"""
ITF Beach Tennis — Tierlist de Duplas
======================================
Coleta o ranking de duplas da ITF e cruza com uma lista de duplas inscritas.

O site da ITF fica atras do Incapsula: chamar a API com `requests` devolve
HTML de desafio no lugar do JSON. Por isso a coleta roda dentro de um
Chromium (Playwright), que resolve o desafio ao abrir a pagina e depois
chama a API interna da propria ITF de dentro dela.

Alem da tierlist, o script permite:
  - adicionar duplas fora da lista (antes da coleta e depois da tierlist, sem
    baixar o ranking de novo);
  - destacar duplas em outra cor, por numero;
  - calcular o rank maximo que a parceira precisa ter para voce chegar a uma
    colocacao ou a um tier (meta de colocacao).

Tiers: S e A saem da soma dos ranks (qualidade); B e C saem da posicao — as
primeiras MAIN_DRAW_CUT duplas entram direto, o resto joga qualifying.

Instalacao:
    pip install playwright colorama
    playwright install chromium

Uso:
    python itf_beach_tennis_tierlist.py
"""

import json
import os
import pathlib
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ─── DUPLAS INSCRITAS ────────────────────────────────────────────────────────
# Lista usada quando nada e colado no terminal. Trocar aqui muda o padrao.
DUPLAS = [
(1, "ANA Bruel", "GEHRING Maria Luiza"),
(2, "BALLERINI SIQUEIRA Nicole", "PAROLA Luize"),
(3, "BELO Ana Luiza", "SILVA Maria Fernanda"),
(4, "BELUSSO Ana Luiza", "CAMPANER LIBERATTI Giovana"),
(5, "CAMARGO Isabelli", "MORAIS AMBLARD Maria Luiza"),
(6, "CARDOSO DUARTE Alice", "MOREIRA Flavia"),
(7, "CARNICELLI INOCENTE Maria Eduarda", "CHEROBIN DE OLIVEIRA Renata"),
(8, "CINTRA ARCHETI Manuela", "SILVA DE CARVALHO Juliana"),
(9, "COELHO Manuela", "REIS Mirella"),
(10, "CORREA Juliana", "SCHIER Gabriela"),
(11, "COSTA PREISNER Ana Carolina", "NOGUEIRA Julia"),
(12, "DE NATALI Ana", "ULIANA ALMEIDA Tassia"),
(13, "DE SOUZA NIEHUES Amabile", "NOGUEIRA Laura"),
(14, "ENZ Leticia", "LIMA Tamires"),
(15, "FIRMO Fernanda", "VIEIRA AMORIM Laura"),
(16, "GARCIA Melissa", "SOARES Clarinha"),
(17, "GOMES GIOVINAZZO Lara", "PERROTTI KUHL Carolina"),
(18, "HELMINSKY Amanda", "RIGOTTI MONTEMOR Laura"),
(19, "LOURENCO TRUSZ Isadora", "SELLA Isabella"),
(20, "MASSAKI Laura Yokoyama Massaki", "PAVLAK Maira"),
(21, "MELILLO Alanis", "MELILLO Luana"),
(22, "NOVAIS Clara", "WEILER PRADO Mariana"),
(23, "PADILHA DIAS SILVA Manuela", "THOMPSON Antonia"),
(24, "PAZZOTTI Antonella", "VERONESI DEBONI Flavia"),
(25, "POLTRONIERI Tatiane", "POLTRONIERI Thalia"),
(26, "SCACHETTI Isabela", "SORNAS Bia"),
(27, "TOLEDO CUNHA Vanessa", "WIDHOLZER Mariana"),
]

# Ranking a que a lista fixa acima pertence ("M" masculino / "W" feminino).
# Serve para avisar quando a lista fixa e cruzada com o ranking errado.
DUPLAS_RANKING = "W"

# ─── TIERS ───────────────────────────────────────────────────────────────────
# O topo e por qualidade (soma dos dois rankings) e a base e por chaveamento:
# as primeiras MAIN_DRAW_CUT duplas entram direto no torneio, o resto joga
# qualifying. Por isso B/C sao decididos pela POSICAO, nao pela soma.
LIMITE_ELITE = 200        # Σ ate aqui  → TIER S
LIMITE_ALTO = 600         # Σ ate aqui  → TIER A
LIMITE_SEM_RANKING = 50000  # Σ acima disso → TIER D

TIER_LABELS = {
    "S": "ELITE",
    "A": "ALTO NÍVEL",
    "B": "MAIN DRAW",
    "C": "QUALIFYING",
    "D": "SEM RANKING",
}

# Quantas duplas entram direto no torneio (perguntado a cada execucao).
MAIN_DRAW_CUT_PADRAO = 20

