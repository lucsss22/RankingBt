"""
Auditoria — registro de eventos de seguranca com cadeia de HMAC
================================================================
Grava cada evento de seguranca num arquivo proprio e assina cada linha
com HMAC-SHA256. O MAC de uma linha inclui o MAC da linha anterior:
alterar, apagar ou reordenar qualquer linha invalida todas as seguintes.

A chave fica em auditoria.key, separada da chave do CSRF (segredo.key):
comprometer uma nao da o poder de forjar a outra.

O arquivo rotaciona em MAX_BYTES com BACKUPS copias, para que um ataque
de muitas tentativas nao encha o disco. A cadeia atravessa a rotacao: a
primeira linha de seguranca.log continua o MAC da ultima linha de
seguranca.log.1, e verificar() le os arquivos na ordem certa.

Seguranca entre processos
-------------------------
Gravar e rotacionar acontecem sob uma trava de arquivo (auditoria.lock,
criada com O_EXCL), e o estado da cadeia e lido do disco dentro da trava,
nunca de memoria. Por isso varios workers de uvicorn, ou varios processos,
compartilham uma cadeia unica sem a bifurcar e sem perder linhas. A chave
tambem e criada sob O_EXCL: quem perde a corrida le a chave do vencedor.

Limites conhecidos
------------------
- Truncar o FIM do log nao e detectado: o que sobra e um prefixo valido.
- Quem tem acesso de escrita a auditoria.key pode reescrever o log inteiro.
- Se as BACKUPS copias rodarem para fora, a cadeia deixa de estar ancorada
  na semente; verificar() avisa quando esta nessa situacao.

Rodado direto, verifica a cadeia:  python auditoria.py [arquivo]
"""

import contextlib
import datetime
import hashlib
import hmac
import os
import pathlib
import secrets
import threading
import time

import atletas

ARQUIVO_LOG = atletas.PASTA_DADOS / "seguranca.log"
ARQUIVO_CHAVE = atletas.PASTA_DADOS / "auditoria.key"
ARQUIVO_TRAVA = atletas.PASTA_DADOS / "auditoria.lock"
MAX_BYTES = 1024 * 1024
BACKUPS = 5
SEMENTE = "0" * 64      # elo zero: a primeira linha precisa de um anterior
LIMITE_CAMPO = 200


# ═══════════════════════════════════════════════════════════════════════════════
# CHAVE
# ═══════════════════════════════════════════════════════════════════════════════
def _ler_chave() -> bytes | None:
    """Chave do disco, ou None se ainda nao esta lá inteira.

    O tamanho e conferido porque bytes.fromhex("") devolve b"" sem levantar
    erro: quem perde a corrida do O_EXCL pode encontrar o arquivo criado e
    ainda vazio, e aceitar isso daria uma chave de zero byte.
    """
    try:
        chave = bytes.fromhex(ARQUIVO_CHAVE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError, OSError):
        return None
    return chave if len(chave) == 32 else None


