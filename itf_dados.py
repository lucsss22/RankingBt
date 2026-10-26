"""
Dados de torneios da ITF — calendario, chaves e atividade dos atletas
=====================================================================
Busca no site da ITF pelas mesmas APIs internas que as paginas usam:

  TournamentApi/GetCalendar       calendario (nome, datas, categoria, pais)
  TournamentApi/GetEventFilters   eventos de um torneio (so se a chave saiu)
  TournamentApi/GetDrawsheet      a chave: rodadas e tamanho
  PlayerApi/GetPlayerActivity     torneios jogados por um atleta, partida a partida

O site fica atras do Incapsula, entao tudo passa por um Chromium (Playwright),
reaproveitando a sessao e as retentativas da coleta do ranking
(SessaoITF / buscar_pagina da tierlist). Uma busca abre o navegador e leva de
20 s a alguns minutos — quando o Incapsula bloqueia, a sessao e trocada com
espera crescente (medido: atividade + calendario + 5 chaves em ~4 min). Por
isso tudo fica em cache em disco (cache_itf/), e o app web roda uma busca por
vez, em segundo plano.

A interpretacao (pontos, rodadas, quem conta) fica em resultados_itf.py.
"""

import datetime
import json
import os
import pathlib
import re
import time

import itf_beach_tennis_tierlist as itf
import resultados_itf

PASTA = pathlib.Path(__file__).resolve().parent
# Mesma pasta de dados do banco (atletas.PASTA_DADOS): BT_DADOS muda as duas.
PASTA_CACHE = pathlib.Path(os.environ.get("BT_DADOS") or PASTA) / "cache_itf"
ARQUIVO_CALENDARIO = PASTA_CACHE / "calendario.json"

API = "https://www.itftennis.com/tennis/api"
URL_CALENDARIO = (
    API + "/TournamentApi/GetCalendar?circuitCode=BT&searchString=&skip={skip}&take=100"
    "&nationCodes=&zoneCodes=&dateFrom={inicio}&dateTo={fim}&indoorOutdoor=&categories="
    "&isOrderAscending=true&orderField=startDate"
)
URL_FILTROS = API + "/TournamentApi/GetEventFilters?tournamentKey={chave}"
URL_DRAWSHEET = (
    API + "/TournamentApi/GetDrawsheet?drawsheetStructureCode=KO&eventClassificationCode={evento}"
    "&playerTypeCode={genero}&tourType={tour}&tournamentId={id}&weekNumber=0"
)
URL_ATIVIDADE = (
    API + "/PlayerApi/GetPlayerActivity?circuitCode=BT&matchTypeCode=D&playerId={id}"
    "&skip={skip}&surfaceCode=&take=100&tourCategoryCode=&year="
)

# Janela do calendario: 52 semanas para tras (categoria dos resultados que
# contam no ranking) e 4 meses para frente (proximos torneios).
DIAS_PASSADO = 400
DIAS_FUTURO = 120
HORAS_CALENDARIO = 24          # depois disso o calendario e baixado de novo
HORAS_CHAVE_NAO_PUBLICADA = 6  # chave ainda nao saiu: tenta de novo depois
MAX_CHAVES_POR_ATUALIZACAO = 8 # chaves buscadas junto com a atividade


class ErroColetaITF(RuntimeError):
    """A ITF nao respondeu com os dados esperados."""


