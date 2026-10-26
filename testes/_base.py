"""Base dos testes: importe ANTES de qualquer modulo do app.

Aponta BT_DADOS para uma pasta temporaria — banco, segredo e caches da ITF
dos testes nunca encostam nos de verdade. O ranking salvo (ranking_itf_M.json)
e lido da pasta do projeto, so leitura.
"""
import os
import pathlib
import sys
import tempfile

PASTA = pathlib.Path(__file__).resolve().parent.parent
DADOS_ITF = pathlib.Path(__file__).resolve().parent / "dados_itf"

if not os.environ.get("BT_DADOS"):
    os.environ["BT_DADOS"] = tempfile.mkdtemp(prefix="bt_testes_")
PASTA_DADOS = pathlib.Path(os.environ["BT_DADOS"])
assert PASTA_DADOS.resolve() != PASTA, "BT_DADOS nao pode ser a pasta do projeto"

sys.path.insert(0, str(PASTA))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

falhas: list[str] = []


def check(condicao, mensagem: str) -> bool:
    print(("  ok   " if condicao else "  FALHA ") + mensagem)
    if not condicao:
        falhas.append(mensagem)
    return bool(condicao)


def fim() -> None:
    print(f"\nFALHAS: {len(falhas)}")
    sys.exit(1 if falhas else 0)
