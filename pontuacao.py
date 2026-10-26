"""
Pontuacao ITF — pontos por rodada
=================================
Le a tabela oficial de pontos do ITF Beach Tennis World Tour
(pontuacao_itf_2026.json) e responde quantos pontos cada rodada vale.

A tabela fica em JSON, e nao no codigo, para poder ser corrigida ou trocada
pela do proximo ano sem mexer aqui. Cada categoria tem varias chaves (tamanho
da chave principal x tamanho do qualifying), e os pontos mudam conforme a
chave. Rodada com valor null na tabela nao vale pontos naquela chave.

Este modulo nao tem input/print: o terminal (app.py) e a futura interface
grafica chamam as mesmas funcoes.
"""

import json
import pathlib
from dataclasses import dataclass, field

PASTA = pathlib.Path(__file__).resolve().parent
ARQUIVO_TABELA = PASTA / "pontuacao_itf_2026.json"

FASE_PRINCIPAL = "principal"
FASE_QUALIFYING = "qualifying"
FASE_BONUS = "bonus"
FASES = (FASE_PRINCIPAL, FASE_QUALIFYING, FASE_BONUS)

NOMES_FASES = {
    FASE_PRINCIPAL:  "Chave principal",
    FASE_QUALIFYING: "Qualifying",
    FASE_BONUS:      "Bonus draw (consolação)",
}


class ErroPontuacao(ValueError):
    """Categoria, chave ou rodada que nao existe na tabela."""


@dataclass
class CalculoPontos:
    total: int
    partes: list[tuple[str, int]] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# LEITURA DA TABELA
