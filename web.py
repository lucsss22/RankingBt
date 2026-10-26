"""
BT Ranking — app web (computador e celular)
===========================================
As funcionalidades do app.py no navegador: cadastro por convite, login,
estimativa e meta de ranking, pontos por rodada (manual ou de um torneio real
da ITF), resultados do atleta na ITF, historico, tierlist de duplas e os dois
temas — A "Areia & Oceano" (claro) e B "Quadra Noturna" (escuro).

O servidor roda neste PC. O celular e os outros atletas entram pelo endereco
gratuito do ngrok; no celular, "Adicionar a tela inicial" instala como app.
Com o PC desligado o app fica fora do ar.

Primeira vez:
    pip install -r requirements.txt
    winget install ngrok.ngrok
    ngrok config add-authtoken <token do painel do ngrok>
    python gerenciar.py convite          # gera o seu convite
    iniciar.bat                          # sobe o servidor e o ngrok
  Crie sua conta no endereco que o ngrok mostrar, com o convite, e depois:
    python gerenciar.py admin seu@email.com

Dia a dia:
    iniciar.bat
"""

import collections
import datetime
import hmac
import ipaddress
import os
import pathlib
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException

import atletas
import estimativa
import itf_beach_tennis_tierlist as itf
import itf_dados
import pontuacao
import resultados_itf
import tierlist_regras

PASTA = pathlib.Path(__file__).resolve().parent
ARQUIVO_SEGREDO = atletas.PASTA_DADOS / "segredo.key"

COOKIE_SESSAO = "bt_sessao"
COOKIE_TEMA = "bt_tema"
TEMAS = ("a", "b")          # a = Areia & Oceano (claro), b = Quadra Noturna (escuro)
TEMA_PADRAO = "a"
# Cookie de sessao so trafega por HTTPS. O ngrok entrega HTTPS, e o navegador
# aceita cookie seguro em http://localhost. BT_COOKIE_SEGURO=0 so para testar
# por IP na rede de casa.
COOKIE_SEGURO = os.environ.get("BT_COOKIE_SEGURO", "1") != "0"
# Mudar ao alterar app.css/app.js: o celular guarda os estaticos em cache.
VERSAO_ESTATICOS = "3"

CATEGORIA_PADRAO = "BT200"
SEM_PONTOS = "sem_pontos"
MAX_DUPLAS_TIERLIST = 128
PAIS_PADRAO = "BRA"
SEMANAS_META_PADRAO = 4        # data da meta sem torneio escolhido
SEMANAS_PROXIMOS_TORNEIOS = 8
MAX_TORNEIOS_LISTA = 40
MINUTOS_ENTRE_ATUALIZACOES = 10  # atividade do mesmo atleta na ITF

# O app fica aberto na internet pelo ngrok. Cada tentativa de entrar ou de se
# cadastrar gasta ~0,5 s de CPU no PBKDF2, e o bloqueio por conta
# (atletas.MAX_TENTATIVAS) nao segura quem testa varios e-mails: por isso
# tambem ha um limite de falhas por endereco de rede.
FALHAS_POR_IP = 10
JANELA_FALHAS_IP = 10 * 60      # segundos
# Maior corpo de pedido aceito. O maior formulario legitimo (lista da tierlist,
# ate 20 mil caracteres) fica bem abaixo; o Starlette le o formulario inteiro
# na memoria, entao um envio gigante nao pode chegar ate ele.
MAX_CORPO_BYTES = 512 * 1024

# 'unsafe-inline' so para estilos: as barras de pontos usam width no style.
CSP = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data:; "
    "connect-src 'self'; manifest-src 'self'; worker-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
)

# Mensagens de sucesso viajam como codigo na URL (?msg=...), nunca como texto:
# assim ninguem monta um link que faz o app "dizer" outra coisa.
MENSAGENS = {
    "bem_vindo": "Conta criada. Bem-vindo(a) ao BT Ranking!",
    "salvo": "Resultado salvo no seu histórico.",
    "removido": "Resultado removido.",
    "perfil": "Cadastro atualizado.",
    "senha": "Senha trocada. As outras sessões da sua conta foram encerradas.",
    "vinculado": "Conta vinculada ao seu cadastro na ITF.",
    "coleta": "Download do ranking iniciado. Leva de 1 a 3 minutos — recarregue para acompanhar.",
    "ocupado": "Já existe uma busca na ITF em andamento. Tente de novo em 1 minuto.",
    "cancelado": "Convite cancelado.",
    "saiu": "Você saiu da sua conta.",
    "lista_salva": "Lista salva.",
    "simulada": "Dupla simulada adicionada.",
    "simulada_excluida": "Dupla simulada excluída.",
    "recente": "Seus resultados foram atualizados há poucos minutos.",
}

# (secao, url, rotulo no celular, rotulo no computador, aparece na barra do celular)
MENU = (
    ("inicio", "/inicio", "Início", "Início", True),
    ("estimar", "/estimar", "Estimar", "Estimar ranking", True),
    ("meta", "/meta", "Meta", "Meta de ranking", False),
    ("pontos", "/pontos", "Pontos", "Pontos por rodada", True),
    ("tierlist", "/tierlist", "Tierlist", "Tierlist de duplas", True),
    ("resultados", "/resultados", "Resultados", "Meus resultados", False),
    ("perfil", "/perfil", "Perfil", "Meu cadastro", True),
)

# Ate onde chegar, na meta de ranking.
FRASES_META = {
    "R48": "Entrar na chave principal", "R32/24": "Entrar na chave principal",
    "R16": "Chegar às oitavas", "QF": "Chegar às quartas", "SF": "Chegar à semifinal",
    "F": "Chegar à final", "W": "Ser campeão",
}

MESES = {
    nome: numero for numero, nome in enumerate(
        ("january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"),
        start=1,
    )
}

app = FastAPI(title="BT Ranking", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=PASTA / "static"), name="static")
templates = Jinja2Templates(directory=PASTA / "templates")
TABELA = pontuacao.carregar_tabela()
MELHORES = pontuacao.melhores_resultados(TABELA)


