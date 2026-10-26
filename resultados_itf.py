"""
Resultados da ITF -> pontos de ranking
======================================
Converte o que o site da ITF devolve (atividade do atleta, calendario e
chaves dos torneios — ver itf_dados.py) em resultados com pontos, usando a
tabela oficial (pontuacao_itf_2026.json), e marca quais contam no ranking.

A ITF nao publica os pontos de cada torneio, so as partidas. Regras usadas
(Regulamento 2026, item 10 e Apendice B):
  - os pontos sao os da rodada em que a dupla parou (campeao = W);
  - quem jogou o qualifying e entrou na chave principal so leva os pontos da
    chave principal; os do qualifying sao para quem nao se classificou;
  - o bonus draw (consolacao) soma com a chave principal;
  - bye ou W.O. so valem como rodada vencida se a dupla venceu ao menos uma
    partida jogada na mesma chave; senao ela leva os pontos da rodada anterior
    a eliminacao; quem desiste sem jogar nenhuma partida nao pontua;
  - os pontos entram na segunda-feira depois do torneio e valem 52 semanas;
  - contam os 10 melhores resultados validos.

Quando a ITF nao publicou a chave, o tamanho e presumido (chave de 32,
qualifying de 2 rodadas) e o resultado sai marcado como `presumido` — so muda
os pontos de quem caiu na 1a rodada.

Este modulo nao acessa a internet nem tem input/print.
"""

import datetime
import re
from dataclasses import dataclass

import pontuacao

MESES = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

CATEGORIAS_CALENDARIO = {
    "BT10": "BT10", "BT50": "BT50", "BT100": "BT100", "BT200": "BT200", "BT400": "BT400",
    "SS100": "SS100", "SS75": "SS75",
}
CHAVE_PRESUMIDA = (32, 32)        # (chave principal, qualifying) mais comum na tabela
RODADAS_QUALY_PRESUMIDAS = 2

PRINCIPAL = "principal"
QUALIFYING = "qualifying"

NOMES_RODADA = {
    "W": "Campeão", "F": "Final (vice)", "SF": "Semifinal", "QF": "Quartas de final",
    "R16": "Oitavas de final", "R32/24": "1ª rodada (chave de 32)", "R48": "1ª rodada (chave de 48)",
    "FRQ": "Qualy: rodada final", "R2": "Qualy: 2ª rodada", "R1": "Qualy: 1ª rodada",
}


@dataclass
class ResultadoITF:
    torneio: str
    chave_torneio: str | None
    link: str | None
    inicio: datetime.date | None
    fim: datetime.date | None
    categoria: str | None          # id da tabela de pontos (BT200, SS100, WCH...)
    parceiro: str | None
    fase: str | None               # principal | qualifying
    rodada: str | None             # codigo da tabela (W, F, SF, ..., FRQ, R1)
    pontos: int | None             # principal ou qualy + bonus
    pontos_bonus: int = 0
    bonus_rodada: str | None = None
    presumido: bool = False
    situacao: str = "ok"           # ok | em_andamento | sem_regra | sem_pontos
    motivo: str | None = None
    entrada: datetime.date | None = None
    vence: datetime.date | None = None
    conta: bool = False
    ativo: bool = False

    @property
    def rodada_texto(self) -> str:
        if self.situacao == "em_andamento":
            return "Em andamento"
        return NOMES_RODADA.get(self.rodada or "", self.rodada or "—")


# ═══════════════════════════════════════════════════════════════════════════════
# DATAS E CATEGORIA
# ═══════════════════════════════════════════════════════════════════════════════
def datas_do_torneio(texto: str | None) -> tuple[datetime.date | None, datetime.date | None]:
    """'23 Oct to 25 Oct 2026', '28 Sep to 01 Oct 2026', '30 Dec 2025 to 02 Jan 2026'."""
    m = re.search(r"(\d{1,2}) (\w{3})(?: (\d{4}))? to (\d{1,2}) (\w{3}) (\d{4})", texto or "")
    if not m or m[2].lower() not in MESES or m[5].lower() not in MESES:
        return None, None
    fim = datetime.date(int(m[6]), MESES[m[5].lower()], int(m[4]))
    ano_inicio = int(m[3]) if m[3] else (fim.year - 1 if MESES[m[2].lower()] > fim.month else fim.year)
    return datetime.date(ano_inicio, MESES[m[2].lower()], int(m[1])), fim


def entrada_no_ranking(fim: datetime.date) -> datetime.date:
    """Segunda-feira seguinte ao fim do torneio."""
    return fim + datetime.timedelta(days=7 - fim.weekday())


def chave_do_link(link: str | None) -> str | None:
    """'/en/tournament/bt200-florianopolis/bra/2026/b-tour-bra-2026-068/' -> 'B-TOUR-BRA-2026-068'."""
    partes = [p for p in (link or "").split("/") if p]
    return partes[-1].upper() if partes and partes[0] == "en" and "tournament" in partes else None


