"""
Tierlist de duplas — regras da ITF
==================================
Ordem de aceitacao (Regulamento 2026, item 14 "System of Merit"):
  A) duplas com os dois atletas ranqueados, pela menor soma dos ranks;
  B) duplas com um so ranqueado, pelo rank dele;
  C) duplas sem ranking.
Empate: entra antes a dupla com o melhor atleta individual; se ainda empatar,
a ITF sorteia — aqui a dupla fica na ordem da lista e sai marcada como empate.

Vagas (Regulamento 2026, item 12 "Draws"):
  chave principal  8 / 16 / 24 / 32           → 7 / 12 / 18 / 20 entram direto
                                               → 2 /  4 /  8 /  8 cabecas de chave
  qualifying       8 / 16 / 24 / 32 / 48 / 64  → 7 / 14 / 20 / 26 / 41 / 56 entram
Cabecas do qualifying: metade da chave do qualy (16 no de 32, 8 no de 16 —
decisao do usuario), no maximo 16: o regulamento permite ate 2 por secao e o
qualy tem no maximo 8 secoes (8 classificados).

Dupla sem nenhum ranqueado nao vira cabeca (regulamento: sem ranking
combinado, sem cabeca de chave).

Este modulo nao tem input/print; o app web usa.
"""

from dataclasses import dataclass

DIRETAS_PRINCIPAL = {8: 7, 16: 12, 24: 18, 32: 20}
CABECAS_PRINCIPAL = {8: 2, 16: 4, 24: 8, 32: 8}
DIRETAS_QUALY = {0: 0, 8: 7, 16: 14, 24: 20, 32: 26, 48: 41, 64: 56}
MAX_CABECAS_QUALY = 16

FAIXAS = {
    "cabeca":       "Cabeça de chave",
    "principal":    "Chave principal",
    "cabeca_qualy": "Cabeça do qualy",
    "qualy":        "Qualifying",
    "fora":         "Fora da chave",
}
FAIXAS_CURTAS = {"cabeca": "Cabeça", "principal": "Chave", "cabeca_qualy": "Cab. qualy",
                 "qualy": "Qualy", "fora": "Fora"}


@dataclass(frozen=True)
class Chave:
    principal: int
    qualifying: int

    @property
    def id(self) -> str:
        return f"{self.principal}x{self.qualifying}"

    @property
    def descricao(self) -> str:
        if not self.qualifying:
            return f"Chave de {self.principal} · sem qualifying"
        return f"Chave de {self.principal} · qualifying de {self.qualifying}"


# As combinacoes que existem na tabela de pontos da ITF com chave principal
# de 8 a 32 (a de 48 nao tem vagas definidas no regulamento).
CHAVES = (
    Chave(32, 32), Chave(32, 16), Chave(32, 48), Chave(32, 64),
    Chave(24, 24), Chave(24, 16), Chave(16, 16), Chave(16, 8), Chave(8, 0),
)
CHAVE_PADRAO = CHAVES[0]


def chave_por_id(chave_id: str | None) -> Chave:
    return next((c for c in CHAVES if c.id == chave_id), CHAVE_PADRAO)


@dataclass(frozen=True)
class Vagas:
    """Ultima posicao de cada faixa, contando do 1º da lista."""
    cabecas: int
    diretas: int
    cabecas_qualy: int
    qualy: int

    def ultima_posicao(self, faixa: str) -> int:
        return {"cabeca": self.cabecas, "principal": self.diretas,
                "cabeca_qualy": self.cabecas_qualy, "qualy": self.qualy}[faixa]


