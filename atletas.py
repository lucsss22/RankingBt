"""
Atletas — cadastro e login
==========================
Contas dos atletas, convites, sessoes de login e historico de resultados,
guardados em SQLite (atletas.db, na mesma pasta do script).

Seguranca:
  - a senha nunca e gravada: so o hash PBKDF2-SHA256 com sal aleatorio;
  - o numero de iteracoes fica gravado junto do hash, entao da para aumentar
    ITERACOES_PBKDF2 no futuro sem invalidar contas antigas — o hash e refeito
    no proximo login;
  - login errado devolve sempre a mesma mensagem, exista o e-mail ou nao, e
    gasta o mesmo tempo nos dois casos;
  - depois de MAX_TENTATIVAS erros seguidos a conta fica bloqueada por
    BLOQUEIO_MINUTOS;
  - o token de sessao so existe no cookie do navegador; o banco guarda o
    hash dele, entao uma copia do banco nao permite entrar como ninguem;
  - trocar a senha derruba as outras sessoes da conta;
  - toda consulta usa parametros (?) — nada de montar SQL com texto do usuario.

Este modulo nao tem input/print: quem conversa com o usuario e o app.py (e,
depois, a interface grafica).
"""

import datetime
import hashlib
import hmac
import os
import pathlib
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass

PASTA = pathlib.Path(__file__).resolve().parent
# Onde ficam banco, segredo e caches da ITF. BT_DADOS aponta outra pasta — os
# testes usam isso para nunca encostar no banco de verdade.
PASTA_DADOS = pathlib.Path(os.environ.get("BT_DADOS") or PASTA)
ARQUIVO_BANCO = PASTA_DADOS / "atletas.db"

# ─── SENHA ───────────────────────────────────────────────────────────────────
ALGORITMO_HASH = "pbkdf2_sha256"
ITERACOES_PBKDF2 = 600_000   # recomendacao da OWASP (2023) para PBKDF2-HMAC-SHA256
TAMANHO_SAL = 16
SENHA_MIN = 8
SENHA_MAX = 128
# Senhas que caem em qualquer ataque de dicionario. Lista curta de proposito:
# o que protege de verdade e o tamanho minimo.
SENHAS_FRACAS = {
    "12345678", "123456789", "1234567890", "87654321", "11111111", "00000000",
    "password", "password1", "senha123", "senha1234", "qwerty123", "abcd1234",
    "beachtennis", "itf12345",
}

# ─── LOGIN ───────────────────────────────────────────────────────────────────
MAX_TENTATIVAS = 5
BLOQUEIO_MINUTOS = 15
DURACAO_SESSAO_DIAS = 30

# ─── CONVITES ────────────────────────────────────────────────────────────────
# Sem 0/O e 1/I/L: o codigo e ditado e digitado no celular.
ALFABETO_CONVITE = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
VALIDADE_CONVITE_DIAS = 14

# ─── CADASTRO ────────────────────────────────────────────────────────────────
GENEROS = {"M": "masculino", "W": "feminino"}   # mesmos codigos do ranking ITF
NOME_MAX = 100
CIDADE_MAX = 80
EMAIL_MAX = 254
ANO_NASCIMENTO_MIN = 1900
RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RE_NACIONALIDADE = re.compile(r"^[A-Z]{3}$")    # codigo de 3 letras da ITF: BRA, ITA...

CAMPOS_PERFIL = ("nome", "genero", "nome_itf", "ano_nascimento", "nacionalidade", "cidade")
ORIGENS_RESULTADO = ("colocacao", "pontos")

ESQUEMA_V1 = """
CREATE TABLE IF NOT EXISTS atletas (
    id                INTEGER PRIMARY KEY,
    email             TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    senha_hash        TEXT    NOT NULL,
    nome              TEXT    NOT NULL,
    genero            TEXT    NOT NULL CHECK (genero IN ('M', 'W')),
    nome_itf          TEXT,
    itf_player_id     INTEGER UNIQUE,
    ano_nascimento    INTEGER,
    nacionalidade     TEXT,
    cidade            TEXT,
    tentativas_falhas INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate     REAL,
    criado_em         TEXT    NOT NULL,
    atualizado_em     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS resultados (
    id         INTEGER PRIMARY KEY,
    atleta_id  INTEGER NOT NULL REFERENCES atletas(id) ON DELETE CASCADE,
    torneio    TEXT    NOT NULL,
    categoria  TEXT,
    chave      TEXT,
    fase       TEXT,
    rodada     TEXT,
    pontos     INTEGER NOT NULL CHECK (pontos >= 0),
    origem     TEXT    NOT NULL CHECK (origem IN ('colocacao', 'pontos')),
    data       TEXT,
    criado_em  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resultados_atleta ON resultados (atleta_id, data);
"""

