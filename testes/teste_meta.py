"""Calculo da meta de ranking (estimativa.py): pontos para a posicao, descarte
do pior resultado, hipotese sem historico e pontos que vencem."""
import datetime
import json
import random

from _base import DADOS_ITF, PASTA, check, fim
import estimativa as E
import pontuacao
import resultados_itf as R

TAB = pontuacao.carregar_tabela()

print("== pontos para a posicao ==")
rk = [{"playerId": i, "points": p} for i, p in enumerate((500, 400, 400, 300, 100, 50), start=1)]
check(E.pontos_para_posicao(rk, 1)[0] == 500, "1º lugar: pontos do líder")
check(E.pontos_para_posicao(rk, 3)[0] == 400, "empatar já divide a posição")
check(E.pontos_para_posicao(rk, 2, excluir_id=2)[0] == 400, "o próprio atleta sai da conta")
check(E.pontos_para_posicao(rk, 99)[0] == 1, "alvo além do ranking: basta pontuar")

ranking = json.load(open(PASTA / "ranking_itf_M.json", encoding="utf-8"))["jogadores"]
eu = ranking[1500]
outros = [j for j in ranking if j["playerId"] != eu["playerId"]]
ordenados = E.pontos_ordenados(outros)
random.seed(5)
erros = []
for alvo in random.sample(range(1, 3000), 200):
    pontos, _ = E.pontos_para_posicao(ranking, alvo, excluir_id=eu["playerId"])
    if E.posicao_com_pontos(pontos, ordenados) > alvo:
        erros.append((alvo, "não alcança"))
    elif pontos > 1 and E.posicao_com_pontos(pontos - 1, ordenados) <= alvo:
        erros.append((alvo, "pede pontos demais"))
check(not erros, f"200 alvos no ranking real: os pontos pedidos são o mínimo exato {erros[:3]}")

print("== soma e descarte ==")
check(E.soma_dos_melhores([5, 3, 9], 2) == 14, "soma só dos N melhores")
check(E.validos_sem_historico(14, 5, 10) == [14], "menos de 10 torneios: o novo soma inteiro")
check(E.validos_sem_historico(105, 12, 10) == [15] + [10] * 9, "10+ torneios sem histórico: todos na média (conservador)")
check(E.validos_sem_historico(0, 0, 10) == [], "sem pontos, sem resultados")

chave, rodadas = E.rodadas_da_chave(TAB, "BT200")
check(chave["id"] == "32x32" and [c for c, _ in rodadas] == ["R32/24", "R16", "QF", "SF", "F", "W"],
      "rodadas do BT200 32x32 da menor para a maior")
m = E.rodada_minima(rodadas, [], 30, 10)
check(m["codigo"] == "QF" and m["ganho"] == 36, "sem resultados: quartas (36) já passam de 30")
m = E.rodada_minima(rodadas, [20] * 10, 230, 10)
check(m["codigo"] == "SF" and m["ganho"] == 52, "com 10 resultados de 20: a semi (72) descarta um 20 e soma +52")
check(E.rodada_minima(rodadas, [20] * 10, 1000, 10) is None, "meta inalcançável no torneio")

linhas = {l["categoria"]: l for l in E.meta_por_categoria(TAB, [], 150, 10)}
check(linhas["BT10"]["rodada"] is None and linhas["BT10"]["maximo"] == 10, "BT10 não alcança 150 nem sendo campeão")
check(linhas["BT200"]["rodada"]["codigo"] == "W", "BT200: só sendo campeão (200)")
check(linhas["BT400"]["rodada"]["codigo"] == "F", "BT400: final (240)")
check(linhas["WCH"]["rodada"]["codigo"] == "QF", "Mundial: quartas (216)")
check("TOUR_FINALS" not in linhas, "Tour Finals fora da meta (não pontua por rodada)")

print("== pontos que vencem ==")
lucas = json.load(open(DADOS_ITF / "atividade_800767267.json", encoding="utf-8"))["items"]
res = R.resultados_do_atleta(lucas, TAB)
hoje = E.soma_dos_melhores(R.pontos_validos(res, datetime.date(2026, 10, 19)), 10)
depois = E.soma_dos_melhores(R.pontos_validos(res, datetime.date(2027, 2, 15)), 10)
check(hoje == 14 and depois == 18, f"14 pts hoje; em fev/2027 perde os 5 de fevereiro e ganha os 9 do BT200 ({hoje} -> {depois})")
fim()