def vagas(chave: Chave, diretas: int | None = None) -> Vagas:
    """`diretas` troca as entradas diretas do regulamento — convites (wild
    cards) nao usados, por exemplo, viram vagas diretas."""
    diretas = diretas or DIRETAS_PRINCIPAL[chave.principal]
    cabecas = min(CABECAS_PRINCIPAL[chave.principal], diretas)
    cabecas_qualy = min(chave.qualifying // 2, MAX_CABECAS_QUALY)
    qualy = DIRETAS_QUALY.get(chave.qualifying, chave.qualifying)
    return Vagas(cabecas=cabecas, diretas=diretas,
                 cabecas_qualy=diretas + cabecas_qualy, qualy=diretas + qualy)


# ═══════════════════════════════════════════════════════════════════════════════
# ORDEM DA ITF
# ═══════════════════════════════════════════════════════════════════════════════
def chave_de_ordem(r1: int | None, r2: int | None) -> tuple[int, int, int]:
    """(metodo, criterio, desempate) — quanto menor, antes a dupla entra."""
    ranks = sorted(r for r in (r1, r2) if r)
    if len(ranks) == 2:
        return (0, ranks[0] + ranks[1], ranks[0])   # metodo A
    if len(ranks) == 1:
        return (1, ranks[0], ranks[0])               # metodo B
    return (2, 0, 0)                                 # metodo C


def faixa_da_posicao(posicao: int, v: Vagas, tem_ranking: bool) -> str:
    if posicao <= v.cabecas and tem_ranking:
        return "cabeca"
    if posicao <= v.diretas:
        return "principal"
    if posicao <= v.cabecas_qualy and tem_ranking:
        return "cabeca_qualy"
    if posicao <= v.qualy:
        return "qualy"
    return "fora"


def ordenar(duplas: list[dict], chave: Chave, diretas: int | None = None) -> list[dict]:
    """`duplas`: dicts com "r1" e "r2" (rank ou None). Devolve copias na ordem
    da ITF com posicao, faixa, soma e a marca de empate."""
    v = vagas(chave, diretas)
    ordenadas = sorted(
        ({**d, "_ordem": chave_de_ordem(d["r1"], d["r2"])} for d in duplas),
        key=lambda d: d["_ordem"],  # sort estavel: empate fica na ordem da lista
    )
    for i, dupla in enumerate(ordenadas):
        vizinhos = ordenadas[max(0, i - 1):i] + ordenadas[i + 1:i + 2]
        metodo = dupla["_ordem"][0]
        dupla.update(
            posicao=i + 1,
            faixa=faixa_da_posicao(i + 1, v, metodo < 2),
            soma=dupla["_ordem"][1] if metodo == 0 else None,
            empate=metodo < 2 and any(o["_ordem"] == dupla["_ordem"] for o in vizinhos),
        )
    for dupla in ordenadas:
        del dupla["_ordem"]
    return ordenadas


# ═══════════════════════════════════════════════════════════════════════════════
# RANKING MINIMO DO PARCEIRO
# ═══════════════════════════════════════════════════════════════════════════════
def posicao_entre(minha: tuple, outras: list[tuple]) -> int:
    """Posicao de uma dupla entre as outras. Empate total conta como derrota:
    a ITF sorteia, entao nao da para contar com ele."""
    return 1 + sum(1 for outra in outras if outra <= minha)


def rank_maximo_parceiro(meu_rank: int | None, outras: list[tuple[int | None, int | None]],
                         alvo: int, rank_limite: int) -> dict:
    """Maior rank que o parceiro pode ter para a dupla terminar em `alvo` ou
    melhor. `outras` sao os ranks (r1, r2) das demais duplas; `rank_limite` e o
    pior rank do ranking (parceiro ranqueado mais fraco possivel).

    A posicao so piora conforme o rank do parceiro aumenta, entao a busca
    binaria acha o limite exato.
    """
    chaves = [chave_de_ordem(r1, r2) for r1, r2 in outras]

    def posicao(rank_parceiro: int | None) -> int:
        return posicao_entre(chave_de_ordem(meu_rank, rank_parceiro), chaves)

    melhor = posicao(1)
    resultado = {
        "alvo": alvo,
        "melhor_posicao": melhor,
        "posicao_sem_ranking": posicao(None),
        "rank_maximo": None,
        "qualquer_ranqueado": False,
    }
    if melhor > alvo:
        return resultado

    baixo, alto = 1, rank_limite
    while baixo < alto:
        meio = (baixo + alto + 1) // 2
        if posicao(meio) <= alvo:
            baixo = meio
        else:
            alto = meio - 1
    resultado["rank_maximo"] = baixo
    resultado["qualquer_ranqueado"] = baixo >= rank_limite
    return resultado


def parceiros_reais(ranking: list[dict], rank_maximo: int, excluir: set[int],
                    pais: str | None = None, limite: int = 20) -> list[dict]:
    """Atletas do ranking que servem de parceiro: rank ate `rank_maximo`, fora
    os de `excluir` (playerId de quem ja esta na lista). Os mais proximos do
    limite primeiro — sao os parceiros mais "alcancaveis"."""
    candidatos = [
        j for j in ranking
        if j.get("rank") and j["rank"] <= rank_maximo
        and j.get("playerId") not in excluir
        and (not pais or j.get("playerNationalityCode") == pais)
    ]
    candidatos.sort(key=lambda j: j["rank"], reverse=True)
    return candidatos[:limite]
