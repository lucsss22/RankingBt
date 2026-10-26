"""
Estimativa de ranking ITF
=========================
Dado o ranking atual (o mesmo cache que a tierlist usa) e os pontos de um
torneio novo, estima a posicao do atleta no proximo ranking.

Regras usadas, todas conferidas:
  - posicao = 1 + quantos jogadores tem MAIS pontos (empatados dividem a
    posicao). Bate com o rank de todos os 3243 jogadores do cache de 05/10/2026;
  - o ranking soma so os N melhores resultados em 52 semanas (N vem da tabela
    de pontos — hoje 10).

O que NAO da para saber com os dados do ranking, e por isso vira faixa ou
aviso em vez de numero exato:
  - quanto vale o pior resultado que conta hoje. Com N ou mais torneios, o
    novo resultado so entra se for melhor que ele, e substitui ele;
  - quais pontos vencem (saem da janela de 52 semanas) ate a proxima
    atualizacao;
  - quanto os outros jogadores vao somar na mesma semana.

Este modulo nao tem input/print.
"""

import bisect
from collections import Counter
from dataclasses import dataclass, field

import pontuacao
from itf_beach_tennis_tierlist import (
    THRESHOLD_MATCH,
    avaliar_match_nome,
    encontrar_jogador,
    obter_nome_jogador,
    obter_pontos_jogador,
    obter_rank_jogador,
    parse_inteiro,
    tokens_nome,
)

AVISO_GERAL = (
    "Estimativa: considera que o resto do ranking fica como está e não desconta "
    "pontos que vencem na janela de 52 semanas. O ranking oficial só sai na "
    "segunda-feira seguinte ao torneio."
)


@dataclass
class Estimativa:
    encontrado: bool
    nome_itf: str | None
    rank_atual: int | None
    pontos_atuais: int
    torneios_no_ranking: int | None
    pontos_torneio: int
    pontos_min: int
    pontos_max: int
    rank_melhor: int | None   # posicao se o total for pontos_max
    rank_pior: int | None     # posicao se o total for pontos_min
    exata_nos_pontos: bool
    avisos: list[str] = field(default_factory=list)


class IndiceDeNomes:
    """Busca por nome sem varrer o ranking inteiro a cada nome — a tierlist
    procura dezenas de nomes de uma vez.

    O match continua sendo o da tierlist (avaliar_match_nome). O indice so
    descarta antes quem nao divide pelo menos dois pedacos do nome: o match
    nunca aceita menos que dois em comum, entao ninguem que casaria fica de
    fora, e o desempate segue a ordem do ranking, como em encontrar_jogador.
    """

    def __init__(self, ranking: list[dict]):
        self.ranking = ranking
        self._posicoes: dict[str, list[int]] = {}
        self._tokens: list[set[str]] = []
        for posicao, jogador in enumerate(ranking):
            tokens = tokens_nome(obter_nome_jogador(jogador))
            self._tokens.append(tokens)
            for token in tokens:
                self._posicoes.setdefault(token, []).append(posicao)

    def sugerir(self, texto: str, limite: int = 8) -> list[dict]:
        """Autocompletar: quem tem cada pedaco digitado no comeco de algum
        pedaco do nome ('sil jo' acha 'SILVA Joao'). Quem tem os pedacos
        inteiros vem antes; depois, os melhores do ranking."""
        pedacos = tokens_nome(texto)
        if not pedacos:
            return []
        candidatos: set[int] | None = None
        for pedaco in pedacos:
            achados = {p for token, posicoes in self._posicoes.items() if token.startswith(pedaco) for p in posicoes}
            candidatos = achados if candidatos is None else candidatos & achados
            if not candidatos:
                return []

        def ordem(posicao: int) -> tuple:
            rank = parse_inteiro(obter_rank_jogador(self.ranking[posicao]))
            return (-len(pedacos & self._tokens[posicao]), rank or float("inf"), posicao)

        return [self.ranking[p] for p in sorted(candidatos, key=ordem)[:limite]]

    def encontrar(self, nome: str) -> dict | None:
        em_comum = Counter(
            posicao for token in tokens_nome(nome) for posicao in self._posicoes.get(token, ())
        )
        melhor = None
        melhor_score = 0.0
        for posicao in sorted(p for p, quantos in em_comum.items() if quantos >= 2):
            jogador = self.ranking[posicao]
            score = avaliar_match_nome(nome, obter_nome_jogador(jogador))
            if score > melhor_score:
                melhor_score = score
                melhor = jogador
        return melhor if melhor_score >= THRESHOLD_MATCH else None