# ═══════════════════════════════════════════════════════════════════════════════
def carregar_tabela(caminho: pathlib.Path = ARQUIVO_TABELA) -> dict:
    try:
        tabela = json.loads(pathlib.Path(caminho).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErroPontuacao(f"tabela de pontos nao encontrada: {caminho}") from None
    except json.JSONDecodeError as exc:
        raise ErroPontuacao(f"tabela de pontos invalida ({caminho}): {exc}") from None

    if not isinstance(tabela.get("categorias"), list):
        raise ErroPontuacao(f"tabela de pontos sem a lista de categorias: {caminho}")
    return tabela


def listar_categorias(tabela: dict) -> list[dict]:
    return tabela["categorias"]


def obter_categoria(tabela: dict, categoria_id: str) -> dict:
    for categoria in tabela["categorias"]:
        if categoria["id"] == categoria_id:
            return categoria
    raise ErroPontuacao(f"categoria desconhecida: {categoria_id}")


def obter_chave(categoria: dict, chave_id: str) -> dict:
    for chave in categoria.get("chaves", []):
        if chave["id"] == chave_id:
            return chave
    raise ErroPontuacao(f"chave {chave_id} nao existe em {categoria['nome']}")


def melhores_resultados(tabela: dict) -> int:
    """Quantos resultados entram na soma do ranking (regra da ITF)."""
    return int(tabela["regras_ranking"]["melhores_resultados"])


def descrever_chave(chave: dict) -> str:
    texto = f"chave principal {chave['chave_principal']}"
    if chave["qualifying"]:
        texto += (
            f" · qualifying {chave['qualifying']} "
            f"({chave['classificados']} classificados, "
            f"{chave['rodadas_qualifying']} rodada(s))"
        )
    else:
        texto += " · sem qualifying"
    return texto


def nome_rodada(tabela: dict, fase: str, codigo: str) -> str:
    return tabela["rodadas"].get(fase, {}).get(codigo, codigo)


def nome_bundle(tabela: dict, bundle_id: str) -> str:
    return tabela.get("bundles", {}).get(bundle_id, bundle_id)


# ═══════════════════════════════════════════════════════════════════════════════
# PONTOS POR RODADA
# ═══════════════════════════════════════════════════════════════════════════════
def rodadas_com_pontos(tabela: dict, categoria_id: str, chave_id: str) -> dict[str, list[dict]]:
    """Por fase, as rodadas que valem pontos nesta chave, do campeao para tras.

    Cada item: {"codigo", "nome", "pontos", "bundles": {bundle_id: pontos}}.
    Rodada com null na tabela fica de fora: nao vale pontos nesta chave.
    """
    categoria = obter_categoria(tabela, categoria_id)
    chave = obter_chave(categoria, chave_id)
    bundles = categoria.get("bundles", {})

    resultado: dict[str, list[dict]] = {}
    for fase in FASES:
        linhas = []
        for codigo, pontos in chave["pontos"].get(fase, {}).items():
            if pontos is None:
                continue
            linha = {
                "codigo":  codigo,
                "nome":    nome_rodada(tabela, fase, codigo),
                "pontos":  pontos,
                "bundles": {},
            }
            # Bundles so existem na chave principal (e a tabela da ITF so da
            # valores ate a rodada de 32/24).
            if fase == FASE_PRINCIPAL:
                linha["bundles"] = {b: valores.get(codigo) for b, valores in bundles.items()}
            linhas.append(linha)
        resultado[fase] = linhas
    return resultado


def calcular_pontos(
    tabela: dict,
    categoria_id: str,
    chave_id: str,
    fase: str,
    rodada: str,
    bundles: tuple[str, ...] | list[str] = (),
    rodada_bonus: str | None = None,
) -> CalculoPontos:
    """Pontos de quem parou em `rodada` (W = campeao).

    `bundles` sao os bundles oferecidos pelo torneio; so valem na chave
    principal. `rodada_bonus` e ate onde a dupla chegou no bonus draw, que
    soma com a chave principal.
    """
    if fase not in (FASE_PRINCIPAL, FASE_QUALIFYING):
        raise ErroPontuacao(f"fase invalida para colocacao: {fase}")

    categoria = obter_categoria(tabela, categoria_id)
    if not categoria.get("por_colocacao", True):
        raise ErroPontuacao(
            f"{categoria['nome']} nao pontua por colocacao — informe os pontos direto"
        )
    chave = obter_chave(categoria, chave_id)

    pontos_fase = chave["pontos"].get(fase, {})
    if rodada not in pontos_fase:
        raise ErroPontuacao(f"rodada {rodada} nao existe em {NOMES_FASES[fase].lower()}")

    calculo = CalculoPontos(total=0)
    base = pontos_fase[rodada]
    descricao = f"{categoria['nome']} — {NOMES_FASES[fase].lower()}: {nome_rodada(tabela, fase, rodada)}"
    if base is None:
        calculo.avisos.append("Essa rodada não vale pontos nesta chave.")
        base = 0
    calculo.partes.append((descricao, base))
    calculo.total += base

    if bundles:
        disponiveis = categoria.get("bundles", {})
        if fase != FASE_PRINCIPAL:
            calculo.avisos.append("Bundles só valem na chave principal; ignorados.")
        else:
            for bundle_id in bundles:
                if bundle_id not in disponiveis:
                    calculo.avisos.append(
                        f"{categoria['nome']} não tem bundle {nome_bundle(tabela, bundle_id)}; ignorado."
                    )
                    continue
                valor = disponiveis[bundle_id].get(rodada)
                if valor is None:
                    calculo.avisos.append(
                        f"A tabela de bundles não define pontos para {rodada}; "
                        f"{nome_bundle(tabela, bundle_id)} ficou de fora."
                    )
                    continue
                calculo.partes.append((f"Bundle {nome_bundle(tabela, bundle_id)}", valor))
                calculo.total += valor

    if rodada_bonus:
        if fase != FASE_PRINCIPAL:
            raise ErroPontuacao("bonus draw so existe para quem jogou a chave principal")
        pontos_bonus = chave["pontos"].get(FASE_BONUS, {})
        valor = pontos_bonus.get(rodada_bonus)
        if rodada_bonus not in pontos_bonus:
            raise ErroPontuacao(f"rodada {rodada_bonus} nao existe no bonus draw")
        if valor is None:
            calculo.avisos.append("Essa rodada do bonus draw não vale pontos nesta chave.")
            valor = 0
        calculo.partes.append((nome_rodada(tabela, FASE_BONUS, rodada_bonus), valor))
        calculo.total += valor

    return calculo
