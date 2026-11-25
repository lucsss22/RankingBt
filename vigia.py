"""
Vigia — deteccao e bloqueio automatico a partir do log de auditoria
====================================================================
Le o log de seguranca gravado pela aplicacao, conta eventos de falha por
endereco IP numa janela de tempo e, ao passar do limite, insere uma regra
DROP no iptables. O bloqueio expira sozinho depois de BLOQUEIO_S.

Roda no conteiner de defesa, que compartilha o namespace de rede do proxy:
a regra criada aqui descarta o pacote antes de a aplicacao ser acordada, o
que protege a CPU gasta no PBKDF2.

O vigia NAO recebe a chave que assina o log — para contar falhas ele nao
precisa dela. Conferir a cadeia e tarefa do administrador, com o
auditoria.py, fora deste conteiner.

Limitacao conhecida: bloqueia apenas IPv4 (o iptables nao trata IPv6).

Rodar:  python vigia.py
"""

import collections
import datetime
import ipaddress
import pathlib
import re
import subprocess
import time
import typing

ARQUIVO_LOG = pathlib.Path("/dados/seguranca.log")
EVENTOS = ("LOGIN_FALHOU", "LIMITE_IP", "CSRF_INVALIDO", "ACESSO_NEGADO")
LIMITE = 5                 # falhas que disparam o bloqueio
JANELA_S = 600             # janela de contagem, em segundos
BLOQUEIO_S = 900           # duracao do bloqueio, em segundos
INTERVALO_S = 2            # pausa entre leituras do arquivo
NUNCA_BLOQUEAR = {"127.0.0.1", "::1"}
LINHA = re.compile(r"\| (?P<evento>[A-Z_]+) \| ip=(?P<ip>[^ |]*)")


def aviso(texto: str) -> None:
    quando = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
    print(f"[{quando}] {texto}", flush=True)


def ipv4_valido(ip: str) -> bool:
    """So endereco IPv4 de verdade chega ao iptables."""
    try:
        return isinstance(ipaddress.ip_address(ip), ipaddress.IPv4Address)
    except ValueError:
        return False


def iptables(*args: str) -> bool:
    """Executa uma regra. Devolve True se o iptables aceitou."""
    try:
        r = subprocess.run(("iptables", *args), capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        aviso(f"ERRO ao chamar iptables: {exc}")
        return False
    if r.returncode != 0:
        aviso(f"ERRO iptables {' '.join(args)}: {r.stderr.strip()}")
    return r.returncode == 0


def bloquear(ip: str) -> bool:
    return iptables("-I", "INPUT", "-s", ip, "-j", "DROP")


def desbloquear(ip: str) -> bool:
    return iptables("-D", "INPUT", "-s", ip, "-j", "DROP")


def abrir_no_fim(caminho: pathlib.Path) -> typing.TextIO:
    """Espera o log existir e posiciona no fim: so eventos novos contam."""
    while not caminho.exists():
        aviso(f"esperando {caminho} aparecer...")
        time.sleep(INTERVALO_S)
    arquivo = caminho.open("r", encoding="utf-8", errors="replace")
    arquivo.seek(0, 2)
    return arquivo


def main() -> None:
    falhas: dict[str, collections.deque[float]] = {}
    bloqueados: dict[str, float] = {}
    arquivo = abrir_no_fim(ARQUIVO_LOG)
    aviso(f"vigia no ar: {LIMITE} falhas em {JANELA_S}s "
          f"-> bloqueio de {BLOQUEIO_S}s")

    while True:
        linha = arquivo.readline()
        if linha:
            achado = LINHA.search(linha)
            if not achado or achado.group("evento") not in EVENTOS:
                continue
            ip = achado.group("ip")
            if ip in NUNCA_BLOQUEAR or ip in bloqueados or not ipv4_valido(ip):
                continue
            momento = time.monotonic()
            recentes = falhas.setdefault(ip, collections.deque())
            recentes.append(momento)
            while recentes and momento - recentes[0] > JANELA_S:
                recentes.popleft()
            aviso(f"{achado.group('evento')} de {ip} "
                  f"({len(recentes)}/{LIMITE})")
            if len(recentes) >= LIMITE and bloquear(ip):
                bloqueados[ip] = momento + BLOQUEIO_S
                recentes.clear()
                aviso(f"BLOQUEADO {ip} por {BLOQUEIO_S}s")
            continue

        # Sem linha nova: trata rotacao, expira bloqueios, limpa contadores.
        if ARQUIVO_LOG.exists() and ARQUIVO_LOG.stat().st_size < arquivo.tell():
            aviso("log rotacionado; reabrindo do inicio")
            arquivo.close()
            arquivo = ARQUIVO_LOG.open("r", encoding="utf-8", errors="replace")
        agora = time.monotonic()
        for ip, expira in list(bloqueados.items()):
            if agora >= expira and desbloquear(ip):
                del bloqueados[ip]
                aviso(f"liberado {ip}")
        for ip, recentes in list(falhas.items()):
            while recentes and agora - recentes[0] > JANELA_S:
                recentes.popleft()
            if not recentes:
                del falhas[ip]
        time.sleep(INTERVALO_S)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        aviso("encerrando")