def carregar_segredo() -> bytes:
    """Chave dos tokens de formulario (CSRF). Criada na primeira execucao."""
    try:
        return bytes.fromhex(ARQUIVO_SEGREDO.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        segredo = secrets.token_bytes(32)
        ARQUIVO_SEGREDO.parent.mkdir(parents=True, exist_ok=True)
        ARQUIVO_SEGREDO.write_text(segredo.hex(), encoding="utf-8")
        return segredo


SEGREDO = carregar_segredo()


# ═══════════════════════════════════════════════════════════════════════════════
# RANKING ITF (cache da tierlist)
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class RankingCarregado:
    """O ranking salvo e o que as telas usam dele a cada pedido, calculado uma
    vez por arquivo baixado (ler os pontos de ~3 mil jogadores e ordenar e o
    que mais pesava nas paginas)."""
    dados: dict
    indice: estimativa.IndiceDeNomes
    ordenados: list[int]        # estimativa.pontos_ordenados
    por_pontos: list[dict]      # estimativa.ordenar_por_pontos
    por_id: dict[int, dict]
    paises: list[str]
    rank_limite: int


_RANKINGS: dict[str, tuple[float, RankingCarregado]] = {}


def _carregar_ranking(genero: str) -> RankingCarregado | None:
    """O ranking salvo pela tierlist (ranking_itf_<genero>.json). Sao ~2 MB,
    entao fica em memoria e so e refeito quando o arquivo muda."""
    caminho = itf.arquivo_cache(genero)
    try:
        modificado = caminho.stat().st_mtime
    except FileNotFoundError:
        return None
    guardado = _RANKINGS.get(genero)
    if guardado and guardado[0] == modificado:
        return guardado[1]
    dados = itf.ler_cache(genero)
    if not dados or len(dados["jogadores"]) < itf.MIN_RANKING_PLAYERS:
        return None
    jogadores = dados["jogadores"]
    por_id: dict[int, dict] = {}
    for jogador in jogadores:   # o primeiro de cada id, como localizar_atleta
        por_id.setdefault(jogador.get("playerId"), jogador)
    carregado = RankingCarregado(
        dados=dados,
        indice=estimativa.IndiceDeNomes(jogadores),
        ordenados=estimativa.pontos_ordenados(jogadores),
        por_pontos=estimativa.ordenar_por_pontos(jogadores),
        por_id=por_id,
        paises=sorted({j.get("playerNationalityCode") for j in jogadores if j.get("playerNationalityCode")}),
        rank_limite=max((j.get("rank") or 0) for j in jogadores),
    )
    _RANKINGS[genero] = (modificado, carregado)
    return carregado


def dados_ranking(genero: str) -> dict | None:
    carregado = _carregar_ranking(genero)
    return carregado.dados if carregado else None


def indice_ranking(genero: str) -> estimativa.IndiceDeNomes | None:
    carregado = _carregar_ranking(genero)
    return carregado.indice if carregado else None


def data_do_ranking(dados: dict | None) -> str:
    """'05 October 2026' (como a ITF manda) -> '05/10/2026'."""
    data = dia_do_ranking(dados)
    return data.strftime("%d/%m/%Y") if data else ((dados or {}).get("rank_date") or "?")


def dia_do_ranking(dados: dict | None) -> datetime.date | None:
    partes = ((dados or {}).get("rank_date") or "").split()
    if len(partes) == 3 and partes[0].isdigit() and partes[2].isdigit() and partes[1].lower() in MESES:
        return datetime.date(int(partes[2]), MESES[partes[1].lower()], int(partes[0]))
    return None


def jogador_do_atleta(atleta: atletas.Atleta, dados: dict | None) -> dict | None:
    if not dados or not atleta.itf_player_id:
        return None
    carregado = _carregar_ranking(atleta.genero)
    if carregado and carregado.dados is dados:
        return carregado.por_id.get(atleta.itf_player_id)
    return estimativa.localizar_atleta(dados["jogadores"], player_id=atleta.itf_player_id)


def resumo_jogador(jogador: dict | None, melhores: int) -> dict | None:
    if not jogador:
        return None
    torneios = itf.parse_inteiro(jogador.get("tournamentsPlayed"))
    return {
        "rank":     itf.parse_inteiro(itf.obter_rank_jogador(jogador)),
        "pontos":   itf.parse_inteiro(itf.obter_pontos_jogador(jogador), 0),
        "torneios": torneios,
        "contando": min(torneios or 0, melhores),
        "nome_itf": itf.obter_nome_jogador(jogador),
        "pais":     jogador.get("playerNationalityCode"),
    }


def sugestao(jogador: dict) -> dict:
    """O que o autocompletar de nomes mostra de cada jogador."""
    return {
        "id":     jogador.get("playerId"),
        "nome":   itf.obter_nome_jogador(jogador),
        "rank":   itf.parse_inteiro(itf.obter_rank_jogador(jogador)),
        "pontos": itf.parse_inteiro(itf.obter_pontos_jogador(jogador), 0),
        "pais":   jogador.get("playerNationalityCode") or "",
    }


def jogador_por_id(genero: str, player_id) -> dict | None:
    """O jogador do ranking salvo com esse playerId, ou None."""
    carregado = _carregar_ranking(genero) if genero in itf.PLAYER_TYPE_LABELS else None
    pid = inteiro(player_id, minimo=1)
    if not carregado or pid is None:
        return None
    return carregado.por_id.get(pid)


def genero_rotulo(genero: str) -> str:
    return itf.PLAYER_TYPE_LABELS.get(genero, genero)


# ═══════════════════════════════════════════════════════════════════════════════
# TAREFAS NA ITF (segundo plano)
# ═══════════════════════════════════════════════════════════════════════════════
# Cada busca abre um Chromium e leva de 20 s a alguns minutos. Uma de cada vez,
# para nao irritar o Incapsula nem pesar no PC. O estado fica em memoria; a
# pagina consulta /tarefa e recarrega quando termina.
_TAREFAS: dict[str, dict] = {}
_TRAVA_TAREFAS = threading.Lock()


def iniciar_tarefa(nome: str, funcao, *args) -> bool:
    with _TRAVA_TAREFAS:
        if any(t.get("rodando") for t in _TAREFAS.values()):
            return False
        _TAREFAS[nome] = {"rodando": True, "inicio": time.time()}
    threading.Thread(target=_executar_tarefa, args=(nome, funcao, args), daemon=True).start()
    return True


def _executar_tarefa(nome: str, funcao, args) -> None:
    estado = {"rodando": False, "ok": False}
    try:
        funcao(*args)
        estado["ok"] = True
    except Exception as exc:
        # A coleta falha de muitos jeitos (rede, Incapsula, Playwright); quem
        # pediu so precisa saber que falhou e tentar de novo.
        estado["erro"] = (str(exc).splitlines() or [exc.__class__.__name__])[0][:200]
    estado["fim"] = time.time()
    _TAREFAS[nome] = estado


def estado_tarefa(nome: str) -> dict | None:
    return _TAREFAS.get(nome)


def tarefa_rodando(nome: str) -> bool:
    return bool((_TAREFAS.get(nome) or {}).get("rodando"))


def coletar_ranking(genero: str) -> None:
    jogadores = itf.buscar_ranking_itf(genero)
    if len(jogadores) < itf.MIN_RANKING_PLAYERS:
        raise RuntimeError("a ITF devolveu um ranking vazio")


# ═══════════════════════════════════════════════════════════════════════════════
# RESULTADOS DO ATLETA NA ITF
# ═══════════════════════════════════════════════════════════════════════════════
def resultados_itf_do_atleta(atleta: atletas.Atleta, dados: dict | None) -> dict | None:
    """Atividade em cache convertida em resultados com pontos, marcando os que
    contam no ranking salvo. None quando ainda nao foi buscada."""
    if not atleta.itf_player_id:
        return None
    atividade = itf_dados.ler_atividade(atleta.itf_player_id)
    if not atividade:
        return None
    itens = atividade.get("itens") or []
    chaves = itf_dados.chaves_em_cache(
        resultados_itf.chave_do_link(i.get("tournamentLink")) for i in itens
    )
    lista = resultados_itf.resultados_do_atleta(
        itens, TABELA, itf_dados.calendario_por_chave(), chaves, atleta.genero
    )
    data_ref = dia_do_ranking(dados) or datetime.date.today()
    resumo = resultados_itf.marcar_contando(lista, data_ref, MELHORES)
    jogador = jogador_do_atleta(atleta, dados)
    oficial = itf.parse_inteiro(itf.obter_pontos_jogador(jogador), 0) if jogador else None
    lista.sort(key=lambda r: r.fim or datetime.date.min, reverse=True)
    corte_recentes = data_ref - datetime.timedelta(weeks=56)
    return {
        "lista": lista,
        "recentes": [r for r in lista if not r.fim or r.fim >= corte_recentes],
        "antigos": [r for r in lista if r.fim and r.fim < corte_recentes],
        "resumo": resumo,
        "oficial": oficial,
        "confere": oficial is not None and resumo["soma"] == oficial,
        "coletado_em": datetime.datetime.fromtimestamp(atividade.get("coletado_em", 0)),
        "data_ref": data_ref,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SESSAO, CSRF E PAGINAS
# ═══════════════════════════════════════════════════════════════════════════════
class PrecisaEntrar(Exception):
    """Pagina de quem esta logado acessada sem sessao."""


def banco():
    conn = atletas.conectar()
    try:
        yield conn
    finally:
        conn.close()


def exigir_atleta(request: Request, conn=Depends(banco)) -> atletas.Atleta:
    atleta = atletas.atleta_da_sessao(conn, request.cookies.get(COOKIE_SESSAO))
    if atleta is None:
        raise PrecisaEntrar()
    return atleta


def exigir_admin(atleta: atletas.Atleta = Depends(exigir_atleta)) -> atletas.Atleta:
    if not atleta.admin:
        raise HTTPException(403, "Só administradores acessam esta página.")
    return atleta


def token_csrf(request: Request) -> str:
    """Amarrado a sessao: um site de fora nao consegue montar um formulario
    valido para o navegador do atleta enviar."""
    sessao = request.cookies.get(COOKIE_SESSAO, "")
    return hmac.new(SEGREDO, sessao.encode("utf-8"), "sha256").hexdigest()[:32]


def conferir_csrf(request: Request, csrf: str = Form("")) -> None:
    if not hmac.compare_digest(csrf, token_csrf(request)):
        raise HTTPException(400, "Formulário expirado. Volte, recarregue a página e tente de novo.")


_FALHAS_IP: dict[str, collections.deque] = {}
_TRAVA_FALHAS = threading.Lock()


def origem_do_pedido(request: Request) -> str:
    """Endereco de quem pediu (o uvicorn ja troca o do ngrok pelo real). Em
    IPv6 conta a rede /64 inteira: cada casa tem milhoes de enderecos."""
    ip = request.client.host if request.client else ""
    try:
        endereco = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if endereco.version == 6 else ip


def _falhas_recentes(origem: str, agora: float) -> collections.deque:
    falhas = _FALHAS_IP.setdefault(origem, collections.deque())
    while falhas and agora - falhas[0] > JANELA_FALHAS_IP:
        falhas.popleft()
    return falhas


def conferir_limite_de_falhas(request: Request) -> None:
    with _TRAVA_FALHAS:
        if len(_falhas_recentes(origem_do_pedido(request), time.monotonic())) >= FALHAS_POR_IP:
            raise HTTPException(429, "Muitas tentativas erradas deste aparelho. "
                                     "Espere alguns minutos e tente de novo.")


def registrar_falha(request: Request) -> None:
    agora = time.monotonic()
    with _TRAVA_FALHAS:
        _falhas_recentes(origem_do_pedido(request), agora).append(agora)
        if len(_FALHAS_IP) > 5000:   # nao deixa a tabela crescer sem fim
            for origem in [o for o, f in _FALHAS_IP.items() if not f or agora - f[-1] > JANELA_FALHAS_IP]:
                del _FALHAS_IP[origem]


def tema_de(request: Request) -> str:
    tema = request.cookies.get(COOKIE_TEMA)
    return tema if tema in TEMAS else TEMA_PADRAO


def pagina(request: Request, template: str, atleta: atletas.Atleta | None = None,
           status_code: int = 200, **contexto):
    return templates.TemplateResponse(
        request,
        template,
        {
            "atleta":   atleta,
            "tema":     tema_de(request),
            "csrf":     token_csrf(request),
            "versao":   VERSAO_ESTATICOS,
            "menu":     MENU,
            "mensagem": MENSAGENS.get(request.query_params.get("msg", "")),
            **contexto,
        },
        status_code=status_code,
    )


def ir(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def gravar_sessao(resposta: RedirectResponse, token: str) -> RedirectResponse:
    resposta.set_cookie(
        COOKIE_SESSAO, token,
        max_age=atletas.DURACAO_SESSAO_DIAS * 86400,
        httponly=True, secure=COOKIE_SEGURO, samesite="lax", path="/",
    )
    return resposta


def inteiro(texto, minimo: int = 0) -> int | None:
    try:
        valor = int(str(texto).strip())
    except (TypeError, ValueError):
        return None
    return valor if valor >= minimo else None


@app.exception_handler(PrecisaEntrar)
async def _redirecionar_para_login(request: Request, exc: PrecisaEntrar):
    return ir("/entrar")


@app.exception_handler(HTTPException)
async def _pagina_de_erro(request: Request, exc: HTTPException):
    mensagem = exc.detail if exc.status_code != 404 else "Página não encontrada."
    return pagina(request, "erro.html", status_code=exc.status_code,
                  codigo=exc.status_code, erro=mensagem)


class LimiteDeCorpo:
    """Recusa pedido com corpo maior que `maximo` antes de alguem ler o
    formulario: pelo Content-Length, ou contando os bytes quando ele nao vem."""

    def __init__(self, app, maximo: int):
        self.app = app
        self.maximo = maximo

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        tamanho = dict(scope.get("headers") or []).get(b"content-length", b"")
        if tamanho.isdigit() and int(tamanho) > self.maximo:
            return await PlainTextResponse("Envio grande demais.", status_code=413)(scope, receive, send)
        recebido = 0

        async def receber():
            nonlocal recebido
            mensagem = await receive()
            if mensagem["type"] == "http.request":
                recebido += len(mensagem.get("body", b""))
                if recebido > self.maximo:
                    raise HTTPException(413, "Envio grande demais.")
            return mensagem

        return await self.app(scope, receber, send)


app.add_middleware(LimiteDeCorpo, maximo=MAX_CORPO_BYTES)


@app.middleware("http")
async def _cabecalhos_de_seguranca(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers.setdefault("Content-Security-Policy", CSP)
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("X-Frame-Options", "DENY")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    resposta.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/static/"):
        resposta.headers["Cache-Control"] = "public, max-age=604800"
    else:
        # Paginas com dados do atleta nao ficam em cache de ninguem.
        resposta.headers.setdefault("Cache-Control", "no-store")
    return resposta


# ═══════════════════════════════════════════════════════════════════════════════
# PWA, TEMA E TAREFAS
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Servido na raiz para controlar o site inteiro.
    return FileResponse(PASTA / "static" / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifesto():
    return FileResponse(PASTA / "static" / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/offline")
def offline(request: Request):
    return pagina(request, "offline.html")


@app.post("/tema")
def trocar_tema(request: Request, tema: str = Form(TEMA_PADRAO)):
    """Para quando o JavaScript nao carregou; normalmente o botao troca o
    tema na hora, sem recarregar."""
    volta = urllib.parse.urlsplit(request.headers.get("referer", "")).path or "/"
    # "//outro.site/..." (ou "/\outro.site") o navegador le como outro site.
    if not volta.startswith("/") or volta.startswith(("//", "/\\")):
        volta = "/"
    resposta = ir(volta)
    resposta.set_cookie(COOKIE_TEMA, tema if tema in TEMAS else TEMA_PADRAO,
                        max_age=365 * 86400, samesite="lax", path="/")
    return resposta


@app.get("/tarefa")
def status_tarefa(request: Request, atleta=Depends(exigir_atleta)):
    """A pagina pergunta aqui se a busca na ITF terminou (app.js)."""
    estado = estado_tarefa(request.query_params.get("nome", "")) or {}
    return JSONResponse({"rodando": bool(estado.get("rodando")),
                         "ok": estado.get("ok"), "erro": estado.get("erro")})


# ═══════════════════════════════════════════════════════════════════════════════
# CONTA
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/")
def raiz(request: Request, conn=Depends(banco)):
    logado = atletas.atleta_da_sessao(conn, request.cookies.get(COOKIE_SESSAO))
    return ir("/inicio" if logado else "/entrar")


@app.get("/entrar")
def entrar(request: Request, conn=Depends(banco)):
    if atletas.atleta_da_sessao(conn, request.cookies.get(COOKIE_SESSAO)):
        return ir("/inicio")
    return pagina(request, "entrar.html", email="")


@app.post("/entrar")
def entrar_enviar(request: Request, email: str = Form(""), senha: str = Form(""),
                  _=Depends(conferir_limite_de_falhas), conn=Depends(banco)):
    try:
        atleta = atletas.autenticar(conn, email, senha)
    except atletas.ErroLogin as exc:
        registrar_falha(request)
        return pagina(request, "entrar.html", status_code=400, erro=str(exc), email=email)
    return gravar_sessao(ir("/inicio"), atletas.criar_sessao(conn, atleta.id))


@app.get("/cadastro")
def cadastro(request: Request):
    convite = atletas.normalizar_convite(request.query_params.get("convite", ""))
    return pagina(request, "cadastro.html", dados={"convite": convite}, erros={})


@app.post("/cadastro")
def cadastro_enviar(
    request: Request,
    convite: str = Form(""), email: str = Form(""), senha: str = Form(""),
    senha2: str = Form(""), nome: str = Form(""), genero: str = Form(""),
    nome_itf: str = Form(""), ano_nascimento: str = Form(""),
    nacionalidade: str = Form(""), cidade: str = Form(""),
    _=Depends(conferir_limite_de_falhas), conn=Depends(banco),
):
    dados = {
        "convite": convite, "email": email, "nome": nome, "genero": genero,
        "nome_itf": nome_itf, "ano_nascimento": ano_nascimento,
        "nacionalidade": nacionalidade, "cidade": cidade,
    }
    if senha != senha2:
        return pagina(request, "cadastro.html", status_code=400, dados=dados,
                      erros={"senha2": "As senhas não conferem."})
    try:
        atleta = atletas.cadastrar(conn, dados, senha, convite=convite)
    except atletas.ErroValidacao as exc:
        # Conta como falha: e o que segura quem tenta adivinhar convites.
        registrar_falha(request)
        return pagina(request, "cadastro.html", status_code=400, dados=dados, erros=exc.erros)
    return gravar_sessao(ir("/inicio?msg=bem_vindo"), atletas.criar_sessao(conn, atleta.id))


@app.post("/sair")
def sair(request: Request, _=Depends(conferir_csrf), conn=Depends(banco)):
    atletas.encerrar_sessao(conn, request.cookies.get(COOKIE_SESSAO))
    resposta = ir("/entrar?msg=saiu")
    resposta.delete_cookie(COOKIE_SESSAO, path="/")
    return resposta


# ═══════════════════════════════════════════════════════════════════════════════
# INICIO
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/inicio")
def inicio(request: Request, atleta=Depends(exigir_atleta), conn=Depends(banco)):
    dados = dados_ranking(atleta.genero)
    preview = pontuacao.rodadas_com_pontos(TABELA, CATEGORIA_PADRAO, "32x32")["principal"][:4]
    coleta = estado_tarefa(f"ranking:{atleta.genero}") if atleta.admin else None
    return pagina(
        request, "inicio.html", atleta,
        secao="inicio",
        dados=dados,
        data_ranking=data_do_ranking(dados),
        resumo=resumo_jogador(jogador_do_atleta(atleta, dados), MELHORES),
        melhores=MELHORES,
        resultados=atletas.listar_resultados(conn, atleta.id)[:3],
        preview=[{**r, "pct": round(r["pontos"] / preview[0]["pontos"] * 100)} for r in preview],
        coleta=coleta,
        coleta_minutos=int((time.time() - coleta["inicio"]) // 60) if coleta and coleta.get("rodando") else None,
        genero_rotulo=genero_rotulo(atleta.genero),
    )


@app.post("/ranking/atualizar")
def atualizar_ranking(genero: str = Form(""), _=Depends(conferir_csrf),
                      atleta=Depends(exigir_admin)):
    if genero not in itf.PLAYER_TYPE_LABELS:
        raise HTTPException(400, "Ranking inválido.")
    iniciou = iniciar_tarefa(f"ranking:{genero}", coletar_ranking, genero)
    return ir("/inicio?msg=" + ("coleta" if iniciou else "ocupado"))


@app.get("/ranking/buscar")
def buscar_no_ranking(request: Request, atleta=Depends(exigir_atleta)):
    """Autocompletar de nomes do ranking salvo (app.js, dupla simulada)."""
    genero = request.query_params.get("genero", "")
    texto = request.query_params.get("q", "")[:atletas.NOME_MAX]
    indice = indice_ranking(genero) if genero in itf.PLAYER_TYPE_LABELS else None
    if indice is None or len(texto.strip()) < 2:
        return JSONResponse({"jogadores": []})
    return JSONResponse({"jogadores": [sugestao(j) for j in indice.sugerir(texto)]})


# ═══════════════════════════════════════════════════════════════════════════════
# PONTOS POR RODADA
# ═══════════════════════════════════════════════════════════════════════════════
def escolher_categoria(categorias: list[dict], categoria_id: str | None) -> dict:
    por_id = {c["id"]: c for c in categorias}
    return por_id.get(categoria_id) or por_id.get(CATEGORIA_PADRAO) or categorias[0]


def escolher_chave(categoria: dict, chave_id: str | None) -> dict:
    for chave in categoria["chaves"]:
        if chave["id"] == chave_id:
            return chave
    # Sem escolha, a chave mais comum (32x32) quando existe.
    return next((c for c in categoria["chaves"] if c["id"] == "32x32"), categoria["chaves"][0])


def com_percentual(linhas: list[dict], maximo: int) -> list[dict]:
    return [{**r, "pct": max(2, round(r["pontos"] / maximo * 100)) if maximo and r["pontos"] else 0}
            for r in linhas]


def tabela_da_chave(categoria: dict, chave: dict) -> dict:
    """O que a tabela de pontos (_tabela_pontos.html) precisa."""
    rodadas = pontuacao.rodadas_com_pontos(TABELA, categoria["id"], chave["id"])
    maximo = max((r["pontos"] for r in rodadas["principal"]), default=0)
    return {
        "chave": chave,
        "descricao_chave": pontuacao.descrever_chave(chave),
        "rodadas": {fase: com_percentual(linhas, maximo) for fase, linhas in rodadas.items()},
        "bundles": [(b, pontuacao.nome_bundle(TABELA, b)) for b in categoria.get("bundles", {})],
    }


def pais_padrao(atleta: atletas.Atleta) -> str:
    return atleta.nacionalidade or PAIS_PADRAO


def data_do_calendario(texto: str | None) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat((texto or "")[:10])
    except ValueError:
        return None


def torneios_do_calendario(calendario: dict | None, busca: str = "", pais: str = "",
                           de: datetime.date | None = None, ate: datetime.date | None = None,
                           limite: int = MAX_TORNEIOS_LISTA) -> list[dict]:
    termo = busca.strip().lower()
    saida = []
    for t in (calendario or {}).get("torneios", []):
        inicio = data_do_calendario(t.get("startDate"))
        fim = data_do_calendario(t.get("endDate")) or inicio
        if pais and t.get("hostNationCode") != pais:
            continue
        if de and (fim or datetime.date.min) < de:
            continue
        if ate and (inicio or datetime.date.max) > ate:
            continue
        if termo and termo not in f"{t.get('tournamentName', '')} {t.get('location', '')}".lower():
            continue
        categoria, _ = resultados_itf.categoria_do_torneio(t.get("tournamentName"), t.get("category"))
        saida.append({**t, "inicio": inicio, "fim": fim, "categoria_id": categoria})
    saida.sort(key=lambda t: t["inicio"] or datetime.date.max)
    return saida[:limite]


def paises_do_calendario(calendario: dict | None) -> list[str]:
    return sorted({t.get("hostNationCode") for t in (calendario or {}).get("torneios", [])
                   if t.get("hostNationCode")})


def info_calendario(calendario: dict | None) -> dict:
    if not calendario:
        return {"existe": False}
    return {"existe": True, "fresco": itf_dados.calendario_fresco(calendario),
            "coletado_em": datetime.datetime.fromtimestamp(calendario.get("coletado_em", 0))}


@app.get("/pontos")
def pontos(request: Request, atleta=Depends(exigir_atleta)):
    q = request.query_params
    categorias = pontuacao.listar_categorias(TABELA)
    modo = "manual" if (q.get("cat") or q.get("chave") or q.get("modo") == "manual") else "torneio"
    contexto = {"secao": "pontos", "categorias": categorias, "tabela": TABELA, "modo": modo,
                "tarefa_calendario": tarefa_rodando("calendario")}

    if modo == "manual":
        categoria = escolher_categoria(categorias, q.get("cat"))
        contexto.update(categoria=categoria, chave=None, rodadas=None)
        if categoria.get("por_colocacao", True):
            contexto.update(tabela_da_chave(categoria, escolher_chave(categoria, q.get("chave"))))
        return pagina(request, "pontos.html", atleta, **contexto)

    calendario = itf_dados.ler_calendario()
    contexto["calendario"] = info_calendario(calendario)
    chave_torneio = (q.get("torneio") or "").strip().upper()
    if not chave_torneio:
        pais = q.get("pais", pais_padrao(atleta))
        periodo = q.get("periodo") if q.get("periodo") in ("proximos", "recentes", "todos") else "proximos"
        hoje = datetime.date.today()
        de, ate = {"proximos": (hoje, None), "recentes": (hoje - datetime.timedelta(days=60), hoje),
                   "todos": (None, None)}[periodo]
        contexto.update(
            busca=q.get("busca", ""), pais=pais, periodo=periodo,
            paises=paises_do_calendario(calendario),
            torneios=torneios_do_calendario(calendario, q.get("busca", ""), pais, de, ate),
        )
        return pagina(request, "pontos.html", atleta, **contexto)

    torneio = itf_dados.calendario_por_chave(calendario).get(chave_torneio)
    if not torneio:
        raise HTTPException(404, "Torneio não encontrado no calendário.")
    categoria_id, motivo = resultados_itf.categoria_do_torneio(torneio.get("tournamentName"), torneio.get("category"))
    genero = q.get("genero") if q.get("genero") in ("M", "W") else atleta.genero
    chave_itf = itf_dados.ler_chave(chave_torneio)
    estrutura = ((chave_itf or {}).get("eventos") or {}).get(genero) if chave_itf else None
    contexto.update(
        torneio={**torneio, "inicio": data_do_calendario(torneio.get("startDate")),
                 "fim": data_do_calendario(torneio.get("endDate"))},
        chave_torneio=chave_torneio, genero=genero, generos=itf.PLAYER_TYPE_LABELS,
        motivo=motivo, chave_itf=chave_itf, estrutura=estrutura,
        chave_consultada_em=datetime.datetime.fromtimestamp(chave_itf["coletado_em"]) if chave_itf else None,
        tarefa_chave=tarefa_rodando(f"chave:{chave_torneio}"),
        pode_buscar_chave=itf_dados.precisa_buscar_chave(chave_torneio),
    )
    if categoria_id:
        categoria = pontuacao.obter_categoria(TABELA, categoria_id)
        contexto["categoria"] = categoria
        if not categoria.get("por_colocacao", True):
            contexto.update(chave=None, rodadas=None)
        elif estrutura and estrutura.get("principal"):
            qualy = estrutura.get("qualifying")
            chave = resultados_itf.chave_da_tabela(
                TABELA, categoria_id, estrutura["principal"]["tamanho"],
                qualy["tamanho"] if qualy else 0,
            )
            contexto.update(tabela_da_chave(categoria, chave), chave_automatica=True)
        else:
            contexto.update(tabela_da_chave(categoria, escolher_chave(categoria, q.get("chave_manual"))),
                            chave_automatica=False)
    return pagina(request, "pontos.html", atleta, **contexto)


@app.post("/itf/calendario")
def buscar_calendario(voltar: str = Form("/pontos"), _=Depends(conferir_csrf),
                      atleta=Depends(exigir_atleta)):
    voltar = voltar if voltar in ("/pontos", "/meta") else "/pontos"
    if itf_dados.calendario_fresco():
        return ir(voltar)
    iniciou = iniciar_tarefa("calendario", itf_dados.atualizar_calendario)
    return ir(f"{voltar}?aguardar=calendario" if iniciou else f"{voltar}?msg=ocupado")


@app.post("/itf/chave")
def buscar_chave(torneio: str = Form(""), _=Depends(conferir_csrf), atleta=Depends(exigir_atleta)):
    chave = torneio.strip().upper()
    if chave not in itf_dados.calendario_por_chave():
        raise HTTPException(400, "Torneio não encontrado no calendário.")
    destino = f"/pontos?torneio={urllib.parse.quote(chave)}"
    if not itf_dados.precisa_buscar_chave(chave):
        return ir(destino)
    iniciou = iniciar_tarefa(f"chave:{chave}", itf_dados.atualizar_chave, chave)
    return ir(destino + ("&aguardar=1" if iniciou else "&msg=ocupado"))


# ═══════════════════════════════════════════════════════════════════════════════
# ESTIMATIVA
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/estimar")
def estimar(request: Request, atleta=Depends(exigir_atleta)):
    q = request.query_params
    melhores = MELHORES
    carregado = _carregar_ranking(atleta.genero)
    dados = carregado.dados if carregado else None
    jogador = jogador_do_atleta(atleta, dados)

    modo = q.get("modo") if q.get("modo") in ("colocacao", "pontos") else "colocacao"
    categorias = [c for c in pontuacao.listar_categorias(TABELA) if c.get("por_colocacao", True)]
    categoria = escolher_categoria(categorias, q.get("cat"))
    chave = escolher_chave(categoria, q.get("chave"))
    rodadas = pontuacao.rodadas_com_pontos(TABELA, categoria["id"], chave["id"])

    # Escolhas que nao existem na categoria/chave atual (trocou de categoria
    # no meio) voltam ao padrao em vez de virar erro.
    fase = "qualifying" if q.get("fase") == "qualifying" and rodadas["qualifying"] else "principal"
    codigos = {r["codigo"] for r in rodadas[fase]} | {SEM_PONTOS}
    rodada = q.get("rodada") if q.get("rodada") in codigos else None
    bundles_disponiveis = list(categoria.get("bundles", {})) if fase == "principal" else []
    bundles = [b for b in q.getlist("bundles") if b in bundles_disponiveis]
    bonus_codigos = {r["codigo"] for r in rodadas["bonus"]} if fase == "principal" else set()
    bonus = q.get("bonus") if q.get("bonus") in bonus_codigos else None

    erro = None
    pontos_torneio = None
    calculo = None
    if modo == "colocacao" and rodada == SEM_PONTOS:
        pontos_torneio = 0
    elif modo == "colocacao" and rodada:
        calculo = pontuacao.calcular_pontos(
            TABELA, categoria["id"], chave["id"], fase, rodada, bundles, bonus
        )
        pontos_torneio = calculo.total
    elif modo == "pontos" and q.get("pontos", "").strip():
        pontos_torneio = inteiro(q.get("pontos"))
        if pontos_torneio is None:
            erro = "Os pontos precisam ser um número inteiro, 0 ou mais."

    torneios = itf.parse_inteiro(jogador.get("tournamentsPlayed")) if jogador else 0
    pede_pior = jogador is not None and (torneios is None or torneios >= melhores)

    # Com os resultados da ITF batendo com o total oficial, o pior resultado
    # que conta e conhecido: a estimativa sai exata sem o atleta digitar nada.
    pior_itf = None
    itf_resultados = resultados_itf_do_atleta(atleta, dados) if pede_pior else None
    if itf_resultados and itf_resultados["confere"] and itf_resultados["resumo"]["pior"]:
        pior_itf = itf_resultados["resumo"]["pior"]
    pior_digitado = q.get("pior", "").strip()
    pior = inteiro(pior_digitado) if pede_pior and pior_digitado else (pior_itf.pontos if pior_itf else None)

    resultado = None
    if dados and pontos_torneio is not None:
        resultado = estimativa.estimar_ranking(
            dados["jogadores"], jogador, pontos_torneio, melhores, pior, ordenados=carregado.ordenados
        )

    rodada_salvar = rodada if rodada and rodada != SEM_PONTOS else ""
    if rodada_salvar and bonus:
        rodada_salvar += f" + bonus {bonus}"

    return pagina(
        request, "estimar.html", atleta,
        secao="estimar",
        dados=dados, data_ranking=data_do_ranking(dados),
        genero_rotulo=genero_rotulo(atleta.genero),
        vinculado=jogador is not None,
        modo=modo, categorias=categorias, categoria=categoria, chave=chave,
        descrever_chave=pontuacao.descrever_chave,
        rodadas=rodadas, fase=fase, rodada=rodada, SEM_PONTOS=SEM_PONTOS,
        bundles_disponiveis=[(b, pontuacao.nome_bundle(TABELA, b)) for b in bundles_disponiveis],
        bundles=bundles, bonus=bonus,
        pontos_digitados=q.get("pontos", ""),
        pede_pior=pede_pior and not pior_itf, pior=pior_digitado, pior_itf=pior_itf, melhores=melhores,
        calculo=calculo, pontos_torneio=pontos_torneio, resultado=resultado, erro=erro,
        rodada_salvar=rodada_salvar,
        torneio_nome=q.get("torneio_nome", "")[:100],
        hoje=datetime.date.today().isoformat(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# META DE RANKING
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/meta")
def meta(request: Request, atleta=Depends(exigir_atleta)):
    q = request.query_params
    carregado = _carregar_ranking(atleta.genero)
    dados = carregado.dados if carregado else None
    jogador = jogador_do_atleta(atleta, dados)
    resumo = resumo_jogador(jogador, MELHORES)
    calendario = itf_dados.ler_calendario()
    pais = q.get("pais", pais_padrao(atleta))
    contexto = {
        "secao": "meta", "dados": dados, "data_ranking": data_do_ranking(dados),
        "genero_rotulo": genero_rotulo(atleta.genero), "resumo": resumo,
        "alvo": q.get("alvo", ""), "pais": pais, "paises": paises_do_calendario(calendario),
        "calendario": info_calendario(calendario), "meta": None, "erro": None,
        "tarefa_calendario": tarefa_rodando("calendario"), "melhores": MELHORES,
    }
    alvo = inteiro(q.get("alvo"), minimo=1)
    if not dados:
        return pagina(request, "meta.html", atleta, **contexto)
    if q.get("alvo", "").strip() and alvo is None:
        contexto["erro"] = "A posição precisa ser um número inteiro maior que zero."
    if alvo is None:
        return pagina(request, "meta.html", atleta, **contexto)

    hoje = datetime.date.today()
    data_ref = dia_do_ranking(dados) or hoje
    data_alvo = hoje + datetime.timedelta(weeks=SEMANAS_META_PADRAO)
    necessario, no_alvo = estimativa.pontos_para_posicao(
        dados["jogadores"], alvo, atleta.itf_player_id, por_pontos=carregado.por_pontos
    )

    # Com os resultados da ITF a meta sabe o que vence ate a data; sem eles,
    # usa o total oficial (conservador quando o atleta ja tem 10 torneios).
    itf_resultados = resultados_itf_do_atleta(atleta, dados)
    if itf_resultados:
        lista = itf_resultados["lista"]

        def validos(data):
            return resultados_itf.pontos_validos(lista, data)

        vencendo = [r for r in lista if r.ativo and r.vence and r.vence <= data_alvo]
    else:
        base = estimativa.validos_sem_historico(
            resumo["pontos"] if resumo else 0, resumo["torneios"] if resumo else 0, MELHORES
        )

        def validos(data):
            return list(base)

        vencendo = []

    total_hoje = estimativa.soma_dos_melhores(validos(data_ref), MELHORES)
    validos_alvo = validos(data_alvo)
    total_alvo = estimativa.soma_dos_melhores(validos_alvo, MELHORES)

    proximos = []
    for t in torneios_do_calendario(calendario, pais=pais, de=hoje,
                                    ate=hoje + datetime.timedelta(weeks=SEMANAS_PROXIMOS_TORNEIOS)):
        if not t["categoria_id"] or not t["fim"]:
            continue
        categoria = pontuacao.obter_categoria(TABELA, t["categoria_id"])
        if not categoria.get("por_colocacao", True):
            continue
        entrada = resultados_itf.entrada_no_ranking(t["fim"])
        chave, rodadas = estimativa.rodadas_da_chave(TABELA, t["categoria_id"])
        base_torneio = validos(entrada)
        proximos.append({
            **t, "entrada": entrada,
            "rodada": estimativa.rodada_minima(rodadas, base_torneio, necessario, MELHORES),
            "total_antes": estimativa.soma_dos_melhores(base_torneio, MELHORES),
        })

    contexto["meta"] = {
        "alvo": alvo,
        "necessario": necessario,
        "no_alvo": itf.obter_nome_jogador(no_alvo) if no_alvo else None,
        "ja_alcancado": bool(resumo and resumo["rank"] and resumo["rank"] <= alvo),
        "total_hoje": total_hoje,
        "total_alvo": total_alvo,
        "data_alvo": data_alvo,
        "vencendo": vencendo,
        "faltam": max(0, necessario - total_alvo),
        "por_categoria": estimativa.meta_por_categoria(TABELA, validos_alvo, necessario, MELHORES),
        "proximos": proximos,
        "com_itf": itf_resultados is not None,
        "confere": bool(itf_resultados and itf_resultados["confere"]),
        "conservador": itf_resultados is None and bool(resumo and (resumo["torneios"] or 0) >= MELHORES),
    }
    contexto["frases"] = FRASES_META
    return pagina(request, "meta.html", atleta, **contexto)


# ═══════════════════════════════════════════════════════════════════════════════
# RESULTADOS
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/resultados")
def resultados(request: Request, atleta=Depends(exigir_atleta), conn=Depends(banco)):
    lista = atletas.listar_resultados(conn, atleta.id)
    regras = TABELA["regras_ranking"]
    return pagina(
        request, "resultados.html", atleta,
        secao="resultados",
        resultados=[{**r, "data_txt": atletas.data_do_resultado(r).strftime("%d/%m/%Y")} for r in lista],
        soma=atletas.soma_dos_melhores(lista, regras["melhores_resultados"], regras["janela_semanas"]),
        melhores=regras["melhores_resultados"], semanas=regras["janela_semanas"],
    )


@app.post("/resultados")
def salvar_resultado(
    request: Request,
    torneio: str = Form(""), data: str = Form(""), pontos: str = Form(""),
    origem: str = Form(""), categoria: str = Form(""), chave: str = Form(""),
    fase: str = Form(""), rodada: str = Form(""),
    _=Depends(conferir_csrf), atleta=Depends(exigir_atleta), conn=Depends(banco),
):
    try:
        atletas.registrar_resultado(conn, atleta.id, {
            "torneio": torneio, "data": data, "pontos": inteiro(pontos), "origem": origem,
            "categoria": categoria or None, "chave": chave or None,
            "fase": fase or None, "rodada": rodada or None,
        })
    except atletas.ErroValidacao as exc:
        raise HTTPException(400, "Não deu para salvar: " + str(exc)) from None
    return ir("/resultados?msg=salvo")


@app.post("/resultados/{resultado_id}/remover")
def remover_resultado(resultado_id: int, _=Depends(conferir_csrf),
                      atleta=Depends(exigir_atleta), conn=Depends(banco)):
    atletas.excluir_resultado(conn, atleta.id, resultado_id)
    return ir("/resultados?msg=removido")


# ═══════════════════════════════════════════════════════════════════════════════
# PERFIL
# ═══════════════════════════════════════════════════════════════════════════════
def pagina_perfil(request: Request, atleta: atletas.Atleta, status_code: int = 200,
                  dados: dict | None = None, erros: dict | None = None,
                  erros_senha: dict | None = None):
    ranking = dados_ranking(atleta.genero)
    tarefa = f"atividade:{atleta.itf_player_id}" if atleta.itf_player_id else None
    return pagina(
        request, "perfil.html", atleta, status_code=status_code,
        secao="perfil",
        dados=dados or {campo: getattr(atleta, campo) for campo in atletas.CAMPOS_PERFIL},
        erros=erros or {}, erros_senha=erros_senha or {},
        generos=atletas.GENEROS,
        itf=resultados_itf_do_atleta(atleta, ranking),
        tarefa_itf=tarefa,
        buscando_itf=bool(tarefa and tarefa_rodando(tarefa)),
        erro_itf=(estado_tarefa(tarefa) or {}).get("erro") if tarefa else None,
        melhores=MELHORES,
        data_ranking=data_do_ranking(ranking),
    )


@app.get("/perfil")
def perfil(request: Request, atleta=Depends(exigir_atleta)):
    return pagina_perfil(request, atleta)


@app.post("/perfil")
def perfil_salvar(
    request: Request,
    nome: str = Form(""), genero: str = Form(""), nome_itf: str = Form(""),
    ano_nascimento: str = Form(""), nacionalidade: str = Form(""), cidade: str = Form(""),
    _=Depends(conferir_csrf), atleta=Depends(exigir_atleta), conn=Depends(banco),
):
    dados = {"nome": nome, "genero": genero, "nome_itf": nome_itf,
             "ano_nascimento": ano_nascimento, "nacionalidade": nacionalidade, "cidade": cidade}
    try:
        atletas.atualizar_perfil(conn, atleta.id, dados)
    except atletas.ErroValidacao as exc:
        return pagina_perfil(request, atleta, 400, dados=dados, erros=exc.erros)
    return ir("/perfil?msg=perfil")


@app.post("/perfil/resultados/atualizar")
def perfil_atualizar_resultados(_=Depends(conferir_csrf), atleta=Depends(exigir_atleta)):
    """Busca na ITF os torneios do proprio atleta (so do vinculado)."""
    if not atleta.itf_player_id:
        raise HTTPException(400, "Vincule sua conta ao ranking ITF antes.")
    atividade = itf_dados.ler_atividade(atleta.itf_player_id)
    if atividade and time.time() - atividade.get("coletado_em", 0) < MINUTOS_ENTRE_ATUALIZACOES * 60:
        return ir("/perfil?msg=recente#resultados-itf")
    dados = dados_ranking(atleta.genero)
    iniciou = iniciar_tarefa(
        f"atividade:{atleta.itf_player_id}", itf_dados.atualizar_atividade,
        atleta.itf_player_id, atleta.genero, TABELA, dia_do_ranking(dados),
    )
    return ir("/perfil?aguardar=1#resultados-itf" if iniciou else "/perfil?msg=ocupado#resultados-itf")


@app.post("/perfil/senha")
def perfil_senha(
    request: Request,
    senha_atual: str = Form(""), senha_nova: str = Form(""), senha_nova2: str = Form(""),
    _=Depends(conferir_csrf), atleta=Depends(exigir_atleta), conn=Depends(banco),
):
    if senha_nova != senha_nova2:
        return pagina_perfil(request, atleta, 400, erros_senha={"senha_nova2": "As senhas não conferem."})
    try:
        atletas.alterar_senha(conn, atleta.id, senha_atual, senha_nova,
                              sessao_atual=request.cookies.get(COOKIE_SESSAO))
    except atletas.ErroValidacao as exc:
        erros = {("senha_nova" if campo == "senha" else campo): msg for campo, msg in exc.erros.items()}
        return pagina_perfil(request, atleta, 400, erros_senha=erros)
    return ir("/perfil?msg=senha")


@app.get("/perfil/itf")
def perfil_itf(request: Request, atleta=Depends(exigir_atleta)):
    dados = dados_ranking(atleta.genero)
    nome = request.query_params.get("nome", "").strip() or atleta.nome_itf or atleta.nome
    candidato = None
    if dados:
        jogador = indice_ranking(atleta.genero).encontrar(nome)
        if jogador:
            candidato = {
                **resumo_jogador(jogador, MELHORES),
                "player_id": jogador.get("playerId"),
                "pais": jogador.get("playerNationalityCode") or "?",
                "nascimento": jogador.get("birthYear") or "?",
            }
    return pagina(
        request, "perfil_itf.html", atleta,
        secao="perfil", dados=dados, nome=nome, candidato=candidato,
        genero_rotulo=genero_rotulo(atleta.genero),
    )


@app.post("/perfil/itf")
def perfil_itf_vincular(player_id: str = Form(""), _=Depends(conferir_csrf),
                        atleta=Depends(exigir_atleta), conn=Depends(banco)):
    # O id tem que existir no ranking do genero do atleta: nao da para se
    # vincular a um jogador inventado ou do outro ranking.
    jogador = jogador_por_id(atleta.genero, player_id)
    if not jogador:
        raise HTTPException(400, "Jogador não encontrado no ranking.")
    try:
        atletas.vincular_itf(conn, atleta.id, jogador["playerId"], itf.obter_nome_jogador(jogador))
    except atletas.ErroValidacao as exc:
        raise HTTPException(400, str(exc)) from None
    return ir("/inicio?msg=vinculado")


# ═══════════════════════════════════════════════════════════════════════════════
# CONVITES (administrador)
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/convites")
def convites(request: Request, atleta=Depends(exigir_admin), conn=Depends(banco)):
    lista = atletas.listar_convites(conn)
    novo = atletas.normalizar_convite(request.query_params.get("novo", ""))
    novo = next((c for c in lista if c["codigo"] == novo and c["situacao"] == "ativo"), None)
    link = whatsapp = None
    if novo:
        link = f"{str(request.base_url).rstrip('/')}/cadastro?convite={novo['codigo']}"
        texto = f"Seu convite para o BT Ranking: {link}"
        whatsapp = "https://wa.me/?text=" + urllib.parse.quote(texto)
    return pagina(request, "convites.html", atleta, secao="convites",
                  convites=lista, novo=novo, link=link, whatsapp=whatsapp)


@app.post("/convites")
def convites_criar(_=Depends(conferir_csrf), atleta=Depends(exigir_admin), conn=Depends(banco)):
    codigo = atletas.criar_convite(conn, criado_por=atleta.id)
    return ir(f"/convites?novo={codigo}")


@app.post("/convites/{codigo}/cancelar")
def convites_cancelar(codigo: str, _=Depends(conferir_csrf),
                      atleta=Depends(exigir_admin), conn=Depends(banco)):
    atletas.revogar_convite(conn, codigo)
    return ir("/convites?msg=cancelado")


# ═══════════════════════════════════════════════════════════════════════════════
# TIERLIST
# ═══════════════════════════════════════════════════════════════════════════════
def montar_tierlist(genero: str, duplas: list[tuple[int, str, str]], simuladas: list[dict],
                    chave: tierlist_regras.Chave, corte: int | None, meu_nome: str,
                    meu_id: int | None = None) -> list[dict]:
    """Duplas da lista + simuladas, na ordem da ITF. O cache de nomes e por
    chamada: o da tierlist original nao separa masculino de feminino."""
    carregado = _carregar_ranking(genero)
    indice, ordenados, por_id = carregado.indice, carregado.ordenados, carregado.por_id
    achados: dict[str, tuple[int | None, str | None, int | None]] = {}

    def buscar(nome: str) -> tuple[int | None, str | None, int | None]:
        if nome not in achados:
            jogador = indice.encontrar(nome)
            achados[nome] = (
                (itf.parse_inteiro(itf.obter_rank_jogador(jogador)), itf.obter_nome_jogador(jogador),
                 jogador.get("playerId"))
                if jogador else (None, None, None)
            )
        return achados[nome]

    def eh_minha(ids: set, *nomes: str) -> bool:
        return (meu_id is not None and meu_id in ids) or any(
            itf.avaliar_match_nome(meu_nome, p) >= itf.THRESHOLD_MATCH for p in nomes)

    linhas = []
    for numero, p1, p2 in duplas:
        r1, n1, id1 = buscar(p1)
        r2, n2, id2 = buscar(p2)
        ids = {id1, id2} - {None}
        linhas.append({"num": str(numero), "p1": p1, "p2": p2, "r1": r1, "r2": r2,
                       "itf1": n1, "itf2": n2, "ids": ids,
                       "simulada": None, "minha": eh_minha(ids, p1, p2)})

    for i, s in enumerate(simuladas, start=1):
        ranks, ids = [], set()
        for n in (1, 2):
            escolhido = por_id.get(s.get(f"itf_id{n}"))
            if escolhido:
                ranks.append(itf.parse_inteiro(itf.obter_rank_jogador(escolhido)))
                ids.add(escolhido.get("playerId"))
            elif s[f"rank{n}"]:
                ranks.append(s[f"rank{n}"])
            elif s[f"pontos{n}"]:
                ranks.append(estimativa.posicao_com_pontos(s[f"pontos{n}"], ordenados))
            else:
                rank, _, pid = buscar(s[f"jogador{n}"])
                ranks.append(rank)
                ids.add(pid)
        linhas.append({"num": f"S{i}", "p1": s["jogador1"], "p2": s["jogador2"],
                       "r1": ranks[0], "r2": ranks[1], "itf1": None, "itf2": None,
                       "ids": ids - {None}, "simulada": s["id"],
                       "minha": eh_minha(ids, s["jogador1"], s["jogador2"])})

    return tierlist_regras.ordenar(linhas, chave, corte)


def calcular_parceiro(q, genero: str, linhas: list[dict], chave: tierlist_regras.Chave,
                      corte: int | None, atleta: atletas.Atleta) -> dict | None:
    """Ranking minimo do parceiro para o atleta escolhido chegar no alvo."""
    if not q.get("alvo"):
        return None
    carregado = _carregar_ranking(genero)
    jogadores, indice = carregado.dados["jogadores"], carregado.indice
    v = tierlist_regras.vagas(chave, corte)
    alvo_txt = q.get("alvo")
    if alvo_txt in tierlist_regras.FAIXAS and alvo_txt != "fora":
        alvo = v.ultima_posicao(alvo_txt)
        alvo_rotulo = tierlist_regras.FAIXAS[alvo_txt]
    else:
        alvo = inteiro(q.get("posicao"), minimo=1)
        alvo_rotulo = f"{alvo}ª posição" if alvo else None
    if not alvo:
        return {"erro": "Escolha a faixa ou digite a posição."}

    nome = (q.get("atleta") or "").strip() or atleta.nome_itf or atleta.nome
    rank_digitado = inteiro(q.get("rank_atleta"), minimo=1)
    jogador = None if rank_digitado else indice.encontrar(nome)
    meu_rank = rank_digitado or (itf.parse_inteiro(itf.obter_rank_jogador(jogador)) if jogador else None)
    meu_id = jogador.get("playerId") if jogador else None

    # As duplas em que o atleta ja esta saem da comparacao: senao ele disputa
    # a vaga contra ele mesmo.
    def eh_dele(linha):
        return (meu_id and meu_id in linha["ids"]) or any(
            itf.avaliar_match_nome(nome, p) >= itf.THRESHOLD_MATCH for p in (linha["p1"], linha["p2"]))
    outras = [(l["r1"], l["r2"]) for l in linhas if not eh_dele(l)]
    resultado = tierlist_regras.rank_maximo_parceiro(meu_rank, outras, alvo, carregado.rank_limite)

    pais = q.get("pais", (jogador or {}).get("playerNationalityCode") or atleta.nacionalidade or PAIS_PADRAO)
    excluir = set().union(*(l["ids"] for l in linhas)) | ({meu_id} if meu_id else set())
    reais = []
    # Com qualquer ranqueado servindo, a lista viraria o fim do ranking: nao ajuda.
    if resultado["rank_maximo"] and not resultado["qualquer_ranqueado"]:
        reais = [{
            "nome": itf.obter_nome_jogador(j), "rank": j.get("rank"),
            "pontos": itf.parse_inteiro(itf.obter_pontos_jogador(j), 0),
            "pais": j.get("playerNationalityCode"),
        } for j in tierlist_regras.parceiros_reais(jogadores, resultado["rank_maximo"], excluir, pais)]
    return {
        **resultado, "alvo_rotulo": alvo_rotulo, "atleta": itf.obter_nome_jogador(jogador) if jogador else nome,
        "meu_rank": meu_rank, "reais": reais, "pais": pais,
        "paises": carregado.paises,
    }


def pagina_tierlist(request: Request, atleta: atletas.Atleta, conn, status_code: int = 200,
                    erro: str | None = None, formulario: dict | None = None,
                    erros_simulada: dict | None = None, simulada_form: dict | None = None):
    salvo = atletas.carregar_tierlist(conn, atleta.id) or {}
    form = formulario or {
        "genero": salvo.get("genero", atleta.genero),
        "chave": salvo.get("chave", tierlist_regras.CHAVE_PADRAO.id),
        "corte": salvo.get("corte") or "",
        "lista": salvo.get("lista", ""),
    }
    chave = tierlist_regras.chave_por_id(form["chave"])
    corte = inteiro(form["corte"], minimo=1)
    simuladas = atletas.listar_duplas_simuladas(conn, atleta.id)
    v = tierlist_regras.vagas(chave, corte)
    simulada_form = simulada_form or {}
    # Na dupla simulada: o proprio atleta ("Sou eu") e quem ja tinha sido
    # escolhido no ranking quando o formulario volta com erro.
    eu = jogador_por_id(form["genero"], atleta.itf_player_id)
    escolhidos = {n: sugestao(j) for n in (1, 2)
                  if (j := jogador_por_id(form["genero"], simulada_form.get(f"itf{n}")))}
    contexto = {
        "secao": "tierlist", "form": form, "generos": itf.PLAYER_TYPE_LABELS,
        "chaves": tierlist_regras.CHAVES, "chave": chave, "vagas": v,
        "diretas_regulamento": tierlist_regras.DIRETAS_PRINCIPAL[chave.principal],
        "faixas": tierlist_regras.FAIXAS, "faixas_curtas": tierlist_regras.FAIXAS_CURTAS,
        "simuladas": simuladas, "linhas": None,
        "parceiro": None, "erro": erro, "erros_simulada": erros_simulada or {},
        "simulada_form": simulada_form, "q": request.query_params,
        "eu": sugestao(eu) if eu else None, "escolhidos": escolhidos,
    }
    dados = dados_ranking(form["genero"]) if form["genero"] in itf.PLAYER_TYPE_LABELS else None
    if dados is None:
        contexto["erro"] = erro or (f"O ranking {genero_rotulo(form['genero'])} ainda não foi baixado. "
                                    "Peça para o administrador atualizar o ranking na tela inicial.")
        return pagina(request, "tierlist.html", atleta, status_code=status_code, **contexto)

    duplas = []
    if form["lista"].strip() and not erro:
        try:
            duplas = itf.parse_duplas_texto(form["lista"])
        except ValueError as exc:
            contexto["erro"] = f"Não entendi a lista: {exc}."
    if duplas or simuladas:
        linhas = montar_tierlist(form["genero"], duplas, simuladas, chave, corte,
                                 atleta.nome_itf or atleta.nome, atleta.itf_player_id)
        encontradas = sum(1 for linha in linhas if linha["r1"] or linha["r2"])
        contexto.update(
            linhas=linhas, encontradas=encontradas, data_ranking=data_do_ranking(dados),
            suspeito=bool(duplas) and encontradas / len(linhas) < itf.TAXA_MATCH_MINIMA,
            parceiro=calcular_parceiro(request.query_params, form["genero"], linhas, chave, corte, atleta),
        )
    return pagina(request, "tierlist.html", atleta, status_code=status_code, **contexto)


@app.get("/tierlist")
def tierlist(request: Request, atleta=Depends(exigir_atleta), conn=Depends(banco)):
    return pagina_tierlist(request, atleta, conn)


@app.post("/tierlist")
def tierlist_salvar(
    request: Request,
    genero: str = Form(""), chave: str = Form(""), corte: str = Form(""), lista: str = Form(""),
    _=Depends(conferir_csrf), atleta=Depends(exigir_atleta), conn=Depends(banco),
):
    form = {"genero": genero, "chave": chave, "corte": corte, "lista": lista}
    erro = None
    if genero not in itf.PLAYER_TYPE_LABELS:
        erro = "Escolha o ranking masculino ou feminino."
    elif corte.strip() and inteiro(corte, minimo=1) is None:
        erro = "As vagas diretas precisam ser um número inteiro maior que zero."
    elif dados_ranking(genero) is None:
        erro = (f"O ranking {genero_rotulo(genero)} ainda não foi baixado. "
                "Peça para o administrador atualizar o ranking na tela inicial.")
    else:
        try:
            duplas = itf.parse_duplas_texto(lista)
        except ValueError as exc:
            erro = f"Não entendi a lista: {exc}."
        else:
            if len(duplas) > MAX_DUPLAS_TIERLIST:
                erro = f"No máximo {MAX_DUPLAS_TIERLIST} duplas por vez."
    if erro:
        return pagina_tierlist(request, atleta, conn, 400, erro=erro, formulario=form)
    try:
        atletas.salvar_tierlist(conn, atleta.id, genero, tierlist_regras.chave_por_id(chave).id,
                                inteiro(corte, minimo=1), lista)
    except atletas.ErroValidacao as exc:
        return pagina_tierlist(request, atleta, conn, 400, erro=str(exc), formulario=form)
    return ir("/tierlist?msg=lista_salva#resultado")


@app.post("/tierlist/simuladas")
def tierlist_simular(
    request: Request,
    jogador1: str = Form(""), rank1: str = Form(""), pontos1: str = Form(""), itf1: str = Form(""),
    jogador2: str = Form(""), rank2: str = Form(""), pontos2: str = Form(""), itf2: str = Form(""),
    eu1: str = Form(""),
    _=Depends(conferir_csrf), atleta=Depends(exigir_atleta), conn=Depends(banco),
):
    dados = {"jogador1": jogador1, "rank1": rank1, "pontos1": pontos1, "itf1": itf1,
             "jogador2": jogador2, "rank2": rank2, "pontos2": pontos2, "itf2": itf2, "eu1": eu1}
    if eu1:
        dados.update(itf1=str(atleta.itf_player_id or ""), jogador1=jogador1 or atleta.nome_itf or atleta.nome)
    # Escolhido no ranking (itf1/itf2): entra com o nome e o playerId da ITF.
    # Id que nao esta no ranking desta tierlist e ignorado; vale o nome digitado.
    genero = (atletas.carregar_tierlist(conn, atleta.id) or {}).get("genero", atleta.genero)
    for n in (1, 2):
        jogador = jogador_por_id(genero, dados[f"itf{n}"])
        if jogador:
            dados[f"jogador{n}"] = itf.obter_nome_jogador(jogador)
            dados[f"itf_id{n}"] = jogador.get("playerId")
        else:
            dados[f"itf{n}"] = ""
    try:
        atletas.adicionar_dupla_simulada(conn, atleta.id, dados)
    except atletas.ErroValidacao as exc:
        return pagina_tierlist(request, atleta, conn, 400, erros_simulada=exc.erros, simulada_form=dados)
    return ir("/tierlist?msg=simulada#resultado")


@app.post("/tierlist/simuladas/{dupla_id}/excluir")
def tierlist_excluir_simulada(dupla_id: int, _=Depends(conferir_csrf),
                              atleta=Depends(exigir_atleta), conn=Depends(banco)):
    atletas.excluir_dupla_simulada(conn, atleta.id, dupla_id)
    return ir("/tierlist?msg=simulada_excluida#resultado")