# Versao 2: app web — administrador, convites e sessoes de login.
ESQUEMA_V2 = """
ALTER TABLE atletas ADD COLUMN admin INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS convites (
    id          INTEGER PRIMARY KEY,
    codigo      TEXT    NOT NULL UNIQUE,
    criado_por  INTEGER REFERENCES atletas(id) ON DELETE SET NULL,
    criado_em   TEXT    NOT NULL,
    expira_em   TEXT    NOT NULL,
    usado_por   INTEGER REFERENCES atletas(id) ON DELETE SET NULL,
    usado_em    TEXT,
    revogado    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessoes (
    token_hash  TEXT    PRIMARY KEY,
    atleta_id   INTEGER NOT NULL REFERENCES atletas(id) ON DELETE CASCADE,
    criado_em   REAL    NOT NULL,
    expira_em   REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessoes_atleta ON sessoes (atleta_id);
"""

# Versao 3: tierlist salva por atleta e duplas simuladas.
ESQUEMA_V3 = """
CREATE TABLE IF NOT EXISTS tierlists (
    atleta_id     INTEGER PRIMARY KEY REFERENCES atletas(id) ON DELETE CASCADE,
    genero        TEXT    NOT NULL CHECK (genero IN ('M', 'W')),
    chave         TEXT    NOT NULL,
    corte         INTEGER,
    lista         TEXT    NOT NULL,
    atualizado_em TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS duplas_simuladas (
    id         INTEGER PRIMARY KEY,
    atleta_id  INTEGER NOT NULL REFERENCES atletas(id) ON DELETE CASCADE,
    jogador1   TEXT    NOT NULL,
    rank1      INTEGER,
    pontos1    INTEGER,
    jogador2   TEXT    NOT NULL,
    rank2      INTEGER,
    pontos2    INTEGER,
    criado_em  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_duplas_simuladas_atleta ON duplas_simuladas (atleta_id);
"""

# Versao 4: o playerId de quem foi escolhido no ranking da ITF na dupla
# simulada. Com ele o rank sai sempre do ranking do dia, sem busca por nome.
ESQUEMA_V4 = """
ALTER TABLE duplas_simuladas ADD COLUMN itf_id1 INTEGER;
ALTER TABLE duplas_simuladas ADD COLUMN itf_id2 INTEGER;
"""

# Cada versao do esquema e aplicada uma vez, em ordem (PRAGMA user_version).
MIGRACOES = {1: ESQUEMA_V1, 2: ESQUEMA_V2, 3: ESQUEMA_V3, 4: ESQUEMA_V4}

MAX_DUPLAS_SIMULADAS = 20
TAMANHO_MAX_LISTA = 20000   # caracteres da lista colada na tierlist


class ErroValidacao(ValueError):
    """Dados recusados. `erros` mapeia campo -> mensagem."""

    def __init__(self, erros: dict[str, str]):
        self.erros = erros
        super().__init__("; ".join(erros.values()))


class ErroLogin(Exception):
    """E-mail/senha incorretos ou conta bloqueada."""


@dataclass(frozen=True)
class Atleta:
    """Dados publicos da conta — o hash da senha nunca sai do banco."""
    id: int
    email: str
    nome: str
    genero: str
    nome_itf: str | None
    itf_player_id: int | None
    ano_nascimento: int | None
    nacionalidade: str | None
    cidade: str | None
    criado_em: str
    admin: bool = False


def _agora() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _atleta_da_linha(linha: sqlite3.Row) -> Atleta:
    dados = {campo: linha[campo] for campo in Atleta.__dataclass_fields__}
    dados["admin"] = bool(dados["admin"])
    return Atleta(**dados)


