"""O indice de nomes da web acha exatamente o mesmo atleta que o
encontrar_jogador da tierlist original."""
import json, random, time
from _base import PASTA, check, fim
import itf_beach_tennis_tierlist as itf
import estimativa
rk = json.load(open(PASTA / "ranking_itf_M.json", encoding="utf-8"))["jogadores"]
random.seed(7)
nomes = []
for j in random.sample(rk, 40):
    fam, giv = j["playerFamilyName"], j["playerGivenName"]
    nomes += [f"{fam.upper()} {giv}", f"{giv} {fam}", f"{fam.split()[0]} {giv}", giv, f"{fam} Xyz"]
nomes += [f"{a} {b}" for a, b, _ in []] + [p for _, p1, p2 in itf.DUPLAS for p in (p1, p2)]
nomes += ["SILVA Joao", "SANTOS Pedro", "DE OLIVEIRA Maria", "GIANOTTI Nicolas", "COBUCCI Lucas", "", "A"]

t0 = time.perf_counter()
original = [itf.encontrar_jogador(n, rk) for n in nomes]
t_orig = time.perf_counter() - t0
t0 = time.perf_counter()
indice = estimativa.IndiceDeNomes(rk)
t_ind_monta = time.perf_counter() - t0
t0 = time.perf_counter()
rapido = [indice.encontrar(n) for n in nomes]
t_ind = time.perf_counter() - t0

diferentes = [(n, a and a["playerId"], b and b["playerId"]) for n, a, b in zip(nomes, original, rapido) if a is not b]
check(not diferentes, f"{len(nomes)} nomes: indice igual ao original ({len(diferentes)} diferencas) {diferentes[:3]}")
check(t_ind < t_orig, f"indice mais rapido ({t_ind:.2f}s contra {t_orig:.1f}s)")

print("== autocompletar (sugerir) ==")
g = next(j for j in rk if j["playerFamilyName"].upper() == "GIANOTTI")
check([j["playerId"] for j in indice.sugerir("gian nic")][:1] == [g["playerId"]], "acha pelo começo de cada pedaço do nome")
check([j["playerId"] for j in indice.sugerir("GIÁNOTTI")][:1] == [g["playerId"]], "ignora acento e maiúsculas")
check(indice.sugerir("") == [] and indice.sugerir("de") == [] and indice.sugerir("zzqxw") == [],
      "vazio, só partícula ou nada parecido: lista vazia")
silvas = indice.sugerir("silva")
ranks = [j["rank"] for j in silvas]
check(len(silvas) == 8 and all("silva" in itf.tokens_nome(itf.obter_nome_jogador(j)) for j in silvas) and ranks == sorted(ranks),
      f"'silva': 8 com o sobrenome inteiro, melhores do ranking primeiro ({ranks[:3]}...)")
prefixo = indice.sugerir("silv", limite=50)
check(any("silva" not in itf.tokens_nome(itf.obter_nome_jogador(j)) for j in prefixo), "'silv' também traz Silveira, Silvano…")
t0 = time.perf_counter()
for consulta in ("sa", "silva jo", "ma", "rodrig", "lu co", "fe", "gianotti nicolas"):
    indice.sugerir(consulta)
dt = time.perf_counter() - t0
check(dt < 1.0, f"7 buscas em {dt * 1000:.0f} ms")

print("== otimizacoes dao o mesmo resultado que antes ==")
def primeiro_valor_original(obj, chaves):
    # Copia da versao anterior (montava a copia em minusculas sempre).
    if not isinstance(obj, dict):
        return None
    obj_lower = {str(k).lower(): v for k, v in obj.items()}
    for chave in chaves:
        valor = obj.get(chave)
        if valor in (None, ""):
            valor = obj_lower.get(chave.lower())
        if valor not in (None, ""):
            return valor
    for chave in ("player", "person", "competitor", "athlete"):
        valor = obj.get(chave)
        if isinstance(valor, dict):
            aninhado = primeiro_valor_original(valor, chaves)
            if aninhado not in (None, ""):
                return aninhado
    return None
grupos = (itf.PLAYER_NAME_KEYS, itf.PLAYER_FIRST_NAME_KEYS, itf.PLAYER_LAST_NAME_KEYS,
          itf.PLAYER_RANK_KEYS, itf.PLAYER_POINTS_KEYS)
estranhos = [{"Points": 5, "RANK": "3"}, {"points": "", "POINTS": 7}, {"player": {"Name": "A B"}},
             {"person": {"lastName": "X", "points": 2}}, {}, None, {"pts": 0, "points": None}]
diferentes = sum(primeiro_valor_original(j, g) != itf.primeiro_valor(j, g) for j in rk + estranhos for g in grupos)
check(diferentes == 0, f"primeiro_valor igual ao anterior ({len(rk) + len(estranhos)} registros x {len(grupos)} campos)")

ordenados = estimativa.pontos_ordenados(rk)
por_pontos = estimativa.ordenar_por_pontos(rk)
random.seed(11)
iguais = True
for _ in range(60):
    jogador = random.choice(rk + [None])
    pontos, pior = random.randint(0, 800), random.choice([None, random.randint(0, 50)])
    iguais &= (estimativa.estimar_ranking(rk, jogador, pontos, 10, pior)
               == estimativa.estimar_ranking(rk, jogador, pontos, 10, pior, ordenados=ordenados))
check(iguais, "estimar_ranking com os pontos já ordenados = sem (60 casos)")
alvos = random.sample(range(1, len(rk) + 5), 150)
check(all(estimativa.pontos_para_posicao(rk, alvo, ex) == estimativa.pontos_para_posicao(rk, alvo, ex, por_pontos=por_pontos)
          for alvo in alvos for ex in (None, rk[alvo % len(rk)]["playerId"])),
      "pontos_para_posicao com o ranking já ordenado = sem (150 alvos, com e sem excluir)")
fim()