def categoria_do_torneio(nome: str, codigo_calendario: str | None = None) -> tuple[str | None, str | None]:
    """(id da categoria na tabela, motivo quando nao da para calcular)."""
    if codigo_calendario in CATEGORIAS_CALENDARIO:
        return CATEGORIAS_CALENDARIO[codigo_calendario], None
    nome = nome or ""
    m = re.search(r"\bBT\s?(10|50|100|200|400)\b", nome, re.IGNORECASE)
    if m:
        return f"BT{m[1]}", None
    if re.search(r"tour finals", nome, re.IGNORECASE):
        return None, "Tour Finals não é calculado."
    if re.search(r"world championships", nome, re.IGNORECASE):
        return "WCH", None
    if re.search(r"sand series", nome, re.IGNORECASE):
        return None, "Sand Series sem categoria (100+ ou 75) — atualize o calendário."
    if re.search(r"championships", nome, re.IGNORECASE):
        return None, "Campeonato regional: a ITF não informa se é RC1 ou RC2."
    return None, "Categoria não reconhecida."


# ═══════════════════════════════════════════════════════════════════════════════
# CHAVES
# ═══════════════════════════════════════════════════════════════════════════════
def estrutura_do_drawsheet(drawsheet: dict) -> dict | None:
    """{"tamanho": 32, "rodadas": 5} a partir do GetDrawsheet da ITF."""
    grupos = (drawsheet or {}).get("koGroups") or []
    if not grupos or not grupos[0].get("rounds"):
        return None
    rodadas = grupos[0]["rounds"]
    primeira = min(rodadas, key=lambda r: r.get("roundNumber") or 0)
    return {"tamanho": 2 * len(primeira.get("matches") or []), "rodadas": len(rodadas)}


def chave_da_tabela(tabela: dict, categoria: str, principal: int | None,
                    qualifying: int | None) -> dict:
    """A chave da tabela que bate com os tamanhos; sem tamanho, a presumida.
    Chave de 24 com byes aparece com 32 lugares no drawsheet."""
    chaves = pontuacao.obter_categoria(tabela, categoria)["chaves"]
    principal = principal or CHAVE_PRESUMIDA[0]
    qualifying = CHAVE_PRESUMIDA[1] if qualifying is None else qualifying
    for md in (principal, 24 if principal == 32 else None):
        for ch in chaves:
            if ch["chave_principal"] == md and ch["qualifying"] == qualifying:
                return ch
    for ch in chaves:
        if ch["chave_principal"] == principal:
            return ch
    return next((c for c in chaves if c["id"] == "32x32"), chaves[0])


def _numero_da_rodada(rotulo: str) -> int | None:
    m = re.match(r"(\d+)(?:st|nd|rd|th) round", rotulo or "", re.IGNORECASE)
    return int(m[1]) if m else None


def codigo_principal(rotulo: str, tamanho: int) -> str | None:
    """Rotulo da ITF na chave principal -> codigo da tabela (sem W)."""
    rotulo = (rotulo or "").lower()
    if rotulo.startswith("final"):
        return "F"
    if rotulo.startswith("semi"):
        return "SF"
    if rotulo.startswith("quarter"):
        return "QF"
    n = _numero_da_rodada(rotulo)
    if n is None:
        return None
    total = max(3, (max(tamanho, 2) - 1).bit_length())      # 24/32 -> 5, 16 -> 4, 48/64 -> 6
    restantes = total - n + 1                                 # contando esta
    if restantes == 4:
        return "R16"
    if restantes == 5:
        return "R32/24"
    if restantes == 6 and tamanho == 48:
        return "R48"
    return None


def codigo_qualifying(rotulo: str, rodadas: int) -> str | None:
    n = _numero_da_rodada(rotulo)
    if n is None:
        return "FRQ" if (rotulo or "").lower().startswith("final") else None
    if n == rodadas:
        return "FRQ"
    return {1: "R1", 2: "R2"}.get(n)


def codigo_bonus(rotulo: str) -> str | None:
    """Bonus draw: rodadas da tabela vao de R16 a W; a 1a rodada de um bonus
    draw de chave de 32 (16 duplas) e R16."""
    codigo = codigo_principal(rotulo, 16)
    return codigo if codigo in ("F", "SF", "QF", "R16") else None


