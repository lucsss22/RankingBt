"""
Auditoria — registro de eventos de seguranca com cadeia de HMAC
================================================================
Grava cada evento de seguranca num arquivo proprio e assina cada linha
com HMAC-SHA256. O MAC de uma linha inclui o MAC da linha anterior:
alterar, apagar ou reordenar qualquer linha invalida todas as seguintes.

A chave fica em auditoria.key, separada da chave do CSRF (segredo.key):
comprometer uma nao da o poder de forjar a outra.

O arquivo rotaciona em MAX_BYTES com BACKUPS copias, para que um ataque
de muitas tentativas nao encha o disco.

Rodado direto, verifica a cadeia:  python auditoria.py [arquivo]
"""

import datetime
import hashlib
import hmac
import logging
import pathlib
import secrets
import threading
from logging.handlers import RotatingFileHandler

import atletas

ARQUIVO_LOG = atletas.PASTA_DADOS / "seguranca.log"
ARQUIVO_CHAVE = atletas.PASTA_DADOS / "auditoria.key"
MAX_BYTES = 1024 * 1024
BACKUPS = 5
SEMENTE = "0" * 64      # elo zero: a primeira linha precisa de um anterior
LIMITE_CAMPO = 200


def carregar_chave() -> bytes:
    """Chave que assina o log. Criada na primeira execucao."""
    try:
        return bytes.fromhex(ARQUIVO_CHAVE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        chave = secrets.token_bytes(32)
        ARQUIVO_CHAVE.parent.mkdir(parents=True, exist_ok=True)
        ARQUIVO_CHAVE.write_text(chave.hex(), encoding="utf-8")
        return chave


CHAVE = carregar_chave()


def _abrir_log() -> logging.Logger:
    log = logging.getLogger("auditoria")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    log.propagate = False
    ARQUIVO_LOG.parent.mkdir(parents=True, exist_ok=True)
    arquivo = RotatingFileHandler(ARQUIVO_LOG, maxBytes=MAX_BYTES,
                                  backupCount=BACKUPS, encoding="utf-8")
    arquivo.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(arquivo)
    return log


LOG = _abrir_log()


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


def _estado_inicial() -> tuple[int, str]:
    """Retoma a cadeia de onde o arquivo parou."""
    try:
        linhas = ARQUIVO_LOG.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, UnicodeDecodeError):
        return 0, SEMENTE
    for linha in reversed(linhas):
        partes = _partir(linha)
        if partes:
            try:
                return int(partes[0].split(" | ")[0][4:]), partes[1]
            except ValueError:
                continue
    return 0, SEMENTE


_TRAVA = threading.Lock()
_seq, _ultimo_mac = _estado_inicial()


def registrar(evento: str, ip: str = "", usuario: str = "", detalhe: str = "") -> None:
    """Grava um evento de seguranca, assinado e encadeado."""
    global _seq, _ultimo_mac
    agora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _TRAVA:
        _seq += 1
        corpo = " | ".join([
            f"seq={_seq}",
            agora,
            _limpar(evento),
            f"ip={_limpar(ip)}",
            f"usuario={_limpar(usuario)}",
            f"detalhe={_limpar(detalhe)}",
        ])
        _ultimo_mac = assinar(_ultimo_mac, corpo)
        LOG.info("%s | mac=%s", corpo, _ultimo_mac)


def verificar(caminho: str | pathlib.Path | None = None) -> tuple[bool, int, str]:
    """Reconfere a cadeia inteira. Devolve (ok, linha, mensagem)."""
    caminho = pathlib.Path(caminho or ARQUIVO_LOG)
    try:
        linhas = caminho.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return False, 0, f"arquivo nao encontrado: {caminho}"
    anterior = SEMENTE
    for numero, linha in enumerate(linhas, start=1):
        partes = _partir(linha)
        if partes is None:
            return False, numero, f"linha {numero}: formato invalido ou sem MAC"
        corpo, mac = partes
        if not corpo.startswith(f"seq={numero} "):
            return False, numero, f"linha {numero}: sequencia fora de ordem (linha apagada?)"
        if not hmac.compare_digest(assinar(anterior, corpo), mac):
            return False, numero, f"linha {numero}: MAC invalido - conteudo alterado"
        anterior = mac
    return True, len(linhas), f"cadeia intacta: {len(linhas)} linhas verificadas"


if __name__ == "__main__":
    import sys
    ok, linha, mensagem = verificar(sys.argv[1] if len(sys.argv) > 1 else None)
    print(("OK    " if ok else "FALHA ") + mensagem)
    sys.exit(0 if ok else 1)