def localizar_atleta(ranking: list[dict], player_id: int | None = None,
                     nome: str | None = None) -> dict | None:
    """Pelo playerId da ITF quando o atleta ja esta vinculado; senao, pelo
    mesmo match de nome da tierlist."""
    if player_id is not None:
        for jogador in ranking:
            if jogador.get("playerId") == player_id:
                return jogador
    if nome:
        return encontrar_jogador(nome, ranking)
    return None


def pontos_ordenados(ranking: list[dict]) -> list[int]:
    """Pontos de todo mundo, negativos e em ordem crescente — o formato que o
    bisect precisa para contar quem tem mais pontos."""
    return sorted(-parse_inteiro(obter_pontos_jogador(j), 0) for j in ranking)


def ordenar_por_pontos(ranking: list[dict]) -> list[dict]:
    """Do mais pontuado ao menos; empate fica na ordem do ranking."""
    return sorted(ranking, key=lambda j: parse_inteiro(obter_pontos_jogador(j), 0), reverse=True)


def posicao_com_pontos(pontos: int, ordenados_neg: list[int]) -> int | None:
    """Posicao de quem tem `pontos`. Sem pontos, sem ranking."""
    if pontos <= 0:
        return None
    return bisect.bisect_left(ordenados_neg, -pontos) + 1


