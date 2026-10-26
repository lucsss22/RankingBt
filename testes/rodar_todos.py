"""Roda todos os testes, cada um num processo com a sua pasta de dados
temporaria (nada encosta no banco de verdade).

Uso:
    python testes/rodar_todos.py
"""
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

PASTA_TESTES = pathlib.Path(__file__).resolve().parent
ORDEM = [
    "teste_modulos.py",         # conta, login, resultados, pontuacao, estimativa (os 44 originais)
    "teste_tierlist.py",        # ordem da ITF, vagas, ranking do parceiro
    "teste_resultados_itf.py",  # dados da ITF -> pontos
    "teste_meta.py",            # meta de ranking
    "teste_web.py",             # app web de ponta a ponta
    "teste_ranking_semana.py",  # atualizacao automatica do ranking toda segunda
    "teste_indice.py",          # indice de nomes = busca original (o mais lento)
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    total_ok = total_falhas = 0
    linhas = []
    for nome in ORDEM:
        ambiente = {**os.environ, "BT_DADOS": tempfile.mkdtemp(prefix="bt_testes_"),
                    "PYTHONIOENCODING": "utf-8"}
        inicio = time.perf_counter()
        saida = subprocess.run([sys.executable, str(PASTA_TESTES / nome)], cwd=PASTA_TESTES.parent,
                               env=ambiente, capture_output=True, text=True, encoding="utf-8")
        duracao = time.perf_counter() - inicio
        oks = len(re.findall(r"^  ok ", saida.stdout, re.MULTILINE))
        falhas = re.findall(r"^  FALHA (.*)$", saida.stdout, re.MULTILINE)
        quebrou = saida.returncode != 0 and not falhas
        total_ok += oks
        total_falhas += len(falhas) + (1 if quebrou else 0)
        estado = "QUEBROU" if quebrou else ("ok" if not falhas else f"{len(falhas)} falha(s)")
        linhas.append(f"{nome:<26} {oks:>4} ok   {estado:<12} {duracao:5.1f}s")
        for falha in falhas:
            linhas.append(f"    FALHA {falha}")
        if quebrou:
            linhas.append("    " + (saida.stderr.strip().splitlines() or ["?"])[-1])
    print("\n".join(linhas))
    print(f"\nTotal: {total_ok} verificações ok, {total_falhas} falha(s)")
    return 1 if total_falhas else 0


if __name__ == "__main__":
    sys.exit(main())