# ─── COLETA ──────────────────────────────────────────────────────────────────
RANKING_PAGE_URL = "https://www.itftennis.com/en/rankings/beach-tennis-tour-rankings/"
RANKING_API_URL = (
    "https://www.itftennis.com/tennis/api/PlayerRankApi/GetPlayerRankings"
    "?circuitCode=BT&playerTypeCode={player_type}&matchTypeCode=D"
    "&ageCategoryCode=&take={take}&skip={skip}&isOrderAscending=true"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
# A API so honra os tamanhos de pagina do dropdown do site (10/25/50/100).
# Qualquer outro valor ela ignora em silencio e devolve 10 — foi o que quebrou
# a coleta antes: take=5000 voltava 200 OK com 10 jogadores e a tierlist inteira
# caia em TIER D. Nao aumente isso sem antes conferir a resposta real da ITF.
TAKE = 100
TAKES_VALIDOS = (10, 25, 50, 100)
MAX_REQUISICOES = 80     # trava de seguranca do loop de paginacao (~8000 jogadores)
PAUSA_ENTRE_PAGINAS_MS = 900  # respiro entre requisicoes; abaixo disso o Incapsula corta
TENTATIVAS_POR_PAGINA = 5     # o Incapsula devolve HTML no lugar do JSON quando irrita
MAX_ROTACOES = 25             # orcamento de sessoes novas para a coleta inteira
ESPERA_INCAPSULA_MS = 4000    # tempo para o Incapsula liberar os cookies
# Sessao nova so nao basta quando o bloqueio ja subiu para o nivel do IP: ai e
# preciso esperar o castigo passar antes de tentar de novo.
BACKOFF_ROTACAO_MS = (5000, 15000, 30000, 60000)

# ─── CACHE EM DISCO ──────────────────────────────────────────────────────────
# O ranking da ITF muda uma vez por semana, mas a coleta custa ~35 requisicoes e
# pode ser cortada no meio. Guardar em disco deixa as reexecucoes instantaneas e
# permite retomar de onde uma coleta interrompida parou.
CACHE_DIR = pathlib.Path(__file__).resolve().parent
CACHE_HORAS = 24
MIN_RANKING_PLAYERS = 10 # abaixo disso a coleta e considerada falha
RANK_SEM_RANKING = 99999 # rank atribuido a quem nao aparece no ranking

# Abaixo desta taxa de duplas encontradas, o resultado e tratado como suspeito.
TAXA_MATCH_MINIMA = 0.30

# Confianca minima do match de nome (0 a 1).
THRESHOLD_MATCH = 0.88

PLAYER_TYPE_LABELS = {"M": "masculino", "W": "feminino"}

# ─── CHAVES POSSIVEIS NO JSON DA ITF ─────────────────────────────────────────
PLAYER_NAME_KEYS = (
    "playerName", "name", "fullName", "playerFullName", "athleteName",
    "displayName", "competitorName", "player",
)
PLAYER_FIRST_NAME_KEYS = ("firstName", "givenName", "playerGivenName", "forename")
PLAYER_LAST_NAME_KEYS = ("lastName", "familyName", "playerFamilyName", "surname")
PLAYER_RANK_KEYS = ("ranking", "rank", "itfRanking", "position", "rankPosition")
PLAYER_POINTS_KEYS = ("points", "pts", "rankingPoints", "totalPoints", "point", "rankPoints")
TOTAL_KEYS = ("total", "totalResults", "totalRecords", "totalCount", "totalItems", "recordCount")


# ═══════════════════════════════════════════════════════════════════════════════
# CORES NO TERMINAL
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    C = {
        "green":   Fore.GREEN,
        "yellow":  Fore.YELLOW,
        "red":     Fore.RED,
        "cyan":    Fore.CYAN,
        "magenta": Fore.MAGENTA,
        "bold":    Style.BRIGHT,
        "reset":   Style.RESET_ALL,
        "dim":     Style.DIM,
    }
except ImportError:
    C = {k: "" for k in
         ["green", "yellow", "red", "cyan", "magenta", "bold", "reset", "dim"]}

# Marcador textual do destaque: sem colorama, C vira tudo string vazia e a cor
# some — o simbolo garante que a dupla destacada continue visivel.
MARCA_DESTAQUE = "►"


def cor(texto, *estilos):
    return "".join(C.get(e, "") for e in estilos) + texto + C["reset"]


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRADA NO TERMINAL
# ═══════════════════════════════════════════════════════════════════════════════
def escolher_ranking_terminal() -> str:
    """Pede o ranking explicitamente — sem padrao, porque escolher errado
    devolve uma tierlist inteira vazia."""
    print(cor("\n--- MENU ---", "cyan", "bold"))
    print("1 - Ranking masculino")
    print("2 - Ranking feminino")

    while True:
        try:
            escolha = input("Qual ranking voce quer buscar? (1 ou 2): ").strip().lower()
        except EOFError:
            print(cor("\nNenhum ranking informado. Rode de novo e escolha 1 ou 2.", "red"))
            sys.exit(1)

        if escolha in ("1", "m", "masc", "masculino", "homem"):
            return "M"
        if escolha in ("2", "f", "fem", "feminino", "mulher", "w", "women"):
            return "W"

        print(cor("Digite 1 para masculino ou 2 para feminino.", "yellow"))


def parse_duplas_texto(texto: str) -> list[tuple[int, str, str]]:
    """Le o formato: numero, jogador 1, jogador 2 — uma linha cada."""
    linhas = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha in ("```", "'''"):
            continue
        if linha.lower() in ("python", "lista", "duplas"):
            continue
        linhas.append(linha)

    duplas = []
    i = 0
    while i < len(linhas):
        numero_texto = linhas[i]
        if not re.fullmatch(r"\d+", numero_texto):
            raise ValueError(
                f"linha {i + 1}: esperado o numero da dupla, mas veio {numero_texto!r}"
            )
        if i + 2 >= len(linhas):
            raise ValueError(f"dupla {numero_texto}: faltou informar os dois jogadores")

        duplas.append((int(numero_texto), linhas[i + 1], linhas[i + 2]))
        i += 3

    return duplas


def ler_duplas_terminal() -> tuple[list[tuple[int, str, str]], bool]:
    """Retorna (duplas, usou_lista_fixa)."""
    print(cor("\n--- LISTA DE DUPLAS ---", "cyan", "bold"))
    print("Cole a lista neste formato, uma linha por item:")
    print("1")
    print("ALMEIDA Ricardo")
    print("NADAL Rafael")
    print("2")
    print("ALVES FRANCA Gustavo")
    print("DUARTE Joao Luiz")
    print()
    print("Quando terminar, aperte Enter em uma linha vazia.")
    print(cor("Se nao colar nada, uso a lista fixa que esta no topo do script.", "dim"))

    linhas = []
    while True:
        try:
            linha = input()
        except EOFError:
            break

        if not linha.strip():
            break
        if linha.strip().lower() in ("fim", "finalizar", "ok"):
            break
        linhas.append(linha)

    if not linhas:
        rotulo = PLAYER_TYPE_LABELS.get(DUPLAS_RANKING, DUPLAS_RANKING)
        print(cor(f"  Usando lista fixa com {len(DUPLAS)} duplas ({rotulo}).", "yellow"))
        return DUPLAS, True

    try:
        duplas = parse_duplas_texto("\n".join(linhas))
    except ValueError as exc:
        print(cor(f"\nErro ao ler a lista: {exc}", "red"))
        print("Confira se o formato esta assim: numero, jogador 1, jogador 2.")
        sys.exit(1)

    print(cor(f"  Lista lida com {len(duplas)} duplas.", "green"))
    return duplas, False


def confirmar_ranking_da_lista_fixa(player_type_code: str) -> None:
    """A lista fixa tem genero definido. Cruzar com o outro ranking nao acha
    ninguem, entao avisa antes de gastar a coleta."""
    if player_type_code == DUPLAS_RANKING:
        return

    escolhido = PLAYER_TYPE_LABELS.get(player_type_code, player_type_code)
    esperado = PLAYER_TYPE_LABELS.get(DUPLAS_RANKING, DUPLAS_RANKING)
    print(cor(
        f"\n  ATENCAO: a lista fixa e de duplas do {esperado}, "
        f"mas voce escolheu o ranking {escolhido}.",
        "red", "bold",
    ))
    print(cor("  Do jeito que esta, nenhuma dupla vai ser encontrada.", "red"))

    try:
        resposta = input("  Continuar mesmo assim? (s/N): ").strip().lower()
    except EOFError:
        resposta = "s"

    if resposta not in ("s", "sim", "y", "yes"):
        print(cor("  Cancelado. Rode de novo e escolha o outro ranking.", "yellow"))
        sys.exit(0)


def perguntar(texto: str, default: str = "") -> str:
    """input() que nao quebra quando a entrada acaba (stdin redirecionado)."""
    try:
        resposta = input(texto).strip()
    except EOFError:
        print()
        return default
    return resposta or default


def escolher_corte_terminal() -> int:
    """Quantas duplas entram no main draw. O resto joga qualifying."""
    print(cor("\n--- CORTE DO MAIN DRAW ---", "cyan", "bold"))
    print(cor("As primeiras N duplas entram direto; o resto joga qualifying.", "dim"))

    while True:
        resposta = perguntar(
            f"Quantas duplas entram direto no main draw? [{MAIN_DRAW_CUT_PADRAO}]: ",
            str(MAIN_DRAW_CUT_PADRAO),
        )
        if re.fullmatch(r"\d+", resposta) and int(resposta) > 0:
            corte = int(resposta)
            print(cor(f"  Corte na {corte}ª posicao.", "green"))
            return corte
        print(cor("Digite um numero inteiro maior que zero.", "yellow"))


def proximo_numero(duplas: list[tuple[int, str, str]]) -> int:
    return max((num for num, _, _ in duplas), default=0) + 1


def adicionar_duplas_terminal(
    duplas: list[tuple[int, str, str]],
    ranking: list[dict] | None = None,
) -> list[int]:
    """Acrescenta duplas que nao estavam na lista. Devolve os numeros criados.

    Quando o ranking ja esta carregado, confere o nome na hora: digitar fora do
    padrao da ITF vira S/R la no fim, e ai o erro ja passou despercebido.
    """
    adicionadas: list[int] = []

    while True:
        resposta = perguntar(
            cor("\nAdicionar uma dupla fora da lista? (s/N): ", "cyan"), "n"
        ).lower()
        if resposta not in ("s", "sim", "y", "yes"):
            break

        numero = proximo_numero(duplas)
        print(cor(f"  Dupla {numero} — formato da ITF: SOBRENOME Nome", "dim"))

        jogador1 = perguntar("  Jogadora 1: ")
        jogador2 = perguntar("  Jogadora 2: ")
        if not jogador1 or not jogador2:
            print(cor("  Faltou um dos nomes. Dupla descartada.", "yellow"))
            continue

        if ranking:
            achou_ambas = True
            for nome in (jogador1, jogador2):
                dados = buscar_jogador_no_ranking(nome, ranking)
                if dados["found"]:
                    print(cor(f"    OK: {nome} -> {dados['nome_itf']} #{dados['rank']}", "green"))
                else:
                    achou_ambas = False
                    print(cor(f"    nao encontrada no ranking: {nome}", "yellow"))

            if not achou_ambas:
                manter = perguntar("    Manter mesmo assim? (S/n): ", "s").lower()
                if manter not in ("s", "sim", "y", "yes"):
                    print(cor("    Dupla descartada.", "dim"))
                    continue

        duplas.append((numero, jogador1, jogador2))
        adicionadas.append(numero)
        print(cor(f"  Dupla {numero} adicionada.", "green"))

    return adicionadas


def parse_numeros(texto: str, validos: set[int]) -> tuple[set[int], list[str]]:
    """Le '3, 7' e devolve (numeros validos, pedacos recusados)."""
    escolhidos: set[int] = set()
    invalidos: list[str] = []

    for pedaco in re.split(r"[,\s]+", texto.strip()):
        if not pedaco:
            continue
        if re.fullmatch(r"\d+", pedaco) and int(pedaco) in validos:
            escolhidos.add(int(pedaco))
        else:
            invalidos.append(pedaco)

    return escolhidos, invalidos


def escolher_destaques_terminal(
    duplas: list[tuple[int, str, str]],
    destaques: set[int],
    adicionadas: list[int] | None = None,
) -> set[int]:
    """Quais duplas sair em cor diferente. Depois de adicionar alguma, o padrao
    do Enter passa a ser justamente a dupla nova."""
    validos = {num for num, _, _ in duplas}

    print(cor("\n--- DESTAQUE ---", "cyan", "bold"))
    if adicionadas:
        lista = ", ".join(str(n) for n in adicionadas)
        print(f"Enter = destacar a(s) dupla(s) adicionada(s) ({lista})")
        print("numero(s) = destacar outra(s), ex: 3, 7   |   n = nenhuma")
        resposta = perguntar("Destacar qual? ", "")
        if not resposta:
            return destaques | set(adicionadas)
    else:
        print(cor("Enter = nenhuma  |  numero(s) = destacar, ex: 3, 7", "dim"))
        resposta = perguntar("Quer destacar alguma dupla? ", "")
        if not resposta:
            return destaques

    if resposta.lower() in ("n", "nao", "não", "nenhuma", "no"):
        return set()

    escolhidos, invalidos = parse_numeros(resposta, validos)
    if invalidos:
        print(cor(f"  Ignorado (nao existe na lista): {', '.join(invalidos)}", "yellow"))
    if not escolhidos:
        return destaques

    print(cor(f"  Destacando: {', '.join(str(n) for n in sorted(escolhidos))}", "magenta"))
    return escolhidos


# ═══════════════════════════════════════════════════════════════════════════════
# NORMALIZAÇÃO DE NOMES (fuzzy match)
# ═══════════════════════════════════════════════════════════════════════════════
PARTICULAS = ("junior", "jr", "sr", "de", "da", "do", "dos", "das")


def normalizar(nome: str) -> str:
    """Sem acento, minusculo, sem particulas, tokens unicos e ordenados —
    para que 'CHEROBIN DE OLIVEIRA Renata' e 'Renata Cherobin de Oliveira'
    virem a mesma string."""
    s = unicodedata.normalize("NFD", nome)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9\s]", " ", s.lower().strip())
    for particula in PARTICULAS:
        s = re.sub(rf"\b{particula}\b", "", s)
    return " ".join(sorted(set(s.split())))