# ═══════════════════════════════════════════════════════════════════════════════
# BANCO
# ═══════════════════════════════════════════════════════════════════════════════
def conectar(caminho: pathlib.Path | str = ARQUIVO_BANCO) -> sqlite3.Connection:
    """Abre (e cria, se preciso) o banco. O user_version do SQLite guarda a
    versao do esquema; as MIGRACOES que faltam sao aplicadas em ordem."""
    # O servidor web abre a conexao numa thread e pode usa-la em outra da mesma
    # requisicao. Cada conexao continua sendo de uma requisicao so.
    conn = sqlite3.connect(str(caminho), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    versao = conn.execute("PRAGMA user_version").fetchone()[0]
    for numero in sorted(MIGRACOES):
        if versao < numero:
            with conn:
                conn.executescript(MIGRACOES[numero])
                conn.execute(f"PRAGMA user_version = {numero}")
    return conn


# ═══════════════════════════════════════════════════════════════════════════════
# SENHA
# ═══════════════════════════════════════════════════════════════════════════════
def gerar_hash_senha(senha: str, iteracoes: int = ITERACOES_PBKDF2) -> str:
    sal = secrets.token_bytes(TAMANHO_SAL)
    digest = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, iteracoes)
    return f"{ALGORITMO_HASH}${iteracoes}${sal.hex()}${digest.hex()}"


def conferir_senha(senha: str, guardado: str) -> bool:
    try:
        algoritmo, iteracoes, sal_hex, digest_hex = guardado.split("$")
        if algoritmo != ALGORITMO_HASH:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", senha.encode("utf-8"), bytes.fromhex(sal_hex), int(iteracoes)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _precisa_refazer_hash(guardado: str) -> bool:
    try:
        return int(guardado.split("$")[1]) < ITERACOES_PBKDF2
    except (IndexError, ValueError):
        return True


_HASH_FICTICIO: str | None = None


def _gastar_tempo_de_hash(senha: str) -> None:
    """Login com e-mail inexistente faz o mesmo trabalho que um real — senao o
    tempo de resposta denuncia quais e-mails tem conta."""
    global _HASH_FICTICIO
    if _HASH_FICTICIO is None:
        _HASH_FICTICIO = gerar_hash_senha(secrets.token_hex(16))
    conferir_senha(senha, _HASH_FICTICIO)


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDACAO
# ═══════════════════════════════════════════════════════════════════════════════
def _texto(valor) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()


def validar_email(email) -> str:
    email = _texto(email).lower()
    if not email:
        raise ErroValidacao({"email": "Informe o e-mail."})
    if len(email) > EMAIL_MAX or not RE_EMAIL.match(email):
        raise ErroValidacao({"email": "E-mail inválido."})
    return email


def validar_senha(senha: str, email: str | None = None) -> None:
    erro = None
    if not senha or len(senha) < SENHA_MIN:
        erro = f"A senha precisa ter pelo menos {SENHA_MIN} caracteres."
    elif len(senha) > SENHA_MAX:
        erro = f"A senha pode ter no máximo {SENHA_MAX} caracteres."
    elif not senha.strip():
        erro = "A senha não pode ser só espaços."
    elif senha.lower() in SENHAS_FRACAS:
        erro = "Essa senha é muito comum. Escolha outra."
    elif email and senha.lower() == email.lower():
        erro = "A senha não pode ser igual ao e-mail."
    if erro:
        raise ErroValidacao({"senha": erro})


def validar_perfil(dados: dict, parcial: bool = False) -> dict:
    """Limpa e confere os campos do perfil. Com `parcial`, so os campos
    presentes em `dados` sao conferidos (edicao)."""
    erros: dict[str, str] = {}
    limpo: dict = {}

    def presente(campo: str) -> bool:
        return not parcial or campo in dados

    if presente("nome"):
        nome = _texto(dados.get("nome"))
        if len(nome) < 2:
            erros["nome"] = "Informe o nome (pelo menos 2 letras)."
        elif len(nome) > NOME_MAX:
            erros["nome"] = f"Nome com no máximo {NOME_MAX} caracteres."
        limpo["nome"] = nome

    if presente("genero"):
        genero = _texto(dados.get("genero")).upper()
        if genero not in GENEROS:
            erros["genero"] = "Escolha o ranking: M (masculino) ou W (feminino)."
        limpo["genero"] = genero

    if presente("nome_itf"):
        nome_itf = _texto(dados.get("nome_itf")) or None
        # O match com o ranking precisa de sobrenome e nome.
        if nome_itf and len(nome_itf.split()) < 2:
            erros["nome_itf"] = "Nome na ITF precisa de sobrenome e nome (ex: SILVA Joao)."
        elif nome_itf and len(nome_itf) > NOME_MAX:
            erros["nome_itf"] = f"Nome na ITF com no máximo {NOME_MAX} caracteres."
        limpo["nome_itf"] = nome_itf

    if presente("ano_nascimento"):
        ano = dados.get("ano_nascimento")
        if ano in (None, ""):
            limpo["ano_nascimento"] = None
        else:
            try:
                ano = int(str(ano).strip())
            except ValueError:
                ano = None
            ano_atual = datetime.date.today().year
            if ano is None or not ANO_NASCIMENTO_MIN <= ano <= ano_atual:
                erros["ano_nascimento"] = (
                    f"Ano de nascimento entre {ANO_NASCIMENTO_MIN} e {ano_atual}."
                )
            limpo["ano_nascimento"] = ano

    if presente("nacionalidade"):
        nacionalidade = _texto(dados.get("nacionalidade")).upper() or None
        if nacionalidade and not RE_NACIONALIDADE.match(nacionalidade):
            erros["nacionalidade"] = "Nacionalidade com o código de 3 letras (ex: BRA)."
        limpo["nacionalidade"] = nacionalidade

    if presente("cidade"):
        cidade = _texto(dados.get("cidade")) or None
        if cidade and len(cidade) > CIDADE_MAX:
            erros["cidade"] = f"Cidade com no máximo {CIDADE_MAX} caracteres."
        limpo["cidade"] = cidade

    if erros:
        raise ErroValidacao(erros)
    return limpo