def estimar_ranking(
    ranking: list[dict],
    jogador: dict | None,
    pontos_torneio: int,
    melhores: int,
    pior_resultado: int | None = None,
    ordenados: list[int] | None = None,
) -> Estimativa:
    """`jogador` e o registro do atleta no ranking (None = sem ranking hoje).

    `pior_resultado` e o menor resultado entre os `melhores` que contam hoje.
    So faz diferenca para quem ja tem `melhores` torneios ou mais; sem ele, a
    estimativa sai como faixa. `ordenados` e o pontos_ordenados(ranking) ja
    calculado, quando quem chama guarda o ranking em memoria.
    """
    if pontos_torneio < 0:
        raise ValueError("pontos do torneio nao podem ser negativos")
    if pior_resultado is not None and pior_resultado < 0:
        raise ValueError("pior resultado nao pode ser negativo")

    avisos = [AVISO_GERAL]

    if jogador:
        pontos_atuais = parse_inteiro(obter_pontos_jogador(jogador), 0)
        rank_atual = parse_inteiro(obter_rank_jogador(jogador))
        torneios = parse_inteiro(jogador.get("tournamentsPlayed"))
        nome_itf = obter_nome_jogador(jogador) or None
    else:
        pontos_atuais, rank_atual, torneios, nome_itf = 0, None, 0, None
        avisos.append("Atleta fora do ranking atual: considerei 0 pontos hoje.")

    if torneios is None:
        # Sem a contagem nao da para saber se o novo resultado substitui outro.
        avisos.append(
            "A ITF não informou quantos torneios você tem no ranking; "
            "por isso a estimativa sai como faixa."
        )

    if torneios is not None and torneios < melhores:
        pontos_min = pontos_max = pontos_atuais + pontos_torneio
        exata = True
    elif pior_resultado is not None:
        pontos_min = pontos_max = pontos_atuais + max(0, pontos_torneio - pior_resultado)
        exata = True
        if pior_resultado > pontos_atuais // melhores:
            # O menor dos N melhores nunca passa da media deles.
            avisos.append(
                f"O pior resultado informado ({pior_resultado}) é maior que a média "
                f"dos seus {melhores} melhores ({pontos_atuais // melhores}); confira o valor."
            )
    else:
        # O novo total e atuais + max(0, novos - pior). O pior que conta fica
        # entre 0 e a media dos N melhores, o que limita a faixa dos dois lados.
        pontos_max = pontos_atuais + pontos_torneio
        pontos_min = pontos_atuais + max(0, pontos_torneio - pontos_atuais // melhores)
        exata = pontos_min == pontos_max
        if not exata:
            avisos.append(
                f"Você já tem {torneios if torneios is not None else '?'} torneios e só os "
                f"{melhores} melhores contam: o novo resultado só soma o quanto passar do "
                f"seu pior resultado que conta hoje. Informe esse valor para um número exato."
            )

    if ordenados is None:
        ordenados = pontos_ordenados(ranking)
    return Estimativa(
        encontrado=jogador is not None,
        nome_itf=nome_itf,
        rank_atual=rank_atual,
        pontos_atuais=pontos_atuais,
        torneios_no_ranking=torneios,
        pontos_torneio=pontos_torneio,
        pontos_min=pontos_min,
        pontos_max=pontos_max,
        rank_melhor=posicao_com_pontos(pontos_max, ordenados),
        rank_pior=posicao_com_pontos(pontos_min, ordenados),
        exata_nos_pontos=exata,
        avisos=avisos,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# META DE RANKING
# ═══════════════════════════════════════════════════════════════════════════════
# Mesma regra da estimativa: posicao = 1 + quantos tem MAIS pontos, e so os N
# melhores resultados validos somam. A meta olha para uma data (a do torneio
# escolhido, ou daqui a 4 semanas): resultados que vencem antes dela saem da
# conta. Os pontos dos outros atletas ficam como estao hoje.

def pontos_para_posicao(ranking: list[dict], alvo: int, excluir_id: int | None = None,
                        por_pontos: list[dict] | None = None) -> tuple[int, dict | None]:
    """Pontos que garantem a posicao `alvo`: os de quem esta nela hoje (empatar
    ja divide a posicao). Devolve (pontos, jogador que esta no alvo).
    `por_pontos` e o ordenar_por_pontos(ranking) ja calculado, se houver."""
    # Tirar alguem de uma lista ja ordenada (sort estavel) da o mesmo que
    # tirar antes e ordenar depois.
    outros = [j for j in (por_pontos if por_pontos is not None else ordenar_por_pontos(ranking))
              if j.get("playerId") != excluir_id]
    if alvo < 1 or alvo > len(outros):
        return 1, None
    no_alvo = outros[alvo - 1]
    return max(1, parse_inteiro(obter_pontos_jogador(no_alvo), 0)), no_alvo


def soma_dos_melhores(pontos: list[int], melhores: int) -> int:
    return sum(sorted(pontos, reverse=True)[:melhores])


def validos_sem_historico(pontos_oficiais: int, torneios: int | None, melhores: int) -> list[int]:
    """Sem os resultados torneio a torneio, monta uma lista que reproduz o total
    oficial. Com menos de N torneios o novo resultado soma inteiro (exato). Com
    N ou mais, supoe todos iguais a media: o pior real nunca passa da media,
    entao o ganho calculado e o minimo garantido (conservador)."""
    if pontos_oficiais <= 0:
        return []
    if torneios is not None and torneios < melhores:
        return [pontos_oficiais]
    media, resto = divmod(pontos_oficiais, melhores)
    return [media + resto] + [media] * (melhores - 1)


def rodada_minima(rodadas: list[tuple[str, int]], validos: list[int],
                  necessario: int, melhores: int) -> dict | None:
    """Primeira rodada (em ordem crescente de pontos) que leva o total a
    `necessario`, ja com o descarte do pior resultado quando ha N ou mais."""
    atual = soma_dos_melhores(validos, melhores)
    for codigo, pontos in rodadas:
        novo = soma_dos_melhores(validos + [pontos], melhores)
        if novo >= necessario:
            return {"codigo": codigo, "pontos": pontos, "ganho": novo - atual, "total": novo}
    return None


def rodadas_da_chave(tabela: dict, categoria_id: str, chave_id: str | None = None) -> tuple[dict, list[tuple[str, int]]]:
    """(chave usada, rodadas da chave principal da menor para a maior)."""
    categoria = pontuacao.obter_categoria(tabela, categoria_id)
    chave = next((c for c in categoria["chaves"] if c["id"] == chave_id), None) \
        or next((c for c in categoria["chaves"] if c["id"] == "32x32"), categoria["chaves"][0])
    rodadas = [(codigo, pts) for codigo, pts in chave["pontos"]["principal"].items() if pts]
    return chave, sorted(rodadas, key=lambda r: r[1])


def meta_por_categoria(tabela: dict, validos: list[int], necessario: int,
                       melhores: int) -> list[dict]:
    """Para cada categoria que pontua por rodada: ate onde precisa chegar."""
    linhas = []
    for categoria in pontuacao.listar_categorias(tabela):
        if not categoria.get("por_colocacao", True):
            continue
        chave, rodadas = rodadas_da_chave(tabela, categoria["id"])
        linhas.append({
            "categoria": categoria["id"],
            "nome": categoria["nome"],
            "chave": chave["id"],
            "rodada": rodada_minima(rodadas, validos, necessario, melhores),
            "maximo": soma_dos_melhores(validos + [rodadas[-1][1]], melhores) if rodadas else None,
        })
    return linhas