# ═══════════════════════════════════════════════════════════════════════════════
# CACHE EM DISCO
# ═══════════════════════════════════════════════════════════════════════════════
def _ler(caminho: pathlib.Path) -> dict | None:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _gravar(caminho: pathlib.Path, dados: dict) -> None:
    """Grava num temporario e troca: quem le nunca pega o arquivo pela metade."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    os.replace(temporario, caminho)


def _arquivo_chave(chave_torneio: str) -> pathlib.Path:
    # So letras, numeros e hifen (B-TOUR-BRA-2026-068): o nome vira caminho
    # de arquivo e nunca pode sair da pasta do cache.
    if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", chave_torneio or ""):
        raise ValueError(f"chave de torneio invalida: {chave_torneio!r}")
    return PASTA_CACHE / "chaves" / f"{chave_torneio.upper()}.json"


def _arquivo_atividade(player_id: int) -> pathlib.Path:
    return PASTA_CACHE / "atividades" / f"{int(player_id)}.json"


# Calendario em memoria: ~600 KB que as paginas de Pontos e Meta liam do disco
# a cada pedido. (marca do arquivo, dados, por chave); trocado de uma vez so,
# entao leituras ao mesmo tempo nunca veem metade. Quem le nao altera os dados.
_cache_calendario: tuple | None = None


def _indexar(dados: dict | None) -> dict[str, dict]:
    return {t["tournamentKey"].upper(): t for t in (dados or {}).get("torneios", []) if t.get("tournamentKey")}


def _calendario_em_cache() -> tuple | None:
    global _cache_calendario
    try:
        estado = ARQUIVO_CALENDARIO.stat()
    except FileNotFoundError:
        return None
    marca = (estado.st_mtime_ns, estado.st_size)
    guardado = _cache_calendario
    if guardado is None or guardado[0] != marca:
        dados = _ler(ARQUIVO_CALENDARIO)
        guardado = (marca, dados, _indexar(dados))
        _cache_calendario = guardado
    return guardado


def ler_calendario() -> dict | None:
    """{"coletado_em": ts, "torneios": [...]} ou None."""
    guardado = _calendario_em_cache()
    return guardado[1] if guardado else None


def calendario_fresco(dados: dict | None = None) -> bool:
    dados = dados if dados is not None else ler_calendario()
    return bool(dados) and time.time() - dados.get("coletado_em", 0) < HORAS_CALENDARIO * 3600


def calendario_por_chave(dados: dict | None = None) -> dict[str, dict]:
    if dados is not None:
        return _indexar(dados)
    guardado = _calendario_em_cache()
    return guardado[2] if guardado else {}


def ler_chave(chave_torneio: str) -> dict | None:
    """{"coletado_em", "publicada", "eventos": {"M": {"principal": {...}, "qualifying": {...}}}}."""
    try:
        return _ler(_arquivo_chave(chave_torneio))
    except ValueError:   # chave com caractere estranho: nunca foi gravada
        return None


def chaves_em_cache(chaves_torneio) -> dict[str, dict]:
    """So as publicadas, no formato que resultados_itf espera."""
    saida = {}
    for chave in chaves_torneio:
        dados = ler_chave(chave) if chave else None
        if dados and dados.get("publicada"):
            saida[chave.upper()] = dados["eventos"]
    return saida


def precisa_buscar_chave(chave_torneio: str) -> bool:
    dados = ler_chave(chave_torneio)
    if not dados:
        return True
    if dados.get("publicada"):
        return False
    return time.time() - dados.get("coletado_em", 0) > HORAS_CHAVE_NAO_PUBLICADA * 3600


def ler_atividade(player_id: int) -> dict | None:
    """{"coletado_em": ts, "itens": [...]} ou None."""
    return _ler(_arquivo_atividade(player_id))


# ═══════════════════════════════════════════════════════════════════════════════
# COLETA (PLAYWRIGHT)
# ═══════════════════════════════════════════════════════════════════════════════
class ColetorITF:
    """Uma sessao de navegador para varias chamadas. Use com `with`."""

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ErroColetaITF("Playwright não instalado (pip install playwright).") from None
        self._playwright = sync_playwright().start()
        try:
            self._navegador = self._playwright.chromium.launch(headless=True)
            self.sessao = itf.SessaoITF(self._navegador, "M")
        except Exception:
            self._playwright.stop()
            raise
        return self

    def __exit__(self, *_):
        try:
            self.sessao.fechar()
            self._navegador.close()
        finally:
            self._playwright.stop()

    def buscar(self, url: str):
        resposta = itf.buscar_pagina(self.sessao, url)
        if resposta is None:
            raise ErroColetaITF("A ITF não respondeu. Tente de novo em alguns minutos.")
        # respiro entre chamadas: abaixo disso o Incapsula corta a sessao
        self.sessao.page.wait_for_timeout(itf.PAUSA_ENTRE_PAGINAS_MS)
        return resposta["data"]


def baixar_calendario(coletor: ColetorITF, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or datetime.date.today()
    inicio = (hoje - datetime.timedelta(days=DIAS_PASSADO)).isoformat()
    fim = (hoje + datetime.timedelta(days=DIAS_FUTURO)).isoformat()
    torneios, skip, total = [], 0, None
    while total is None or skip < total:
        dados = coletor.buscar(URL_CALENDARIO.format(skip=skip, inicio=inicio, fim=fim))
        itens = dados.get("items") or []
        total = dados.get("totalItems") or 0
        if not itens:
            break
        torneios.extend(itens)
        skip += len(itens)
    resultado = {"coletado_em": time.time(), "inicio": inicio, "fim": fim, "torneios": torneios}
    _gravar(ARQUIVO_CALENDARIO, resultado)
    return resultado


def baixar_chave(coletor: ColetorITF, chave_torneio: str) -> dict:
    """Estrutura das chaves (masculina e feminina, principal e qualifying)."""
    filtros = coletor.buscar(URL_FILTROS.format(chave=chave_torneio.lower()))
    eventos: dict[str, dict] = {}
    for genero in filtros.get("filters") or []:
        codigo_genero = genero.get("valueCode")
        for evento in genero.get("subFilter") or []:
            fase = {"M": "principal", "Q": "qualifying"}.get(evento.get("valueCode"))
            estruturas = {s.get("valueCode") for s in evento.get("subFilter") or []}
            if not fase or "KO" not in estruturas or codigo_genero not in ("M", "W"):
                continue
            drawsheet = coletor.buscar(URL_DRAWSHEET.format(
                evento=evento["valueCode"], genero=codigo_genero,
                tour=filtros.get("tourType") or "N", id=filtros.get("tournamentId"),
            ))
            estrutura = resultados_itf.estrutura_do_drawsheet(drawsheet)
            if estrutura:
                eventos.setdefault(codigo_genero, {})[fase] = estrutura
    resultado = {"coletado_em": time.time(), "publicada": bool(eventos), "eventos": eventos}
    _gravar(_arquivo_chave(chave_torneio), resultado)
    return resultado


def baixar_atividade(coletor: ColetorITF, player_id: int) -> dict:
    itens, skip, total = [], 0, None
    while total is None or skip < total:
        dados = coletor.buscar(URL_ATIVIDADE.format(id=int(player_id), skip=skip))
        lote = dados.get("items") or []
        total = dados.get("totalItems") or 0
        if not lote:
            break
        itens.extend(lote)
        skip += len(lote)
    resultado = {"coletado_em": time.time(), "itens": itens}
    _gravar(_arquivo_atividade(player_id), resultado)
    return resultado


# ═══════════════════════════════════════════════════════════════════════════════
# TAREFAS (o que o app web dispara em segundo plano)
# ═══════════════════════════════════════════════════════════════════════════════
def atualizar_calendario() -> None:
    with ColetorITF() as coletor:
        baixar_calendario(coletor)


def atualizar_chave(chave_torneio: str) -> None:
    with ColetorITF() as coletor:
        baixar_chave(coletor, chave_torneio)


def atualizar_atividade(player_id: int, genero: str, tabela: dict,
                        data_ref: datetime.date | None = None) -> None:
    """Atividade do atleta + calendario (para a categoria) + as chaves dos
    torneios em que o tamanho muda os pontos (ate MAX_CHAVES_POR_ATUALIZACAO)."""
    data_ref = data_ref or datetime.date.today()
    with ColetorITF() as coletor:
        calendario = ler_calendario()
        if not calendario_fresco(calendario):
            calendario = baixar_calendario(coletor)
        atividade = baixar_atividade(coletor, player_id)

        resultados = resultados_itf.resultados_do_atleta(
            atividade["itens"], tabela, calendario_por_chave(calendario), {}, genero
        )
        inicio_janela = data_ref - datetime.timedelta(weeks=53)
        pendentes = [
            r.chave_torneio for r in resultados
            if r.presumido and r.chave_torneio and r.fim and r.fim >= inicio_janela
            and precisa_buscar_chave(r.chave_torneio)
        ]
        for chave in pendentes[:MAX_CHAVES_POR_ATUALIZACAO]:
            baixar_chave(coletor, chave)


# ═══════════════════════════════════════════════════════════════════════════════
# RANKING DA SEMANA
# ═══════════════════════════════════════════════════════════════════════════════
# A ITF publica um ranking por semana, com data de segunda-feira. Conferir a
# data pede so a primeira pagina; o ranking inteiro (~35 paginas por genero) so
# e baixado quando ela mudou. O arquivo continua o da tierlist original
# (ranking_itf_<genero>.json), que o app de terminal tambem usa.
ARQUIVO_AGENDA_RANKING = PASTA_CACHE / "agenda_ranking.json"


def data_do_ranking_na_itf(coletor: ColetorITF, genero: str) -> str | None:
    """Data do ranking que a ITF mostra agora, no formato salvo ('19 October 2026')."""
    return itf.extrair_rank_date(coletor.buscar(itf.RANKING_API_URL.format(player_type=genero, take=10, skip=0)))


def atualizar_ranking(genero: str) -> str:
    """Baixa o ranking de `genero` se a ITF publicou um novo ou se o salvo
    ficou incompleto. Devolve "em_dia" ou "baixado". Se a ITF parar no meio,
    o que veio fica salvo, a proxima tentativa continua dali e aqui sai erro."""
    with ColetorITF() as coletor:
        salvo = itf.ler_cache(genero) or {}
        publicado = data_do_ranking_na_itf(coletor, genero)
        if publicado and salvo.get("completo") and salvo.get("rank_date") == publicado:
            return "em_dia"
        jogadores = itf.coletar_ranking(coletor.sessao, genero)
    if len(jogadores) < itf.MIN_RANKING_PLAYERS or not (itf.ler_cache(genero) or {}).get("completo"):
        raise ErroColetaITF(f"a ITF parou no meio ({len(jogadores)} jogadores); a próxima tentativa continua dali")
    return "baixado"


def atualizar_rankings(generos: tuple[str, ...] = tuple(itf.PLAYER_TYPE_LABELS)) -> dict[str, str]:
    """Cada genero com um navegador proprio (cada um tem seu limite de sessoes
    novas); um que falhe nao impede o outro."""
    feito, erros = {}, []
    for genero in generos:
        try:
            feito[genero] = atualizar_ranking(genero)
        except Exception as exc:
            erros.append(f"{itf.PLAYER_TYPE_LABELS.get(genero, genero)}: {exc}")
    if erros:
        raise ErroColetaITF("; ".join(erros))
    return feito


def ultima_tentativa_ranking() -> float:
    return (_ler(ARQUIVO_AGENDA_RANKING) or {}).get("tentativa", 0)


def marcar_tentativa_ranking(quando: float, generos) -> None:
    _gravar(ARQUIVO_AGENDA_RANKING, {"tentativa": quando, "generos": list(generos)})