# ═══════════════════════════════════════════════════════════════════════════════
# CONTA
# ═══════════════════════════════════════════════════════════════════════════════
def cadastrar(conn: sqlite3.Connection, dados: dict, senha: str,
              convite: str | None = None) -> Atleta:
    """`dados` tem email + os campos de CAMPOS_PERFIL. Junta todos os erros
    numa ErroValidacao so, para o formulario mostrar tudo de uma vez.

    `convite`: o app web sempre passa (cadastro so por convite) e o convite e
    gasto na mesma transacao que cria a conta. None dispensa o convite — e o
    cadastro local, pelo terminal do proprio PC.
    """
    erros: dict[str, str] = {}
    email = None
    perfil: dict = {}

    codigo_convite = None
    if convite is not None:
        codigo_convite = normalizar_convite(convite)
        if not codigo_convite:
            erros["convite"] = "Informe o código do convite (ex: BT-AB12-CD34)."
        elif not _convite_disponivel(conn, codigo_convite):
            erros["convite"] = "Convite inválido, já usado ou expirado."

    try:
        email = validar_email(dados.get("email"))
    except ErroValidacao as exc:
        erros.update(exc.erros)
    try:
        validar_senha(senha, email)
    except ErroValidacao as exc:
        erros.update(exc.erros)
    try:
        perfil = validar_perfil(dados)
    except ErroValidacao as exc:
        erros.update(exc.erros)

    if email and "email" not in erros:
        existe = conn.execute("SELECT 1 FROM atletas WHERE email = ?", (email,)).fetchone()
        if existe:
            erros["email"] = "Já existe uma conta com esse e-mail."

    if erros:
        raise ErroValidacao(erros)

    agora = _agora()
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO atletas (email, senha_hash, nome, genero, nome_itf,
                                     ano_nascimento, nacionalidade, cidade,
                                     criado_em, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email, gerar_hash_senha(senha), perfil["nome"], perfil["genero"],
                    perfil["nome_itf"], perfil["ano_nascimento"], perfil["nacionalidade"],
                    perfil["cidade"], agora, agora,
                ),
            )
            if codigo_convite:
                # So gasta se ninguem gastou entre a checagem e aqui; senao a
                # excecao desfaz a conta criada acima.
                gasto = conn.execute(
                    """
                    UPDATE convites SET usado_por = ?, usado_em = ?
                     WHERE codigo = ? AND usado_por IS NULL AND revogado = 0 AND expira_em > ?
                    """,
                    (cursor.lastrowid, agora, codigo_convite, agora),
                )
                if gasto.rowcount != 1:
                    raise ErroValidacao({"convite": "Convite inválido, já usado ou expirado."})
    except sqlite3.IntegrityError:
        # Corrida entre a checagem acima e o INSERT.
        raise ErroValidacao({"email": "Já existe uma conta com esse e-mail."}) from None

    return buscar_atleta(conn, cursor.lastrowid)


