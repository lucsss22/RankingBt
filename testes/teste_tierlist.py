"""Regras da tierlist: ordem e desempate da ITF, vagas por chave, faixas e
ranking minimo do parceiro (comparado com forca bruta)."""
import json
import random

from _base import PASTA, check, fim
import tierlist_regras as T

print("== vagas por chave ==")
def faixas(chave_id, diretas=None):
    v = T.vagas(T.chave_por_id(chave_id), diretas)
    return (v.cabecas, v.diretas, v.cabecas_qualy, v.qualy)

check(faixas("32x32") == (8, 20, 36, 46), f"32x32: 8 cabeças, 20 diretas, 16 cabeças do qualy, 26 no qualy {faixas('32x32')}")
check(faixas("32x16") == (8, 20, 28, 34), f"32x16: 8 cabeças do qualy, 14 no qualy {faixas('32x16')}")
check(faixas("16x16") == (4, 12, 20, 26), f"16x16: 4 cabeças, 12 diretas {faixas('16x16')}")
check(faixas("24x24") == (8, 18, 30, 38), f"24x24: 18 diretas, 12 cabeças do qualy {faixas('24x24')}")
check(faixas("8x0") == (2, 7, 7, 7), f"8x0: sem qualifying {faixas('8x0')}")
check(faixas("32x64") == (8, 20, 36, 76), f"32x64: cabeças do qualy limitadas a 16 {faixas('32x64')}")
check(faixas("32x32", 22) == (8, 22, 38, 48), f"vagas diretas editadas (convite não usado) {faixas('32x32', 22)}")
check(T.chave_por_id("lixo").id == "32x32", "chave desconhecida cai na 32x32")

print("== ordem da ITF ==")
duplas = [
    {"id": "a", "r1": 10, "r2": 50},     # A: soma 60, melhor 10
    {"id": "b", "r1": 30, "r2": 30},     # A: soma 60, melhor 30
    {"id": "c", "r1": 5, "r2": None},    # B: um ranqueado, #5
    {"id": "d", "r1": None, "r2": None}, # C: sem ranking
    {"id": "e", "r1": 100, "r2": 200},   # A: soma 300
    {"id": "f", "r1": 20, "r2": 40},     # A: soma 60, melhor 20
    {"id": "g", "r1": 40, "r2": 20},     # A: soma 60, melhor 20 (empate total com f)
]
ordem = T.ordenar(duplas, T.chave_por_id("32x32"))
check([d["id"] for d in ordem] == ["a", "f", "g", "b", "e", "c", "d"],
      f"A por soma, desempate pelo melhor atleta, depois B e C: {[d['id'] for d in ordem]}")
por_id = {d["id"]: d for d in ordem}
check(por_id["f"]["empate"] and por_id["g"]["empate"], "empate total marcado (sorteio)")
check(not por_id["a"]["empate"] and not por_id["b"]["empate"], "mesma soma com desempate decidido não é empate")
check(por_id["c"]["posicao"] == 6, "dupla com um ranqueado (#5) entra depois de todas com dois ranqueados")
check(por_id["d"]["faixa"] == "principal", "dupla sem ranking não vira cabeça mesmo na 7ª posição")
check(por_id["a"]["soma"] == 60 and por_id["c"]["soma"] is None, "soma só para dupla com dois ranqueados")
check([d["id"] for d in duplas] == ["a", "b", "c", "d", "e", "f", "g"] and "posicao" not in duplas[0],
      "não altera a lista original")

grandes = [{"r1": i, "r2": i + 1000} for i in range(1, 51)]
contagem = {}
for d in T.ordenar(grandes, T.chave_por_id("32x32")):
    contagem[d["faixa"]] = contagem.get(d["faixa"], 0) + 1
check(contagem == {"cabeca": 8, "principal": 12, "cabeca_qualy": 16, "qualy": 10, "fora": 4},
      f"50 duplas numa 32x32: {contagem}")

print("== ranking minimo do parceiro ==")
r = T.rank_maximo_parceiro(30, [(10, 50), (50, 50)], 1, 600)
check(r["rank_maximo"] == 29, f"para passar a dupla 10+50: parceiro até #29 ({r['rank_maximo']})")
r = T.rank_maximo_parceiro(5, [(10, 50)], 1, 600)
check(r["rank_maximo"] == 55, f"soma 60 com melhor atleta #5 ganha o desempate: até #55 ({r['rank_maximo']})")
r = T.rank_maximo_parceiro(300, [(1, 2), (3, 4)], 1, 600)
check(r["rank_maximo"] is None and r["melhor_posicao"] == 3, "alvo impossível devolve a melhor posição possível")
r = T.rank_maximo_parceiro(10, [(1, 2)], 5, 600)
check(r["qualquer_ranqueado"], "lista menor que o alvo: qualquer parceiro ranqueado serve")
r = T.rank_maximo_parceiro(None, [(10, 20), (5, None)], 2, 600)
check(r["rank_maximo"] == 4, f"atleta sem ranking: parceiro precisa passar o #5 da outra dupla B ({r['rank_maximo']})")
r = T.rank_maximo_parceiro(None, [(10, 20)], 1, 600)
check(r["rank_maximo"] is None, "sem ranking não passa dupla com dois ranqueados")

def forca_bruta(meu, outras, alvo, limite):
    chaves = [T.chave_de_ordem(a, b) for a, b in outras]
    validos = [p for p in range(1, limite + 1)
               if T.posicao_entre(T.chave_de_ordem(meu, p), chaves) <= alvo]
    return max(validos) if validos else None

random.seed(11)
divergencias = 0
for _ in range(300):
    outras = [(random.choice([None] + list(range(1, 400))), random.choice([None] + list(range(1, 400))))
              for _ in range(random.randint(0, 40))]
    meu = random.choice([None] + list(range(1, 400)))
    alvo = random.randint(1, 45)
    if T.rank_maximo_parceiro(meu, outras, alvo, 450)["rank_maximo"] != forca_bruta(meu, outras, alvo, 450):
        divergencias += 1
check(divergencias == 0, f"busca binária = força bruta em 300 cenários aleatórios ({divergencias} diferentes)")

print("== atletas reais ==")
ranking = json.load(open(PASTA / "ranking_itf_M.json", encoding="utf-8"))["jogadores"]
reais = T.parceiros_reais(ranking, 300, excluir={ranking[0]["playerId"]}, pais="BRA", limite=20)
check(len(reais) == 20 and all(j["rank"] <= 300 and j["playerNationalityCode"] == "BRA" for j in reais),
      "20 atletas do Brasil até o #300")
check([j["rank"] for j in reais] == sorted((j["rank"] for j in reais), reverse=True) and reais[0]["rank"] <= 300,
      f"os mais próximos do limite primeiro (#{reais[0]['rank']} … #{reais[-1]['rank']})")
excluido = reais[0]["playerId"]
check(excluido not in {j["playerId"] for j in T.parceiros_reais(ranking, 300, {excluido}, "BRA")},
      "quem já está na lista fica de fora")
todos = T.parceiros_reais(ranking, 50, set(), None, limite=100)
check(len({j["playerNationalityCode"] for j in todos}) > 1, "sem país: atletas de vários países")
fim()