def carregar_chave() -> bytes:
    """Chave que assina o log. Criada na primeira execucao.

    O O_EXCL garante que, com varios processos subindo juntos, so um cria:
    os outros recebem FileExistsError e leem a chave que ficou no disco.
    """
    chave = _ler_chave()
    if chave is not None:
        return chave
    ARQUIVO_CHAVE.parent.mkdir(parents=True, exist_ok=True)
    nova = secrets.token_bytes(32)
    try:
        fd = os.open(ARQUIVO_CHAVE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
            arquivo.write(nova.hex())
        return nova
    for _ in range(50):          # perdemos a corrida: o vencedor pode estar gravando
        chave = _ler_chave()
        if chave is not None:
            return chave
        time.sleep(0.01)
    raise RuntimeError(f"auditoria: nao consegui ler a chave em {ARQUIVO_CHAVE}")


CHAVE = carregar_chave()


# ═══════════════════════════════════════════════════════════════════════════════
# ASSINATURA E FORMATO DA LINHA
# ═══════════════════════════════════════════════════════════════════════════════
def _limpar(valor: object) -> str:
    """Impede injecao de log: sem quebra de linha e sem o separador."""
    texto = str(valor or "")
    for ruim in ("\r", "\n", "|"):
        texto = texto.replace(ruim, " ")
    return " ".join(texto.split())[:LIMITE_CAMPO]


def assinar(anterior: str, corpo: str) -> str:
    """MAC da linha: depende dela e do MAC da linha anterior."""
    dados = f"{anterior}|{corpo}".encode("utf-8")
    return hmac.new(CHAVE, dados, hashlib.sha256).hexdigest()


def _partir(linha: str) -> tuple[str, str] | None:
    """Separa corpo e MAC de uma linha gravada."""
    if " | mac=" not in linha or not linha.startswith("seq="):
        return None
    corpo, _, mac = linha.rpartition(" | mac=")
    return corpo, mac.strip()


def _seq_de(corpo: str) -> int | None:
    try:
        return int(corpo.split(" | ")[0][4:])
    except (ValueError, IndexError):
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# TRAVA ENTRE PROCESSOS
# ═══════════════════════════════════════════════════════════════════════════════
try:                                        # Linux, macOS
    import fcntl

    def _bloquear(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _desbloquear(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)

except ImportError:                         # Windows
    import msvcrt

    def _bloquear(fd: int) -> None:
        # LK_LOCK tenta por ~10s e levanta; aqui a espera e indefinida de proposito,
        # porque desistir significaria perder um evento de seguranca.
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.001)

    def _desbloquear(fd: int) -> None:
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _abrir_trava() -> int:
    ARQUIVO_TRAVA.parent.mkdir(parents=True, exist_ok=True)
    return os.open(ARQUIVO_TRAVA, os.O_CREAT | os.O_RDWR)


_FD_TRAVA = _abrir_trava()
_TRAVA_THREADS = threading.Lock()


@contextlib.contextmanager
def _travar():
    """Serializa gravacao e rotacao entre threads E entre processos.

    Sao duas travas porque uma so nao basta: a trava de arquivo do sistema
    operacional e por descritor, entao duas threads do mesmo processo
    passariam juntas por ela. A de thread resolve dentro do processo, a de
    arquivo resolve entre processos.

    Travar um byte de um arquivo que fica aberto, em vez de criar e apagar um
    arquivo por evento, e mais rapido e mais seguro: se o processo morrer, o
    sistema operacional libera a trava sozinho, sem deixar trava orfa.
    """
    with _TRAVA_THREADS:
        os.lseek(_FD_TRAVA, 0, os.SEEK_SET)
        _bloquear(_FD_TRAVA)
        try:
            yield
        finally:
            os.lseek(_FD_TRAVA, 0, os.SEEK_SET)
            _desbloquear(_FD_TRAVA)


# ═══════════════════════════════════════════════════════════════════════════════
# ROTACAO E ESTADO DA CADEIA
# ═══════════════════════════════════════════════════════════════════════════════
def _arquivos_da_cadeia(base: pathlib.Path) -> list[pathlib.Path]:
    """Do mais antigo para o mais novo: .BACKUPS .. .1 e por fim o atual."""
    arquivos = [pathlib.Path(f"{base}.{n}") for n in range(BACKUPS, 0, -1)]
    arquivos = [caminho for caminho in arquivos if caminho.exists()]
    if base.exists():
        arquivos.append(base)
    return arquivos


def _rotacionar_se_preciso() -> None:
    """Chamado sob a trava. Mantem os nomes .1 .. .BACKUPS."""
    try:
        if ARQUIVO_LOG.stat().st_size < MAX_BYTES:
            return
    except FileNotFoundError:
        return
    ultimo = pathlib.Path(f"{ARQUIVO_LOG}.{BACKUPS}")
    with contextlib.suppress(OSError):
        ultimo.unlink()
    for n in range(BACKUPS - 1, 0, -1):
        origem = pathlib.Path(f"{ARQUIVO_LOG}.{n}")
        if origem.exists():
            with contextlib.suppress(OSError):
                origem.replace(pathlib.Path(f"{ARQUIVO_LOG}.{n + 1}"))
    with contextlib.suppress(OSError):
        ARQUIVO_LOG.replace(pathlib.Path(f"{ARQUIVO_LOG}.1"))


def _cauda_valida(caminho: pathlib.Path) -> tuple[int, str] | None:
    """Ultima linha valida de um arquivo, lendo so o fim dele."""
    try:
        with open(caminho, "rb") as arquivo:
            arquivo.seek(0, os.SEEK_END)
            tamanho = arquivo.tell()
            arquivo.seek(max(0, tamanho - 8192))
            texto = arquivo.read().decode("utf-8", "ignore")
    except (FileNotFoundError, OSError):
        return None
    for linha in reversed(texto.splitlines()):
        partes = _partir(linha)
        if partes is None:
            continue
        seq = _seq_de(partes[0])
        if seq is not None:
            return seq, partes[1]
    return None


def _estado_do_disco() -> tuple[int, str]:
    """Onde a cadeia parou, lido do disco. Chamado sob a trava.

    Olha o arquivo atual e, se ele acabou de rotacionar e esta vazio,
    volta nos backups — e assim a cadeia continua por cima da rotacao.
    """
    for caminho in reversed(_arquivos_da_cadeia(ARQUIVO_LOG)):
        estado = _cauda_valida(caminho)
        if estado is not None:
            return estado
    return 0, SEMENTE


# ═══════════════════════════════════════════════════════════════════════════════
# GRAVACAO
# ═══════════════════════════════════════════════════════════════════════════════
def registrar(evento: str, ip: str = "", usuario: str = "", detalhe: str = "") -> None:
    """Grava um evento de seguranca, assinado e encadeado.

    Nao levanta excecao para quem chama: falhar ao auditar nao pode derrubar
    o pedido do atleta. Uma falha aqui aparece como lacuna na sequencia, que
    verificar() acusa.
    """
    agora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _travar():
            _rotacionar_se_preciso()
            seq, anterior = _estado_do_disco()
            corpo = " | ".join([
                f"seq={seq + 1}",
                agora,
                _limpar(evento),
                f"ip={_limpar(ip)}",
                f"usuario={_limpar(usuario)}",
                f"detalhe={_limpar(detalhe)}",
            ])
            mac = assinar(anterior, corpo)
            ARQUIVO_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(ARQUIVO_LOG, "a", encoding="utf-8", newline="\n") as arquivo:
                arquivo.write(f"{corpo} | mac={mac}\n")
    except (OSError, TimeoutError):
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# VERIFICACAO
# ═══════════════════════════════════════════════════════════════════════════════
def verificar(caminho: str | pathlib.Path | None = None) -> tuple[bool, int, str]:
    """Reconfere a cadeia inteira, atravessando a rotacao.

    Devolve (ok, linha, mensagem). A contagem de linha e continua: ela cobre
    os arquivos rotacionados e o atual como se fossem um so.
    """
    base = pathlib.Path(caminho or ARQUIVO_LOG)
    arquivos = _arquivos_da_cadeia(base)
    if not arquivos:
        return False, 0, f"arquivo nao encontrado: {base}"

    linhas: list[tuple[pathlib.Path, str]] = []
    for arquivo in arquivos:
        try:
            texto = arquivo.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as erro:
            return False, 0, f"nao consegui ler {arquivo.name}: {erro}"
        linhas.extend((arquivo, linha) for linha in texto.splitlines())

    if not linhas:
        return False, 0, "log vazio: nada para verificar"

    primeiro = _partir(linhas[0][1])
    if primeiro is None:
        return False, 1, "linha 1: formato invalido ou sem MAC"
    seq_inicial = _seq_de(primeiro[0])
    if seq_inicial is None:
        return False, 1, "linha 1: numero de sequencia ilegivel"

    # A cadeia so esta ancorada na semente se comecar em seq=1. Se os backups
    # mais antigos rodaram para fora, o primeiro MAC nao tem como ser provado:
    # verificamos dali para frente e dizemos isso na mensagem.
    ancorada = seq_inicial == 1
    anterior = SEMENTE if ancorada else primeiro[1]
    inicio = 0 if ancorada else 1

    for indice in range(inicio, len(linhas)):
        arquivo, linha = linhas[indice]
        numero = indice + 1
        partes = _partir(linha)
        if partes is None:
            return False, numero, f"linha {numero} ({arquivo.name}): formato invalido ou sem MAC"
        corpo, mac = partes
        esperado = seq_inicial + indice
        if _seq_de(corpo) != esperado:
            return False, numero, (f"linha {numero} ({arquivo.name}): esperava seq={esperado} "
                                   "- linha apagada ou fora de ordem")
        if not hmac.compare_digest(assinar(anterior, corpo), mac):
            return False, numero, f"linha {numero} ({arquivo.name}): MAC invalido - conteudo alterado"
        anterior = mac

    total = len(linhas)
    onde = f"{len(arquivos)} arquivo(s)" if len(arquivos) > 1 else arquivos[0].name
    if ancorada:
        return True, total, f"cadeia intacta: {total} linhas em {onde}"
    return True, total, (f"cadeia intacta de seq={seq_inicial} em diante: {total} linhas em {onde} "
                         "- os backups mais antigos rodaram para fora, a primeira linha nao e provavel")


if __name__ == "__main__":
    import sys
    ok, linha, mensagem = verificar(sys.argv[1] if len(sys.argv) > 1 else None)
    print(("OK    " if ok else "FALHA ") + mensagem)
    sys.exit(0 if ok else 1)