def autenticar(conn: sqlite3.Connection, email: str, senha: str) -> Atleta:
    mensagem_padrao = "E-mail ou senha incorretos."
    email = _texto(email).lower()

    linha = conn.execute("SELECT * FROM atletas WHERE email = ?", (email,)).fetchone()
    if linha is None:
        _gastar_tempo_de_hash(senha or "")
        raise ErroLogin(mensagem_padrao)

    agora = time.time()
    if linha["bloqueado_ate"] and linha["bloqueado_ate"] > agora:
        minutos = int((linha["bloqueado_ate"] - agora) // 60) + 1
        raise ErroLogin(
            f"Conta bloqueada por excesso de tentativas. Tente de novo em {minutos} min."
        )

    if not conferir_senha(senha or "", linha["senha_hash"]):
        tentativas = linha["tentativas_falhas"] + 1
        bloqueado_ate = None
        if tentativas >= MAX_TENTATIVAS:
            bloqueado_ate = agora + BLOQUEIO_MINUTOS * 60
            tentativas = 0
        with conn:
            conn.execute(
                "UPDATE atletas SET tentativas_falhas = ?, bloqueado_ate = ? WHERE id = ?",
                (tentativas, bloqueado_ate, linha["id"]),
            )
        if bloqueado_ate:
            raise ErroLogin(
                f"{mensagem_padrao} Conta bloqueada por {BLOQUEIO_MINUTOS} min "
                f"depois de {MAX_TENTATIVAS} tentativas."
            )
        raise ErroLogin(mensagem_padrao)

    novo_hash = gerar_hash_senha(senha) if _precisa_refazer_hash(linha["senha_hash"]) else None
    with conn:
        conn.execute(
            """
            UPDATE atletas
               SET tentativas_falhas = 0, bloqueado_ate = NULL,
                   senha_hash = COALESCE(?, senha_hash)
             WHERE id = ?
            """,
            (novo_hash, linha["id"]),
        )
    return _atleta_da_linha(linha)


def buscar_atleta(conn: sqlite3.Connection, atleta_id: int) -> Atleta | None:
    linha = conn.execute("SELECT * FROM atletas WHERE id = ?", (atleta_id,)).fetchone()
    return _atleta_da_linha(linha) if linha else None


def atualizar_perfil(conn: sqlite3.Connection, atleta_id: int, dados: dict) -> Atleta:
    """Atualiza so os campos de CAMPOS_PERFIL presentes em `dados`."""
    dados = {campo: valor for campo, valor in dados.items() if campo in CAMPOS_PERFIL}
    if not dados:
        return buscar_atleta(conn, atleta_id)

    limpo = validar_perfil(dados, parcial=True)
    atual = buscar_atleta(conn, atleta_id)
    if atual and "genero" in limpo and limpo["genero"] != atual.genero:
        # O vinculo era com um jogador do ranking do outro genero.
        limpo["itf_player_id"] = None

    # Os nomes das colunas vem de CAMPOS_PERFIL (ou do codigo acima), nunca do usuario.
    colunas = ", ".join(f"{campo} = ?" for campo in limpo)
    with conn:
        conn.execute(
            f"UPDATE atletas SET {colunas}, atualizado_em = ? WHERE id = ?",
            (*limpo.values(), _agora(), atleta_id),
        )
    return buscar_atleta(conn, atleta_id)


def alterar_senha(conn: sqlite3.Connection, atleta_id: int,
                  senha_atual: str, senha_nova: str,
                  sessao_atual: str | None = None) -> None:
    """Troca a senha e encerra as sessoes da conta, menos `sessao_atual` (o
    token de quem esta trocando, quando a troca vem do app web)."""
    linha = conn.execute(
        "SELECT email, senha_hash FROM atletas WHERE id = ?", (atleta_id,)
    ).fetchone()
    if linha is None or not conferir_senha(senha_atual or "", linha["senha_hash"]):
        raise ErroValidacao({"senha_atual": "Senha atual incorreta."})
    validar_senha(senha_nova, linha["email"])
    with conn:
        conn.execute(
            "UPDATE atletas SET senha_hash = ?, atualizado_em = ? WHERE id = ?",
            (gerar_hash_senha(senha_nova), _agora(), atleta_id),
        )
        conn.execute(
            "DELETE FROM sessoes WHERE atleta_id = ? AND token_hash <> ?",
            (atleta_id, _hash_token(sessao_atual) if sessao_atual else ""),
        )


def definir_admin(conn: sqlite3.Connection, email: str, admin: bool = True) -> Atleta | None:
    """Administrador cria convites e manda baixar o ranking. Feito pelo
    terminal (gerenciar.py), nunca pelo app web."""
    with conn:
        conn.execute(
            "UPDATE atletas SET admin = ?, atualizado_em = ? WHERE email = ?",
            (int(admin), _agora(), _texto(email).lower()),
        )
    linha = conn.execute("SELECT * FROM atletas WHERE email = ?", (_texto(email).lower(),)).fetchone()
    return _atleta_da_linha(linha) if linha else None


def vincular_itf(conn: sqlite3.Connection, atleta_id: int,
                 player_id: int, nome_itf: str) -> Atleta:
    """Liga a conta ao jogador da ITF. Um mesmo jogador da ITF so pode estar
    em uma conta."""
    outro = conn.execute(
        "SELECT id FROM atletas WHERE itf_player_id = ? AND id <> ?", (player_id, atleta_id)
    ).fetchone()
    if outro:
        raise ErroValidacao({"itf_player_id": "Esse jogador da ITF já está vinculado a outra conta."})

    with conn:
        conn.execute(
            "UPDATE atletas SET itf_player_id = ?, nome_itf = ?, atualizado_em = ? WHERE id = ?",
            (player_id, _texto(nome_itf) or None, _agora(), atleta_id),
        )
    return buscar_atleta(conn, atleta_id)


# ═══════════════════════════════════════════════════════════════════════════════
# RESULTADOS
# ═══════════════════════════════════════════════════════════════════════════════
def registrar_resultado(conn: sqlite3.Connection, atleta_id: int, resultado: dict) -> int:
    """`resultado`: torneio, pontos, origem ('colocacao'|'pontos') e, quando
    houver, categoria, chave, fase, rodada e data (AAAA-MM-DD)."""
    erros: dict[str, str] = {}

    torneio = _texto(resultado.get("torneio"))
    if not torneio:
        erros["torneio"] = "Informe o nome do torneio."
    elif len(torneio) > NOME_MAX:
        erros["torneio"] = f"Nome do torneio com no máximo {NOME_MAX} caracteres."

    pontos = resultado.get("pontos")
    if not isinstance(pontos, int) or isinstance(pontos, bool) or pontos < 0:
        erros["pontos"] = "Pontos precisam ser um número inteiro, 0 ou mais."

    origem = resultado.get("origem")
    if origem not in ORIGENS_RESULTADO:
        erros["origem"] = f"Origem precisa ser uma de: {', '.join(ORIGENS_RESULTADO)}."

    data = _texto(resultado.get("data")) or None
    if data:
        try:
            data = datetime.date.fromisoformat(data).isoformat()
        except ValueError:
            erros["data"] = "Data no formato AAAA-MM-DD."

    if erros:
        raise ErroValidacao(erros)

    with conn:
        cursor = conn.execute(
            """
            INSERT INTO resultados (atleta_id, torneio, categoria, chave, fase, rodada,
                                    pontos, origem, data, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                atleta_id, torneio, resultado.get("categoria"), resultado.get("chave"),
                resultado.get("fase"), resultado.get("rodada"), pontos, origem, data, _agora(),
            ),
        )
    return cursor.lastrowid


def listar_resultados(conn: sqlite3.Connection, atleta_id: int) -> list[dict]:
    linhas = conn.execute(
        """
        SELECT id, torneio, categoria, chave, fase, rodada, pontos, origem, data, criado_em
          FROM resultados
         WHERE atleta_id = ?
         ORDER BY COALESCE(data, criado_em) DESC, id DESC
        """,
        (atleta_id,),
    ).fetchall()
    return [dict(linha) for linha in linhas]


def excluir_resultado(conn: sqlite3.Connection, atleta_id: int, resultado_id: int) -> bool:
    """So apaga resultado do proprio atleta."""
    with conn:
        cursor = conn.execute(
            "DELETE FROM resultados WHERE id = ? AND atleta_id = ?", (resultado_id, atleta_id)
        )
    return cursor.rowcount > 0


def data_do_resultado(resultado: dict) -> datetime.date:
    """Data do torneio; sem ela, o dia em que o resultado foi salvo."""
    return datetime.date.fromisoformat((resultado["data"] or resultado["criado_em"])[:10])


def soma_dos_melhores(resultados: list[dict], melhores: int, semanas: int,
                      hoje: datetime.date | None = None) -> int:
    """Regra do ranking aplicada so ao historico salvo aqui — nao e o ranking
    oficial, que tambem conta torneios que o atleta nao salvou."""
    limite = (hoje or datetime.date.today()) - datetime.timedelta(weeks=semanas)
    recentes = sorted(
        (r["pontos"] for r in resultados if data_do_resultado(r) >= limite), reverse=True
    )
    return sum(recentes[:melhores])


# ═══════════════════════════════════════════════════════════════════════════════
# TIERLIST SALVA E DUPLAS SIMULADAS
# ═══════════════════════════════════════════════════════════════════════════════
def salvar_tierlist(conn: sqlite3.Connection, atleta_id: int, genero: str,
                    chave: str, corte: int | None, lista: str) -> None:
    """Uma lista por atleta: a ultima que ele montou."""
    if genero not in GENEROS:
        raise ErroValidacao({"genero": "Escolha o ranking masculino ou feminino."})
    if len(lista) > TAMANHO_MAX_LISTA:
        raise ErroValidacao({"lista": "Lista grande demais."})
    with conn:
        conn.execute(
            """
            INSERT INTO tierlists (atleta_id, genero, chave, corte, lista, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (atleta_id) DO UPDATE SET
                genero = excluded.genero, chave = excluded.chave, corte = excluded.corte,
                lista = excluded.lista, atualizado_em = excluded.atualizado_em
            """,
            (atleta_id, genero, chave, corte, lista, _agora()),
        )


def carregar_tierlist(conn: sqlite3.Connection, atleta_id: int) -> dict | None:
    linha = conn.execute("SELECT * FROM tierlists WHERE atleta_id = ?", (atleta_id,)).fetchone()
    return dict(linha) if linha else None


def _numero_opcional(valor, campo: str, erros: dict) -> int | None:
    texto = _texto(valor)
    if not texto:
        return None
    if not texto.isdigit() or int(texto) < 1:
        erros[campo] = "Use um número inteiro maior que zero."
        return None
    return int(texto)


def adicionar_dupla_simulada(conn: sqlite3.Connection, atleta_id: int, dados: dict) -> int:
    """Cada atleta da dupla: nome e, se quiser, o rank OU os pontos. Sem
    nenhum dos dois, o app procura o nome no ranking. `itf_id{n}` e o
    playerId de quem foi escolhido no ranking: o rank vem de la, entao
    rank e pontos digitados nao valem junto com ele."""
    erros: dict[str, str] = {}
    limpo = {}
    for n in (1, 2):
        nome = _texto(dados.get(f"jogador{n}"))
        if len(nome) < 2:
            erros[f"jogador{n}"] = "Informe o nome do atleta."
        elif len(nome) > NOME_MAX:
            erros[f"jogador{n}"] = f"Nome com no máximo {NOME_MAX} caracteres."
        itf_id = _numero_opcional(dados.get(f"itf_id{n}"), f"jogador{n}", erros)
        rank = None if itf_id else _numero_opcional(dados.get(f"rank{n}"), f"rank{n}", erros)
        pontos = None if itf_id else _numero_opcional(dados.get(f"pontos{n}"), f"pontos{n}", erros)
        if rank and pontos:
            erros[f"pontos{n}"] = "Informe o rank ou os pontos, não os dois."
        limpo.update({f"jogador{n}": nome, f"rank{n}": rank, f"pontos{n}": pontos, f"itf_id{n}": itf_id})

    total = conn.execute(
        "SELECT COUNT(*) FROM duplas_simuladas WHERE atleta_id = ?", (atleta_id,)
    ).fetchone()[0]
    if total >= MAX_DUPLAS_SIMULADAS:
        erros["jogador1"] = f"No máximo {MAX_DUPLAS_SIMULADAS} duplas simuladas. Exclua alguma antes."
    if erros:
        raise ErroValidacao(erros)

    with conn:
        cursor = conn.execute(
            """
            INSERT INTO duplas_simuladas (atleta_id, jogador1, rank1, pontos1, itf_id1,
                                          jogador2, rank2, pontos2, itf_id2, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (atleta_id, limpo["jogador1"], limpo["rank1"], limpo["pontos1"], limpo["itf_id1"],
             limpo["jogador2"], limpo["rank2"], limpo["pontos2"], limpo["itf_id2"], _agora()),
        )
    return cursor.lastrowid


def listar_duplas_simuladas(conn: sqlite3.Connection, atleta_id: int) -> list[dict]:
    linhas = conn.execute(
        "SELECT * FROM duplas_simuladas WHERE atleta_id = ? ORDER BY id", (atleta_id,)
    ).fetchall()
    return [dict(linha) for linha in linhas]


def excluir_dupla_simulada(conn: sqlite3.Connection, atleta_id: int, dupla_id: int) -> bool:
    """So apaga dupla do proprio atleta."""
    with conn:
        cursor = conn.execute(
            "DELETE FROM duplas_simuladas WHERE id = ? AND atleta_id = ?", (dupla_id, atleta_id)
        )
    return cursor.rowcount > 0


# ═══════════════════════════════════════════════════════════════════════════════
# CONVITES
# ═══════════════════════════════════════════════════════════════════════════════
def normalizar_convite(codigo) -> str:
    """Aceita o codigo digitado de qualquer jeito (minusculo, sem tracos, com
    espacos) e devolve no formato BT-XXXX-XXXX, ou "" se nao parecer um."""
    bruto = re.sub(r"[^A-Z0-9]", "", str(codigo or "").upper())
    if len(bruto) == 10 and bruto.startswith("BT"):
        bruto = bruto[2:]
    if len(bruto) != 8:
        return ""
    return f"BT-{bruto[:4]}-{bruto[4:]}"


def _convite_disponivel(conn: sqlite3.Connection, codigo: str) -> bool:
    linha = conn.execute(
        """
        SELECT 1 FROM convites
         WHERE codigo = ? AND usado_por IS NULL AND revogado = 0 AND expira_em > ?
        """,
        (codigo, _agora()),
    ).fetchone()
    return linha is not None


def criar_convite(conn: sqlite3.Connection, criado_por: int | None = None,
                  validade_dias: int = VALIDADE_CONVITE_DIAS) -> str:
    agora = datetime.datetime.now()
    expira = agora + datetime.timedelta(days=validade_dias)
    for _ in range(5):
        corpo = "".join(secrets.choice(ALFABETO_CONVITE) for _ in range(8))
        codigo = f"BT-{corpo[:4]}-{corpo[4:]}"
        try:
            with conn:
                conn.execute(
                    "INSERT INTO convites (codigo, criado_por, criado_em, expira_em) VALUES (?, ?, ?, ?)",
                    (codigo, criado_por, agora.isoformat(timespec="seconds"),
                     expira.isoformat(timespec="seconds")),
                )
            return codigo
        except sqlite3.IntegrityError:
            continue   # codigo repetido (31^8 combinacoes): sorteia outro
    raise RuntimeError("nao consegui gerar um codigo de convite unico")


def listar_convites(conn: sqlite3.Connection) -> list[dict]:
    linhas = conn.execute(
        """
        SELECT c.codigo, c.criado_em, c.expira_em, c.usado_em, c.revogado,
               a.nome AS usado_por_nome
          FROM convites c
          LEFT JOIN atletas a ON a.id = c.usado_por
         ORDER BY c.criado_em DESC, c.id DESC
        """
    ).fetchall()
    agora = _agora()
    convites = []
    for linha in linhas:
        convite = dict(linha)
        if convite["usado_em"]:
            convite["situacao"] = "usado"
        elif convite["revogado"]:
            convite["situacao"] = "cancelado"
        elif convite["expira_em"] <= agora:
            convite["situacao"] = "expirado"
        else:
            convite["situacao"] = "ativo"
        convites.append(convite)
    return convites


def revogar_convite(conn: sqlite3.Connection, codigo: str) -> bool:
    """Cancela um convite que ainda nao foi usado."""
    with conn:
        cursor = conn.execute(
            "UPDATE convites SET revogado = 1 WHERE codigo = ? AND usado_por IS NULL",
            (normalizar_convite(codigo),),
        )
    return cursor.rowcount > 0


# ═══════════════════════════════════════════════════════════════════════════════
# SESSOES (app web)
# ═══════════════════════════════════════════════════════════════════════════════
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def criar_sessao(conn: sqlite3.Connection, atleta_id: int) -> str:
    """Devolve o token que vai no cookie. Aproveita para limpar as vencidas."""
    token = secrets.token_urlsafe(32)
    agora = time.time()
    with conn:
        conn.execute("DELETE FROM sessoes WHERE expira_em < ?", (agora,))
        conn.execute(
            "INSERT INTO sessoes (token_hash, atleta_id, criado_em, expira_em) VALUES (?, ?, ?, ?)",
            (_hash_token(token), atleta_id, agora, agora + DURACAO_SESSAO_DIAS * 86400),
        )
    return token


def atleta_da_sessao(conn: sqlite3.Connection, token: str | None) -> Atleta | None:
    if not token:
        return None
    linha = conn.execute(
        """
        SELECT a.* FROM sessoes s JOIN atletas a ON a.id = s.atleta_id
         WHERE s.token_hash = ? AND s.expira_em > ?
        """,
        (_hash_token(token), time.time()),
    ).fetchone()
    return _atleta_da_linha(linha) if linha else None


def encerrar_sessao(conn: sqlite3.Connection, token: str | None) -> None:
    if not token:
        return
    with conn:
        conn.execute("DELETE FROM sessoes WHERE token_hash = ?", (_hash_token(token),))