def tokens_nome(nome: str) -> set[str]:
    return set(normalizar(nome).split())


def similaridade(a: str, b: str) -> float:
    a_norm = normalizar(a)
    b_norm = normalizar(b)
    ratio = SequenceMatcher(None, a_norm, b_norm).ratio()

    a_tokens = set(a_norm.split())
    b_tokens = set(b_norm.split())
    if len(a_tokens) >= 2 and len(b_tokens) >= 2:
        inter = a_tokens & b_tokens
        token_score = (len(inter) / len(a_tokens) * 0.7) + (len(inter) / len(b_tokens) * 0.3)
        return max(ratio, token_score)

    return ratio


def avaliar_match_nome(nome_busca: str, nome_itf: str) -> float:
    """
    Match conservador: evita aceitar nomes "parecidos".
    Para nomes curtos, todos os tokens precisam bater; para nomes longos,
    exige quase todos e deixa a similaridade decidir o desempate.
    """
    busca_tokens = tokens_nome(nome_busca)
    itf_tokens = tokens_nome(nome_itf)
    if len(busca_tokens) < 2 or len(itf_tokens) < 2:
        return 0.0

    overlap = busca_tokens & itf_tokens
    if len(busca_tokens) <= 3:
        exigidos = len(busca_tokens)
    else:
        exigidos = max(3, -(-len(busca_tokens) * 8 // 10))  # 80% arredondado pra cima

    if len(overlap) < exigidos:
        return 0.0

    cobertura = len(overlap) / len(busca_tokens)
    precisao = len(overlap) / len(itf_tokens)
    return (cobertura * 0.70) + (precisao * 0.20) + (similaridade(nome_busca, nome_itf) * 0.10)


def encontrar_jogador(nome_busca: str, ranking: list[dict]) -> dict | None:
    """Melhor match acima do threshold, ou None."""
    melhor = None
    melhor_score = 0.0

    for jogador in ranking:
        nome_itf = obter_nome_jogador(jogador)
        if not nome_itf:
            continue
        score = avaliar_match_nome(nome_busca, nome_itf)
        if score > melhor_score:
            melhor_score = score
            melhor = jogador

    return melhor if melhor_score >= THRESHOLD_MATCH else None


# ═══════════════════════════════════════════════════════════════════════════════
# LEITURA DO JSON DA ITF
# ═══════════════════════════════════════════════════════════════════════════════
def primeiro_valor(obj: dict, chaves: tuple[str, ...]):
    """Primeiro valor nao vazio entre as chaves, tolerando caixa diferente
    e um nivel de aninhamento (player/person/competitor/athlete)."""
    if not isinstance(obj, dict):
        return None

    # A copia em minusculas so e montada se a chave exata nao estiver la: no
    # JSON da ITF quase sempre esta, e isto roda para cada jogador do ranking.
    obj_lower = None
    for chave in chaves:
        valor = obj.get(chave)
        if valor in (None, ""):
            if obj_lower is None:
                obj_lower = {str(k).lower(): v for k, v in obj.items()}
            valor = obj_lower.get(chave.lower())
        if valor not in (None, ""):
            return valor

    for chave in ("player", "person", "competitor", "athlete"):
        valor = obj.get(chave)
        if isinstance(valor, dict):
            aninhado = primeiro_valor(valor, chaves)
            if aninhado not in (None, ""):
                return aninhado

    return None


def obter_nome_jogador(jogador: dict) -> str:
    valor = primeiro_valor(jogador, PLAYER_NAME_KEYS)
    if isinstance(valor, dict):
        valor = obter_nome_jogador(valor)
    if isinstance(valor, str) and valor.strip():
        return valor.strip()

    primeiro = primeiro_valor(jogador, PLAYER_FIRST_NAME_KEYS)
    ultimo = primeiro_valor(jogador, PLAYER_LAST_NAME_KEYS)
    return " ".join(str(p).strip() for p in (primeiro, ultimo) if p not in (None, "")).strip()


def obter_campo_escalar(jogador: dict, chaves: tuple[str, ...]):
    valor = primeiro_valor(jogador, chaves)
    return None if isinstance(valor, (dict, list)) else valor


def obter_rank_jogador(jogador: dict):
    return obter_campo_escalar(jogador, PLAYER_RANK_KEYS)


def obter_pontos_jogador(jogador: dict):
    return obter_campo_escalar(jogador, PLAYER_POINTS_KEYS)


def parse_inteiro(valor, default=None):
    if valor in (None, ""):
        return default
    match = re.search(r"\d+", str(valor).replace(",", ""))
    if not match:
        return default
    return int(match.group(0))


def maior_rank(jogadores: list[dict]) -> int | None:
    ranks = [parse_inteiro(obter_rank_jogador(j)) for j in jogadores]
    ranks = [rank for rank in ranks if rank is not None]
    return max(ranks) if ranks else None


def parece_item_ranking(item) -> bool:
    if not isinstance(item, dict):
        return False
    return bool(obter_nome_jogador(item)) and (
        obter_rank_jogador(item) is not None or obter_pontos_jogador(item) is not None
    )


def extrair_jogadores(data) -> list[dict]:
    """Varre o JSON e devolve a maior lista que pareca ser o ranking."""
    candidatos = []

    def walk(node):
        if isinstance(node, list):
            jogadores = [item for item in node if parece_item_ranking(item)]
            if jogadores:
                candidatos.append(jogadores)
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if parece_item_ranking(node):
                candidatos.append([node])
            for valor in node.values():
                walk(valor)

    walk(data)
    return max(candidatos, key=len) if candidatos else []


def extrair_total(data) -> int | None:
    """Total de jogadores informado pela ITF, em qualquer nivel do JSON."""
    chaves_total = {k.lower() for k in TOTAL_KEYS}

    if isinstance(data, dict):
        for chave, valor in data.items():
            if str(chave).lower() in chaves_total:
                total = parse_inteiro(valor)
                if total is not None:
                    return total
        filhos = data.values()
    elif isinstance(data, list):
        filhos = data
    else:
        return None

    for filho in filhos:
        total = extrair_total(filho)
        if total is not None:
            return total

    return None


def chave_jogador(jogador: dict) -> tuple[str, str]:
    return (
        normalizar(obter_nome_jogador(jogador)),
        str(obter_rank_jogador(jogador) or "").strip(),
    )


def adicionar_jogadores(destino: list[dict], jogadores: list[dict], vistos: set) -> int:
    novos = 0
    for jogador in jogadores:
        chave = chave_jogador(jogador)
        if not chave[0] or chave in vistos:
            continue
        destino.append(jogador)
        vistos.add(chave)
        novos += 1
    return novos


# ═══════════════════════════════════════════════════════════════════════════════
# COLETA VIA PLAYWRIGHT
# ═══════════════════════════════════════════════════════════════════════════════
# fetch de dentro da pagina da ITF: reaproveita os cookies do Incapsula que o
# browser ja resolveu ao abrir o site.
FETCH_JS = """
async (url) => {
    const res = await fetch(url, {
        method: "GET",
        credentials: "same-origin",
        headers: {"Accept": "application/json, text/plain, */*"}
    });
    const contentType = res.headers.get("content-type") || "";
    if (!contentType.toLowerCase().includes("json")) {
        const text = await res.text();
        return {ok: res.ok, status: res.status, contentType, text: text.slice(0, 250)};
    }
    return {ok: res.ok, status: res.status, contentType, data: await res.json()};
}
"""


class SessaoITF:
    """Sessao de browser contra a ITF.

    O Incapsula corta a sessao depois de algumas dezenas de requisicoes e passa
    a devolver HTML no lugar do JSON. Recarregar a pagina no mesmo contexto NAO
    resolve (os cookies queimados continuam la); o que resolve e descartar o
    contexto e abrir outro."""

    def __init__(self, browser, player_type_code: str):
        self.browser = browser
        self.player_type_code = player_type_code
        self.ctx = None
        self.page = None
        self.rotacoes = 0
        self._abrir()

    def _abrir(self) -> None:
        self.ctx = self.browser.new_context(
            user_agent=USER_AGENT,
            locale="pt-BR",
            viewport={"width": 1280, "height": 800},
        )
        self.page = self.ctx.new_page()
        self.page.goto(
            f"{RANKING_PAGE_URL}?playerType={self.player_type_code}&matchType=D",
            wait_until="domcontentloaded",
            timeout=90000,
        )
        self.page.wait_for_timeout(ESPERA_INCAPSULA_MS)

    def rotacionar(self, tentativa: int = 0) -> bool:
        """Sessao nova. False quando o orcamento de rotacoes acabou."""
        if self.rotacoes >= MAX_ROTACOES:
            return False
        self.rotacoes += 1
        espera = BACKOFF_ROTACAO_MS[min(tentativa, len(BACKOFF_ROTACAO_MS) - 1)]
        print(cor(
            f"     sessao bloqueada — esperando {espera // 1000}s e abrindo outra "
            f"({self.rotacoes}/{MAX_ROTACOES})",
            "yellow",
        ))
        try:
            self.page.wait_for_timeout(espera)
        except Exception:
            time.sleep(espera / 1000)
        self.fechar()
        try:
            self._abrir()
        except Exception as exc:
            print(cor(f"     falha ao abrir sessao nova: {exc}", "red"))
            return False
        return True

    def fetch(self, url: str) -> dict:
        try:
            return self.page.evaluate(FETCH_JS, url)
        except Exception as exc:
            return {"ok": False, "erro": str(exc).splitlines()[0][:100]}

    def fechar(self) -> None:
        try:
            if self.ctx:
                self.ctx.close()
        except Exception:
            pass


def buscar_pagina(sessao: "SessaoITF", url: str) -> dict | None:
    """Uma pagina do ranking. Se a ITF devolver qualquer coisa que nao seja o
    JSON esperado, abre uma sessao nova e tenta de novo."""
    for tentativa in range(TENTATIVAS_POR_PAGINA):
        resposta = sessao.fetch(url)
        if resposta.get("ok") and "data" in resposta:
            return resposta

        if resposta.get("erro"):
            motivo = resposta["erro"]
        elif resposta.get("ok"):
            motivo = resposta.get("contentType", "?")
        else:
            motivo = f"HTTP {resposta.get('status')}"
        print(cor(f"     resposta invalida ({motivo})", "yellow"))

        if not sessao.rotacionar(tentativa):
            break

    return None


def arquivo_cache(player_type_code: str) -> pathlib.Path:
    return CACHE_DIR / f"ranking_itf_{player_type_code}.json"


def ler_cache(player_type_code: str) -> dict | None:
    caminho = arquivo_cache(player_type_code)
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(dados, dict) or not isinstance(dados.get("jogadores"), list):
        return None
    return dados


def cache_fresco(dados: dict | None) -> bool:
    if not dados or not dados.get("completo"):
        return False
    idade_h = (time.time() - dados.get("coletado_em", 0)) / 3600
    return idade_h < CACHE_HORAS


def gravar_cache(player_type_code: str, jogadores: list[dict],
                 total_esperado: int | None, rank_date, completo: bool) -> None:
    if not jogadores:
        return
    payload = {
        "player_type": player_type_code,
        "coletado_em": time.time(),
        "rank_date":   rank_date,
        "total_itf":   total_esperado,
        "completo":    completo,
        "jogadores":   jogadores,
    }
    # Grava ao lado e troca de uma vez: o app web le este arquivo a qualquer
    # momento e nunca pode pegar o JSON pela metade.
    caminho = arquivo_cache(player_type_code)
    temporario = caminho.with_suffix(".tmp")
    try:
        temporario.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporario, caminho)
    except Exception as exc:
        print(cor(f"  ⚠ Nao consegui gravar o cache: {exc}", "yellow"))


def extrair_rank_date(data) -> str | None:
    if isinstance(data, dict):
        for chave, valor in data.items():
            if str(chave).lower() == "rankdate" and valor:
                return str(valor)
        for valor in data.values():
            achado = extrair_rank_date(valor)
            if achado:
                return achado
    elif isinstance(data, list):
        for item in data:
            achado = extrair_rank_date(item)
            if achado:
                return achado
    return None


def coletar_ranking(sessao: "SessaoITF", player_type_code: str) -> list[dict]:
    jogadores: list[dict] = []
    vistos: set = set()
    total_esperado = None
    rank_date = None
    recebidos = 0          # itens brutos ja devolvidos pela ITF = proximo skip
    fim_da_lista = False   # percorremos o ranking inteiro (com ou sem repetidos)
    parcial = ler_cache(player_type_code)

    if TAKE not in TAKES_VALIDOS:
        print(cor(
            f"  ⚠ TAKE={TAKE} nao esta em {TAKES_VALIDOS}; a ITF vai devolver 10 por pagina.",
            "yellow",
        ))

    for _ in range(MAX_REQUISICOES):
        url = RANKING_API_URL.format(player_type=player_type_code, take=TAKE, skip=recebidos)

        print(f"  → take={TAKE} skip={recebidos}")
        resposta = buscar_pagina(sessao, url)
        if resposta is None:
            print(cor("     desisti desta pagina apos as retentativas.", "red"))
            break

        players = extrair_jogadores(resposta["data"])
        total = extrair_total(resposta["data"])
        if total is not None and total >= len(players):
            total_esperado = max(total_esperado or 0, total)
        rank_date = rank_date or extrair_rank_date(resposta["data"])

        if not players:
            break

        # Retomada: se uma coleta anterior parou no meio e o ranking ainda e o
        # da mesma semana, aproveita o que ja esta em disco e pula pra frente.
        if parcial is not None:
            ja_salvos = parcial.get("jogadores") or []
            if rank_date and parcial.get("rank_date") == rank_date and len(ja_salvos) > len(players):
                print(cor(
                    f"     retomando coleta anterior ({len(ja_salvos)} jogadores em cache)",
                    "cyan",
                ))
                adicionar_jogadores(jogadores, ja_salvos, vistos)
                recebidos = max(recebidos, len(jogadores))
            parcial = None

        # A ITF as vezes devolve menos que o pedido. Isso NAO significa fim da
        # lista: o skip tem que andar pelo que ela realmente mandou, senao a
        # pagina seguinte repete o mesmo bloco (ou pula jogadores).
        novos = adicionar_jogadores(jogadores, players, vistos)
        recebidos += len(players)
        total_txt = f" | total ITF {total_esperado}" if total_esperado else ""
        print(f"     +{novos} novos ({len(jogadores)} acumulados){total_txt}")

        if total_esperado and recebidos >= total_esperado:
            fim_da_lista = True
            break
        if novos == 0:
            # so repetidos e ainda ha lista pela frente: a ITF esta devolvendo o
            # mesmo bloco, insistir nao adianta.
            break

        sessao.page.wait_for_timeout(PAUSA_ENTRE_PAGINAS_MS)

    gravar_cache(player_type_code, jogadores, total_esperado, rank_date, fim_da_lista)

    if not fim_da_lista:
        print(cor(
            f"  ⚠ Coleta incompleta: {len(jogadores)} de {total_esperado or '?'} jogadores. "
            "Duplas de rank mais baixo podem aparecer como S/R.",
            "yellow", "bold",
        ))
        print(cor(
            "    O que ja veio ficou salvo em "
            f"{arquivo_cache(player_type_code).name} — rodar de novo retoma daqui.",
            "dim",
        ))
    elif total_esperado and len(jogadores) < total_esperado:
        # A cauda do ranking tem centenas de empates no mesmo rank e a ITF
        # repete jogadores entre as paginas. O ranking foi percorrido inteiro.
        print(cor(
            f"  ({total_esperado - len(jogadores)} linhas repetidas pela ITF na cauda do "
            "ranking foram descartadas)",
            "dim",
        ))

    return jogadores


def buscar_ranking_itf(player_type_code: str) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(cor("\n[!] Playwright nao instalado.", "red"))
        print("    Execute:  pip install playwright && playwright install chromium")
        return []

    rotulo = PLAYER_TYPE_LABELS.get(player_type_code, player_type_code)

    cache = ler_cache(player_type_code)
    if cache_fresco(cache):
        idade_h = (time.time() - cache["coletado_em"]) / 3600
        print(cor(
            f"\nUsando o ranking {rotulo} em cache "
            f"({len(cache['jogadores'])} jogadores, {idade_h:.1f}h, "
            f"ranking de {cache.get('rank_date') or '?'}).",
            "green", "bold",
        ))
        print(cor(f"Para forcar coleta nova, apague {arquivo_cache(player_type_code).name}.", "dim"))
        return cache["jogadores"]

    print(cor(f"\nBaixando o ranking {rotulo} da ITF (browser headless)...", "cyan", "bold"))
    print(cor("Sao ~35 requisicoes; pode levar 1-3 minutos.", "dim"))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            print("  → Abrindo a pagina da ITF...")
            sessao = SessaoITF(browser, player_type_code)
            try:
                return coletar_ranking(sessao, player_type_code)
            finally:
                sessao.fechar()
        finally:
            browser.close()


# ═══════════════════════════════════════════════════════════════════════════════
# TIERLIST
# ═══════════════════════════════════════════════════════════════════════════════
# O fuzzy match varre o ranking inteiro (milhares de jogadoras) por nome. Como a
# tierlist e remontada a cada dupla adicionada, o resultado fica em cache.
_CACHE_MATCH: dict[str, dict] = {}


def buscar_jogador_no_ranking(nome: str, ranking: list[dict]) -> dict:
    if nome in _CACHE_MATCH:
        return _CACHE_MATCH[nome]

    jogador = encontrar_jogador(nome, ranking)
    if not jogador:
        resultado = {"found": False, "rank": None, "points": 0, "nome_itf": None}
    else:
        resultado = {
            "found":    True,
            "rank":     parse_inteiro(obter_rank_jogador(jogador)),
            "points":   parse_inteiro(obter_pontos_jogador(jogador), 0),
            "nome_itf": obter_nome_jogador(jogador) or "?",
        }

    _CACHE_MATCH[nome] = resultado
    return resultado


def get_tier(rank_sum: int, posicao: int, corte: int) -> tuple[str, str]:
    """S e A saem da soma dos ranks (qualidade); B e C saem da posicao na lista
    (quem entra direto no torneio e quem cai no qualifying)."""
    if rank_sum > LIMITE_SEM_RANKING:
        return "D", TIER_LABELS["D"]
    if rank_sum <= LIMITE_ELITE:
        return "S", TIER_LABELS["S"]
    if rank_sum <= LIMITE_ALTO:
        return "A", TIER_LABELS["A"]
    if posicao <= corte:
        return "B", TIER_LABELS["B"]
    return "C", TIER_LABELS["C"]


def montar_tierlist(
    ranking: list[dict],
    duplas: list[tuple[int, str, str]],
    destaques: set[int] | None = None,
) -> list[dict]:
    resultados = []
    destaques = destaques or set()

    print(cor("\n─── Cruzando duplas com o ranking ───", "cyan"))
    for num, p1, p2 in duplas:
        d1 = buscar_jogador_no_ranking(p1, ranking)
        d2 = buscar_jogador_no_ranking(p2, ranking)

        r1 = d1["rank"] or RANK_SEM_RANKING
        r2 = d2["rank"] or RANK_SEM_RANKING

        status_p1 = cor(f"#{d1['rank']}", "green") if d1["rank"] else cor("S/R", "dim")
        status_p2 = cor(f"#{d2['rank']}", "green") if d2["rank"] else cor("S/R", "dim")
        nome_itf_1 = f" -> {d1['nome_itf'][:24]}" if d1["found"] else ""
        nome_itf_2 = f" -> {d2['nome_itf'][:24]}" if d2["found"] else ""
        marca = cor(MARCA_DESTAQUE, "magenta", "bold") if num in destaques else " "
        rotulo = f"Dupla {num:>2}:"
        if num in destaques:
            rotulo = cor(rotulo, "magenta", "bold")
        print(
            f" {marca}{rotulo} {p1[:30]:<30} {status_p1}{nome_itf_1}"
            f"  |  {p2[:30]:<30} {status_p2}{nome_itf_2}"
        )

        resultados.append({
            "num":       num,
            "p1":        p1,
            "p2":        p2,
            "r1":        d1["rank"],
            "r2":        d2["rank"],
            "nome_itf1": d1["nome_itf"],
            "nome_itf2": d2["nome_itf"],
            "pts1":      d1["points"],
            "pts2":      d2["points"],
            "rank_sum":  r1 + r2,
            "both":      d1["found"] and d2["found"],
            "any":       d1["found"] or d2["found"],
        })

    # ambos ranqueados primeiro (menor soma = melhor), depois um, depois nenhum
    resultados.sort(key=lambda x: (
        0 if x["both"] else (1 if x["any"] else 2),
        x["rank_sum"],
    ))
    return resultados


def descricao_tier(letra: str, corte: int) -> str:
    """Faixa de cada tier, pra tabela nao virar letra solta sem criterio."""
    return {
        "S": f"(Σ≤{LIMITE_ELITE})",
        "A": f"(Σ≤{LIMITE_ALTO})",
        "B": f"(até a {corte}ª)",
        "C": f"({corte + 1}ª+)",
        "D": "",
    }.get(letra, "")


def exibir_tierlist(
    resultados: list[dict],
    corte: int,
    destaques: set[int] | None = None,
    adicionadas: set[int] | None = None,
):
    destaques = destaques or set()
    adicionadas = adicionadas or set()

    print(cor("\n" + "═" * 62, "bold"))
    print(cor("  🏖  TIERLIST BEACH TENNIS — RANKING ITF  🏖", "bold", "cyan"))
    print(cor("═" * 62, "bold"))

    TIER_CORES = {"S": "yellow", "A": "cyan", "B": "green", "C": "dim", "D": "dim"}
    tier_atual = None

    for pos, r in enumerate(resultados, start=1):
        tier_letra, tier_label = get_tier(r["rank_sum"], pos, corte)
        if tier_letra != tier_atual:
            tier_atual = tier_letra
            faixa = descricao_tier(tier_letra, corte)
            print(cor(
                f"\n  ── TIER {tier_letra}  {tier_label} {faixa} ──",
                TIER_CORES.get(tier_letra, "reset"), "bold",
            ))

        soma = r["rank_sum"] if r["rank_sum"] < RANK_SEM_RANKING else None
        r1_str = f"#{r['r1']}" if r["r1"] else "S/R"
        r2_str = f"#{r['r2']}" if r["r2"] else "S/R"
        pts_total = r["pts1"] + r["pts2"]

        # S ou A que caiu depois do corte continua sendo qualifying: a letra vem
        # da qualidade, entao o aviso tem que vir escrito.
        sufixo = ""
        if tier_letra in ("S", "A") and pos > corte:
            sufixo += cor("  qualy", "yellow")
        if r["num"] in adicionadas:
            sufixo += cor("  (nova)", "magenta")

        linha = (
            f"{pos:>2}º  "
            f"[{r['num']:>2}]  "
            f"{r['p1'][:26]:<26} ({r1_str:>6})  "
            f"{r['p2'][:26]:<26} ({r2_str:>6})  "
            f"Σ={str(soma) if soma else '—':>6}  "
            f"{f'{pts_total} pts' if pts_total > 0 else '—'}"
        )

        if r["num"] in destaques:
            print(f" {cor(MARCA_DESTAQUE, 'magenta', 'bold')}{cor(linha, 'magenta', 'bold')}{sufixo}")
        else:
            print(f"  {linha}{sufixo}")

    print(cor("\n" + "═" * 62, "bold"))
    encontrados = sum(1 for r in resultados if r["any"])
    print(cor(
        f"  {encontrados}/{len(resultados)} duplas com pelo menos um jogador no ranking ITF",
        "dim",
    ))
    if len(resultados) > corte:
        print(cor(
            f"  {corte} primeiras entram direto | "
            f"{len(resultados) - corte} no qualifying",
            "dim",
        ))
    print()


def avisar_matches_baixos(resultados: list[dict], player_type_code: str) -> bool:
    """Sem isso, escolher o ranking errado gera uma tierlist inteira em TIER D
    sem nenhum sinal de que deu errado. Retorna True se o resultado e suspeito."""
    if not resultados:
        return False

    encontrados = sum(1 for r in resultados if r["any"])
    if encontrados / len(resultados) >= TAXA_MATCH_MINIMA:
        return False

    outro = "W" if player_type_code == "M" else "M"
    escolhido = PLAYER_TYPE_LABELS.get(player_type_code, player_type_code)
    alternativo = PLAYER_TYPE_LABELS.get(outro, outro)

    print(cor("  " + "!" * 58, "red", "bold"))
    print(cor(
        f"  SO {encontrados} DE {len(resultados)} DUPLAS FORAM ENCONTRADAS "
        f"NO RANKING {escolhido.upper()}.",
        "red", "bold",
    ))
    print(cor("  A tierlist acima nao vale muita coisa. Causas provaveis:", "red"))
    print(cor(f"    - ranking errado: tente o {alternativo}", "red"))
    print(cor("    - nomes escritos diferente da ITF (confira acentos e sobrenomes)", "red"))
    print(cor("  " + "!" * 58, "red", "bold"))
    print()
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# META DE COLOCAÇÃO — qual rank a parceira precisa ter
# ═══════════════════════════════════════════════════════════════════════════════
def identificar_jogadora(ranking: list[dict]) -> tuple[str, int] | None:
    """Devolve (nome, rank). Tenta achar no ranking da ITF; se nao achar, aceita
    o numero digitado na mao — serve pra quem esta S/R ou escreve o nome
    diferente da ITF."""
    nome = perguntar(cor("\n  Seu nome (como aparece na ITF): ", "cyan"))
    if not nome:
        print(cor("  Sem nome, nao da pra calcular.", "yellow"))
        return None

    dados = buscar_jogador_no_ranking(nome, ranking)
    if dados["found"] and dados["rank"]:
        print(cor(f"  Encontrada: {dados['nome_itf']} — #{dados['rank']}", "green"))
        return nome, dados["rank"]

    print(cor(f"  '{nome}' nao foi encontrada no ranking.", "yellow"))
    resposta = perguntar("  Digite seu rank atual (numero, ou Enter pra desistir): ")
    if not re.fullmatch(r"\d+", resposta):
        return None

    return nome, int(resposta)


def somas_das_outras(resultados: list[dict], meu_nome: str) -> tuple[list[int], list[dict]]:
    """Σ das demais duplas, em ordem. A dupla em que voce ja esta sai da conta —
    senao voce disputa a vaga contra voce mesma e a meta sai errada."""
    minhas = [
        r for r in resultados
        if avaliar_match_nome(meu_nome, r["p1"]) >= THRESHOLD_MATCH
        or avaliar_match_nome(meu_nome, r["p2"]) >= THRESHOLD_MATCH
    ]
    minhas_nums = {r["num"] for r in minhas}
    somas = sorted(r["rank_sum"] for r in resultados if r["num"] not in minhas_nums)
    return somas, minhas


def posicao_da_soma(soma: int, somas: list[int]) -> int:
    """Onde uma dupla com essa Σ entraria na lista das outras."""
    return sum(1 for s in somas if s < soma) + 1


def rank_para_posicao(meu_rank: int, somas: list[int], alvo: int) -> dict:
    """Rank maximo da parceira pra chegar na posicao alvo.

    Pra ocupar a posicao N, a Σ precisa ser menor que a da dupla que esta em N
    hoje (ela e empurrada pra baixo) e maior que a da dupla em N-1.
    """
    teto_soma = somas[alvo - 1] if alvo - 1 < len(somas) else None
    piso_soma = somas[alvo - 2] if 2 <= alvo <= len(somas) + 1 else None

    # "alvo ou melhor": so o teto importa.
    if teto_soma is None:
        max_parceira = None           # a lista e menor que o alvo: qualquer uma serve
    else:
        max_parceira = teto_soma - 1 - meu_rank

    min_parceira = 1 if piso_soma is None else max(1, piso_soma + 1 - meu_rank)

    melhor_soma_possivel = meu_rank + 1   # se a parceira fosse a #1 do mundo
    return {
        "alvo":                 alvo,
        "meu_rank":             meu_rank,
        "soma_a_bater":         teto_soma,
        "max_parceira":         max_parceira,
        "min_parceira":         min_parceira,
        "possivel":             max_parceira is None or max_parceira >= 1,
        "melhor_posicao_possivel": posicao_da_soma(melhor_soma_possivel, somas),
    }


def rank_para_soma(meu_rank: int, limite_soma: int) -> int:
    """Rank maximo da parceira pra Σ ficar dentro de um limite fixo (tiers S/A)."""
    return limite_soma - meu_rank


def exibir_meta(meta: dict, corte: int, somas: list[int]):
    alvo = meta["alvo"]
    meu_rank = meta["meu_rank"]

    print(cor(f"\n  → Para terminar em {alvo}º ou melhor:", "bold"))

    if meta["max_parceira"] is None:
        print(cor(
            f"     a lista tem so {len(somas)} outras duplas — "
            f"qualquer parceira te coloca em {alvo}º ou melhor.", "green",
        ))
        return

    if not meta["possivel"]:
        print(cor(
            f"     impossivel com o seu #{meu_rank}: mesmo com a #1 do mundo "
            f"a Σ seria {meu_rank + 1}, e a vaga exige Σ ≤ {meta['soma_a_bater'] - 1}.",
            "red",
        ))
        print(cor(
            f"     com a #1 voce chegaria em {meta['melhor_posicao_possivel']}º. "
            f"Pra mirar em {alvo}º, seu rank teria que ser "
            f"≤ #{meta['soma_a_bater'] - 2}.",
            "yellow",
        ))
        return

    print(cor(
        f"     parceira precisa ser #{meta['max_parceira']} ou melhor  "
        f"(Σ ≤ {meta['soma_a_bater'] - 1}, batendo a dupla de Σ={meta['soma_a_bater']})",
        "green", "bold",
    ))

    if meta["min_parceira"] > 1:
        print(cor(
            f"  → Para terminar exatamente em {alvo}º: "
            f"parceira entre #{meta['min_parceira']} e #{meta['max_parceira']} "
            f"(parceira melhor que #{meta['min_parceira']} te joga pra cima, "
            f"o que nao e problema).",
            "dim",
        ))


def meta_terminal(resultados: list[dict], ranking: list[dict], corte: int) -> dict | None:
    """Pergunta a colocacao pretendida e devolve o rank que a parceira precisa."""
    print(cor("\n--- META DE COLOCAÇÃO ---", "cyan", "bold"))
    print(cor(
        "Posicao e dentro desta lista de inscritas, nao o ranking da ITF.", "dim"
    ))

    identificacao = identificar_jogadora(ranking)
    if not identificacao:
        return None

    meu_nome, meu_rank = identificacao
    somas, minhas = somas_das_outras(resultados, meu_nome)

    for r in minhas:
        print(cor(
            f"  (sua dupla atual [{r['num']}] {r['p1']} / {r['p2']} "
            f"saiu da comparacao)", "dim",
        ))

    if not somas:
        print(cor("  Nao sobrou nenhuma outra dupla pra comparar.", "yellow"))
        return None

    alvo_texto = perguntar(
        cor(f"\n  Em que posicao voce quer chegar? [{corte}]: ", "cyan"), str(corte)
    )
    if not re.fullmatch(r"\d+", alvo_texto) or int(alvo_texto) < 1:
        print(cor("  Posicao invalida.", "yellow"))
        return None

    alvo = int(alvo_texto)
    meta = rank_para_posicao(meu_rank, somas, alvo)
    exibir_meta(meta, corte, somas)

    # A meta por tier nao depende de quem mais se inscreveu (S e A sao Σ fixa),
    # entao vale como referencia estavel entre torneios.
    print(cor("\n  → Por tier:", "bold"))
    metas_tier = {}
    for letra, limite in (("S", LIMITE_ELITE), ("A", LIMITE_ALTO)):
        teto = rank_para_soma(meu_rank, limite)
        metas_tier[letra] = teto
        if teto >= 1:
            print(f"     TIER {letra} {TIER_LABELS[letra]:<11} (Σ≤{limite}): "
                  + cor(f"parceira #{teto} ou melhor", "green"))
        else:
            print(cor(
                f"     TIER {letra} {TIER_LABELS[letra]:<11} (Σ≤{limite}): "
                f"fora de alcance com o seu #{meu_rank}", "dim",
            ))

    meta_main_draw = rank_para_posicao(meu_rank, somas, corte)
    metas_tier["B"] = meta_main_draw["max_parceira"]
    if meta_main_draw["max_parceira"] is None:
        print(f"     TIER B {TIER_LABELS['B']:<11} (até a {corte}ª): "
              + cor("a lista ainda nao enche o main draw — voce entra direto", "green"))
    elif meta_main_draw["possivel"]:
        print(f"     TIER B {TIER_LABELS['B']:<11} (até a {corte}ª): "
              + cor(f"parceira #{meta_main_draw['max_parceira']} ou melhor", "green")
              + cor("  ← evita o qualifying", "dim"))
    else:
        print(cor(
            f"     TIER B {TIER_LABELS['B']:<11} (até a {corte}ª): "
            f"impossivel com o seu #{meu_rank} — cairia no qualifying", "red",
        ))

    print()
    return {
        "jogadora":            meu_nome,
        "rank":                meu_rank,
        "posicao_alvo":        alvo,
        "soma_a_bater":        meta["soma_a_bater"],
        "rank_maximo_parceira": meta["max_parceira"],
        "rank_minimo_parceira": meta["min_parceira"],
        "possivel":            meta["possivel"],
        "corte_main_draw":     corte,
        "por_tier":            metas_tier,
        "duplas_comparadas":   len(somas),
    }


def salvar_json(
    resultados: list[dict],
    ranking: list[dict],
    player_type_code: str,
    suspeito: bool,
    corte: int,
    adicionadas: set[int] | None = None,
    destaques: set[int] | None = None,
    meta: dict | None = None,
):
    adicionadas = adicionadas or set()
    destaques = destaques or set()

    output = {
        "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ranking": PLAYER_TYPE_LABELS.get(player_type_code, player_type_code),
        "player_type_code": player_type_code,
        "total_duplas": len(resultados),
        "duplas_encontradas": sum(1 for r in resultados if r["any"]),
        "resultado_suspeito": suspeito,
        "total_no_ranking_itf": len(ranking),
        "maior_rank_carregado": maior_rank(ranking),
        "corte_main_draw": corte,
        "duplas_adicionadas": sorted(adicionadas),
        "duplas_destacadas": sorted(destaques),
        "criterio_tiers": {
            "S": f"soma dos ranks <= {LIMITE_ELITE}",
            "A": f"soma dos ranks <= {LIMITE_ALTO}",
            "B": f"posicao <= {corte} (entra direto no torneio)",
            "C": f"posicao > {corte} (joga qualifying)",
            "D": f"soma dos ranks > {LIMITE_SEM_RANKING} (sem ranking)",
        },
        "meta_colocacao": meta,
        "tierlist": [
            {
                "posicao":   i + 1,
                "dupla_num": r["num"],
                "jogador1":  {"nome": r["p1"], "nome_itf": r["nome_itf1"], "rank": r["r1"], "pts": r["pts1"]},
                "jogador2":  {"nome": r["p2"], "nome_itf": r["nome_itf2"], "rank": r["r2"], "pts": r["pts2"]},
                "rank_soma": r["rank_sum"] if r["rank_sum"] < RANK_SEM_RANKING else None,
                "tier":      get_tier(r["rank_sum"], i + 1, corte)[0],
                "main_draw": (i + 1) <= corte,
                "adicionada": r["num"] in adicionadas,
            }
            for i, r in enumerate(resultados)
        ],
    }

    fname = "tierlist_resultado.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(cor(f"  ✓ Resultado salvo em: {fname}", "green"))


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    print(cor("╔══════════════════════════════════════════════════════════╗", "bold"))
    print(cor("║  ITF Beach Tennis — Scraper + Tierlist de Duplas        ║", "bold"))
    print(cor("╚══════════════════════════════════════════════════════════╝", "bold"))

    player_type_code = escolher_ranking_terminal()
    duplas, usou_lista_fixa = ler_duplas_terminal()
    if usou_lista_fixa:
        confirmar_ranking_da_lista_fixa(player_type_code)

    corte = escolher_corte_terminal()

    # Antes da coleta: as duplas extras entram junto e ja saem na tierlist.
    adicionadas = set(adicionar_duplas_terminal(duplas))
    destaques = escolher_destaques_terminal(duplas, set(), sorted(adicionadas))

    ranking = buscar_ranking_itf(player_type_code)

    if len(ranking) < MIN_RANKING_PLAYERS:
        print(cor(
            "\n✗ Nao foi possivel obter o ranking da ITF.\n"
            "\nO que checar:\n"
            "  1. Playwright instalado:  pip install playwright && playwright install chromium\n"
            "  2. Conexao / proxy — a ITF fica atras do Incapsula\n"
            "  3. Se a ITF mudou a API: Chrome → F12 → Network → Fetch/XHR na pagina\n"
            f"     {RANKING_PAGE_URL}\n"
            "     e atualize RANKING_API_URL no topo deste script\n",
            "red",
        ))
        sys.exit(1)

    extra = f" ate rank #{maior_rank(ranking)}" if maior_rank(ranking) else ""
    print(cor(f"\n✓ {len(ranking)} jogadores carregados do ranking ITF{extra}.", "green", "bold"))

    resultados = montar_tierlist(ranking, duplas, destaques)
    exibir_tierlist(resultados, corte, destaques, adicionadas)
    suspeito = avisar_matches_baixos(resultados, player_type_code)

    # Depois da tierlist: o ranking ja esta na memoria, entao adicionar dupla e
    # recalcular e instantaneo — nao abre o browser de novo.
    meta = None
    while True:
        print(cor("\n--- E AGORA? ---", "cyan", "bold"))
        print("1 - Adicionar dupla e recalcular")
        print("2 - Calcular meta de colocacao (rank minimo da parceira)")
        print("3 - Destacar outra dupla")
        print("4 - Salvar e sair")

        escolha = perguntar("Opcao [4]: ", "4")

        if escolha == "1":
            novas = adicionar_duplas_terminal(duplas, ranking)
            if not novas:
                continue
            adicionadas |= set(novas)
            destaques = escolher_destaques_terminal(duplas, destaques, novas)
            resultados = montar_tierlist(ranking, duplas, destaques)
            exibir_tierlist(resultados, corte, destaques, adicionadas)
            suspeito = avisar_matches_baixos(resultados, player_type_code)
        elif escolha == "2":
            meta = meta_terminal(resultados, ranking, corte) or meta
        elif escolha == "3":
            destaques = escolher_destaques_terminal(duplas, destaques)
            exibir_tierlist(resultados, corte, destaques, adicionadas)
        elif escolha in ("4", "sair", "s", "q"):
            break
        else:
            print(cor("Digite 1, 2, 3 ou 4.", "yellow"))

    salvar_json(
        resultados, ranking, player_type_code, suspeito,
        corte, adicionadas, destaques, meta,
    )


if __name__ == "__main__":
    main()