# ═══════════════════════════════════════════════════════════════════════════════
# UM EVENTO (CHAVE PRINCIPAL, QUALIFYING OU BONUS)
# ═══════════════════════════════════════════════════════════════════════════════
def _desfecho(partidas: list[dict]) -> tuple[str, str | None, bool]:
    """('campeao' | 'eliminado' | 'classificado' | 'andamento' | 'desistiu',
    rotulo da rodada decisiva, venceu alguma partida jogada)."""
    if not partidas:
        return "andamento", None, False
    venceu_jogando = any(p.get("resultCode") == "W" for p in partidas)
    ultima = partidas[0]                       # a ITF manda da rodada mais longe para a 1a
    rotulo = (ultima.get("roundGroup") or {}).get("Value")
    codigo = ultima.get("resultCode") or ""
    if codigo == "W":
        return ("campeao" if (rotulo or "").lower().startswith("final") else "venceu"), rotulo, True
    if codigo == "L":
        return "eliminado", rotulo, venceu_jogando
    if codigo == "O":
        # W.O. na ultima partida registrada: a dupla nao seguiu, entao foi ela
        # que deu o W.O. Antes de outras partidas seria W.O. recebido.
        return ("eliminado" if venceu_jogando else "desistiu"), rotulo, venceu_jogando
    return "andamento", rotulo, venceu_jogando


def _rodada_anterior(codigo: str, ordem: list[str]) -> str | None:
    i = ordem.index(codigo) if codigo in ordem else -1
    return ordem[i - 1] if i > 0 else None


ORDEM_PRINCIPAL = ["R48", "R32/24", "R16", "QF", "SF", "F", "W"]
ORDEM_QUALY = ["R1", "R2", "FRQ"]


def resultado_do_evento(evento: dict, fase: str, tamanho: int, rodadas_qualy: int) -> dict:
    """{"codigo": ..., "estado": ..., "motivo": ...} de um evento da atividade."""
    partidas = evento.get("matches") or []
    estado, rotulo, venceu_jogando = _desfecho(partidas)
    if estado in ("andamento",):
        return {"codigo": None, "estado": "em_andamento"}
    if estado == "desistiu":
        return {"codigo": None, "estado": "sem_pontos",
                "motivo": "Desistiu (W.O.) sem jogar nenhuma partida: não pontua."}

    if fase == QUALIFYING:
        if estado in ("venceu", "campeao"):
            return {"codigo": None, "estado": "classificado"}
        codigo = codigo_qualifying(rotulo, rodadas_qualy)
        ordem = ORDEM_QUALY
    else:
        codigo = "W" if estado == "campeao" else codigo_principal(rotulo, tamanho)
        if estado == "venceu":
            return {"codigo": None, "estado": "em_andamento"}
        ordem = ORDEM_PRINCIPAL

    if codigo is None:
        return {"codigo": None, "estado": "sem_regra", "motivo": f"Rodada não reconhecida: {rotulo}."}

    # Bye/W.O. sem nenhuma vitoria jogada: pontos da rodada anterior a eliminacao.
    avancou_sem_jogar = any(p.get("resultCode") in ("B", "O") for p in partidas[1:])
    if estado == "eliminado" and not venceu_jogando and avancou_sem_jogar:
        anterior = _rodada_anterior(codigo, ordem)
        return {"codigo": anterior, "estado": "ok" if anterior else "sem_pontos",
                "motivo": "Avançou por bye/W.O. sem vencer partida: leva os pontos da rodada anterior."}
    return {"codigo": codigo, "estado": "ok"}


# ═══════════════════════════════════════════════════════════════════════════════
# ATIVIDADE COMPLETA
# ═══════════════════════════════════════════════════════════════════════════════
def _nome_parceiro(evento: dict) -> str | None:
    p = evento.get("partner") or {}
    nome = " ".join(x.strip() for x in (p.get("givenName"), p.get("familyName")) if x and x.strip())
    return nome or None


def _pontos(tabela: dict, categoria: str, chave: dict, fase: str, codigo: str | None) -> int | None:
    if codigo is None:
        return None
    valor = chave["pontos"].get(fase, {}).get(codigo)
    return valor or 0


def resultados_do_atleta(itens: list[dict], tabela: dict,
                         calendario: dict[str, dict] | None = None,
                         chaves: dict[str, dict] | None = None,
                         genero: str = "M") -> list[ResultadoITF]:
    """`itens`: o GetPlayerActivity da ITF. `calendario`: torneios por chave
    (B-TOUR-...), para a categoria. `chaves`: estrutura das chaves ja baixadas,
    por chave do torneio — {"M": {"principal": {...}, "qualifying": {...}}}."""
    calendario = calendario or {}
    chaves = chaves or {}
    resultados = []

    for item in itens:
        chave_torneio = chave_do_link(item.get("tournamentLink"))
        inicio, fim = datas_do_torneio(item.get("dates"))
        info_cal = calendario.get(chave_torneio or "", {})
        categoria, motivo = categoria_do_torneio(item.get("tournamentName"), info_cal.get("category"))

        eventos = {"principal": None, "qualifying": None, "bonus": None}
        for evento in item.get("events") or []:
            tipo = (evento.get("drawType") or "").lower()
            fase = "principal" if tipo.startswith("main") else "qualifying" if tipo.startswith("qualif") \
                else "bonus" if tipo.startswith("consol") else None
            if fase and eventos[fase] is None:
                eventos[fase] = evento

        estrutura = (chaves.get(chave_torneio or "") or {}).get(genero) or {}
        md = (estrutura.get("principal") or {}).get("tamanho")
        qd_info = estrutura.get("qualifying") or {}
        qd = qd_info.get("tamanho") if estrutura else None
        presumido = not estrutura

        base = eventos["principal"] or eventos["qualifying"]
        resultado = ResultadoITF(
            torneio=item.get("tournamentName") or "?", chave_torneio=chave_torneio,
            link=item.get("tournamentLink"), inicio=inicio, fim=fim, categoria=categoria,
            parceiro=_nome_parceiro(base) if base else None, fase=None, rodada=None, pontos=None,
            entrada=entrada_no_ranking(fim) if fim else None,
        )
        if resultado.entrada:
            resultado.vence = resultado.entrada + datetime.timedelta(weeks=52)

        if base is None:
            resultado.situacao, resultado.motivo = "sem_regra", "Torneio sem chave principal nem qualifying."
            resultados.append(resultado)
            continue
        if categoria is None:
            resultado.situacao, resultado.motivo = "sem_regra", motivo
            resultados.append(resultado)
            continue

        ch = chave_da_tabela(tabela, categoria, md, qd if estrutura.get("qualifying") else (0 if estrutura else None))
        tamanho = md or ch["chave_principal"]
        rodadas_qualy = qd_info.get("rodadas") or ch.get("rodadas_qualifying") or RODADAS_QUALY_PRESUMIDAS

        fase = PRINCIPAL if eventos["principal"] else QUALIFYING
        r = resultado_do_evento(eventos[fase], fase, tamanho, rodadas_qualy)
        if r["estado"] == "classificado":
            # Classificou no qualy mas a chave principal nao veio na atividade.
            resultado.situacao, resultado.motivo = "sem_regra", "Classificou no qualifying; chave principal não encontrada."
        resultado.fase = fase
        resultado.rodada = r["codigo"]
        resultado.motivo = resultado.motivo or r.get("motivo")
        if r["estado"] in ("em_andamento", "sem_pontos", "sem_regra"):
            resultado.situacao = r["estado"]
            resultado.pontos = 0 if r["estado"] == "sem_pontos" else None
        elif resultado.situacao == "ok":
            resultado.pontos = _pontos(tabela, categoria, ch, fase, r["codigo"])
            # Na 1a rodada o tamanho da chave muda os pontos; nas outras, nao.
            primeira = r["codigo"] in ("R32/24", "R16", "R1") or (fase == QUALIFYING and r["codigo"] == "FRQ")
            resultado.presumido = presumido and primeira

        if eventos["bonus"] is not None and fase == PRINCIPAL and resultado.situacao == "ok":
            estado, rotulo, _ = _desfecho(eventos["bonus"].get("matches") or [])
            codigo = "W" if estado == "campeao" else codigo_bonus(rotulo) if estado == "eliminado" else None
            if codigo:
                resultado.bonus_rodada = codigo
                resultado.pontos_bonus = ch["pontos"].get("bonus", {}).get(codigo) or 0
                resultado.pontos += resultado.pontos_bonus
        resultados.append(resultado)

    return resultados


def marcar_contando(resultados: list[ResultadoITF], data_ref: datetime.date,
                    melhores: int) -> dict:
    """Marca `ativo` (valendo na data) e `conta` (entre os `melhores`). Devolve
    o resumo: soma, quantos contam, o pior que conta."""
    for r in resultados:
        r.ativo = bool(
            r.situacao == "ok" and r.pontos is not None and r.entrada and r.vence
            and r.entrada <= data_ref < r.vence
        )
        r.conta = False
    ativos = sorted((r for r in resultados if r.ativo), key=lambda r: r.pontos, reverse=True)
    contando = ativos[:melhores]
    for r in contando:
        r.conta = True
    return {
        "soma": sum(r.pontos for r in contando),
        "contando": len(contando),
        "ativos": len(ativos),
        "pior": contando[-1] if len(contando) >= melhores else None,
        "incertos": sum(1 for r in resultados if r.situacao == "sem_regra"
                        and r.entrada and r.vence and r.entrada <= data_ref < r.vence),
    }


def pontos_validos(resultados: list[ResultadoITF], data: datetime.date) -> list[int]:
    """Pontos de cada resultado que ainda vale em `data` (sem cortar nos 10)."""
    return [r.pontos for r in resultados
            if r.situacao == "ok" and r.pontos is not None and r.entrada and r.vence
            and r.entrada <= data < r.vence]
