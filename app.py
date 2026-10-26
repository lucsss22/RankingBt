"""
ITF Beach Tennis — app do atleta (terminal)
===========================================
Ponto de entrada novo. Junta a tierlist de duplas, que continua igual, com:
  - cadastro e login de atletas (atletas.py);
  - pontos por rodada de cada categoria de torneio (pontuacao.py);
  - estimativa de ranking por colocacao ou por pontos (estimativa.py);
  - historico de resultados do atleta.

Aqui so tem a conversa com o usuario. A logica fica nos modulos, que a
interface grafica vai reaproveitar.

Uso:
    python app.py
"""

import datetime
import getpass
import re
import sys
import time

import atletas
import estimativa
import itf_beach_tennis_tierlist as itf
import pontuacao
from itf_beach_tennis_tierlist import cor

SEM_PONTOS = "sem_pontos"   # opcao "parei numa rodada que nao vale pontos"
LARGURA = 62


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRADA NO TERMINAL
# ═══════════════════════════════════════════════════════════════════════════════
class EntradaEncerrada(Exception):
    """stdin acabou (pipe/arquivo). Encerra o app em vez de girar nos menus."""


def perguntar(texto: str, default: str = "") -> str:
    # O perguntar() da tierlist devolve o default quando a entrada acaba. Nos
    # menus em loop daqui isso vira laco infinito, entao aqui EOF encerra.
    try:
        resposta = input(texto).strip()
    except EOFError:
        print()
        raise EntradaEncerrada from None
    return resposta or default


def sim(resposta: str) -> bool:
    return resposta.strip().lower() in ("s", "sim", "y", "yes")


def ler_senha(texto: str) -> str:
    """Sem eco no terminal. Com a entrada redirecionada o getpass trava no
    Windows (le do console, nao do stdin), entao cai para o input."""
    try:
        if sys.stdin.isatty():
            return getpass.getpass(texto)
        return input(texto)
    except EOFError:
        print()
        raise EntradaEncerrada from None


def perguntar_inteiro(texto: str, minimo: int = 0) -> int | None:
    """Enter vazio devolve None (cancela ou pula)."""
    while True:
        resposta = perguntar(texto)
        if not resposta:
            return None
        if re.fullmatch(r"\d+", resposta) and int(resposta) >= minimo:
            return int(resposta)
        print(cor(f"Digite um numero inteiro a partir de {minimo}, ou Enter para cancelar.", "yellow"))


def escolher(titulo: str, opcoes: list[tuple[str, str]], voltar: str = "Voltar") -> str | None:
    """Menu numerado. Devolve a chave da opcao escolhida, ou None (0)."""
    print(cor(f"\n--- {titulo} ---", "cyan", "bold"))
    for i, (_, rotulo) in enumerate(opcoes, start=1):
        print(f"{i} - {rotulo}")
    print(cor(f"0 - {voltar}", "dim"))

    while True:
        resposta = perguntar("Opcao: ")
        if resposta == "0":
            return None
        if re.fullmatch(r"\d+", resposta) and 1 <= int(resposta) <= len(opcoes):
            return opcoes[int(resposta) - 1][0]
        print(cor(f"Digite um numero de 0 a {len(opcoes)}.", "yellow"))


def titulo(texto: str) -> None:
    print(cor("\n" + "═" * LARGURA, "bold"))
    print(cor(f"  {texto}", "bold", "cyan"))
    print(cor("═" * LARGURA, "bold"))


def mostrar_erros(exc: atletas.ErroValidacao) -> None:
    for mensagem in exc.erros.values():
        print(cor(f"  ✗ {mensagem}", "red"))


def formatar_rank(rank: int | None) -> str:
    return f"#{rank}" if rank else "sem ranking"


# ═══════════════════════════════════════════════════════════════════════════════
# RANKING ITF (cache da tierlist)
# ═══════════════════════════════════════════════════════════════════════════════
def carregar_ranking(genero: str) -> tuple[list[dict], dict]:
    """Ranking do genero do atleta. Usa o cache da tierlist mesmo velho —
    baixar de novo leva minutos — e so baixa se o atleta pedir ou se nao
    houver cache nenhum."""
    rotulo = itf.PLAYER_TYPE_LABELS.get(genero, genero)
    cache = itf.ler_cache(genero)

    if cache and cache["jogadores"] and not itf.cache_fresco(cache):
        dias = (time.time() - cache.get("coletado_em", 0)) / 86400
        print(cor(
            f"\n  Ranking {rotulo} salvo: ranking de {cache.get('rank_date') or '?'}, "
            f"baixado ha {dias:.0f} dia(s).",
            "dim",
        ))
        if not sim(perguntar("  Baixar o ranking atualizado da ITF? Leva 1-3 min (s/N): ", "n")):
            return cache["jogadores"], cache

    jogadores = itf.buscar_ranking_itf(genero)
    if len(jogadores) >= itf.MIN_RANKING_PLAYERS:
        return jogadores, itf.ler_cache(genero) or {}

    if cache and cache["jogadores"]:
        print(cor("  Nao consegui baixar o ranking; sigo com o que estava salvo.", "yellow"))
        return cache["jogadores"], cache
    return [], {}


def confirmar_jogador(jogador: dict) -> bool:
    nome = itf.obter_nome_jogador(jogador)
    rank = itf.parse_inteiro(itf.obter_rank_jogador(jogador))
    pontos = itf.parse_inteiro(itf.obter_pontos_jogador(jogador), 0)
    pais = jogador.get("playerNationalityCode") or "?"
    nascimento = jogador.get("birthYear") or "?"
    print(cor(
        f"\n  Encontrei: {nome} ({pais}, nascido em {nascimento}) — "
        f"{formatar_rank(rank)}, {pontos} pts",
        "green",
    ))
    return sim(perguntar("  E voce? (S/n): ", "s"))


def vincular(conn, atleta: atletas.Atleta, jogador: dict) -> atletas.Atleta:
    try:
        atleta = atletas.vincular_itf(
            conn, atleta.id, jogador["playerId"], itf.obter_nome_jogador(jogador)
        )
        print(cor("  ✓ Conta vinculada ao seu cadastro na ITF.", "green"))
    except atletas.ErroValidacao as exc:
        mostrar_erros(exc)
    return atleta


def procurar_e_vincular(conn, atleta: atletas.Atleta,
                        ranking: list[dict]) -> tuple[atletas.Atleta, dict | None]:
    """Acha o atleta no ranking pelo nome e, se ele confirmar, guarda o
    playerId — dai em diante a busca e exata."""
    nome = atleta.nome_itf or atleta.nome
    for _ in range(3):
        jogador = estimativa.localizar_atleta(ranking, nome=nome)
        if jogador and confirmar_jogador(jogador):
            return vincular(conn, atleta, jogador), jogador

        if not jogador:
            print(cor(f"\n  Nao achei '{nome}' no ranking.", "yellow"))
        nome = perguntar(
            "  Seu nome como aparece na ITF (SOBRENOME Nome), ou Enter para seguir sem: "
        )
        if not nome:
            break
    return atleta, None


def localizar_no_ranking(conn, atleta: atletas.Atleta,
                         ranking: list[dict]) -> tuple[atletas.Atleta, dict | None]:
    if atleta.itf_player_id:
        jogador = estimativa.localizar_atleta(ranking, player_id=atleta.itf_player_id)
        if not jogador:
            print(cor(
                f"\n  Seu cadastro ITF ({atleta.nome_itf or atleta.itf_player_id}) "
                "nao aparece neste ranking: considero 0 pontos hoje.",
                "yellow",
            ))
        return atleta, jogador
    return procurar_e_vincular(conn, atleta, ranking)


# ═══════════════════════════════════════════════════════════════════════════════
# PONTOS POR RODADA
# ═══════════════════════════════════════════════════════════════════════════════
def escolher_categoria(tabela: dict, so_por_colocacao: bool = False) -> dict | None:
    opcoes = [
        (c["id"], c["nome"]) for c in pontuacao.listar_categorias(tabela)
        if not so_por_colocacao or c.get("por_colocacao", True)
    ]
    categoria_id = escolher("CATEGORIA DO TORNEIO", opcoes)
    return pontuacao.obter_categoria(tabela, categoria_id) if categoria_id else None


def escolher_chave(categoria: dict) -> dict | None:
    chaves = categoria["chaves"]
    if len(chaves) == 1:
        return chaves[0]
    opcoes = [(ch["id"], pontuacao.descrever_chave(ch)) for ch in chaves]
    chave_id = escolher(f"TAMANHO DA CHAVE — {categoria['nome']}", opcoes)
    return pontuacao.obter_chave(categoria, chave_id) if chave_id else None


def barra(pontos: int, maximo: int) -> str:
    if maximo <= 0 or pontos <= 0:
        return ""
    return "█" * max(1, round(pontos / maximo * 20))


def exibir_regra_especial(tabela: dict, categoria: dict) -> None:
    titulo(f"{categoria['nome']} — pontos")
    print(cor("  Esta categoria nao pontua por rodada, e sim por vitoria:\n", "dim"))
    for item in categoria.get("regra_especial", []):
        print(f"  {item['descricao']:<32} {item['pontos']:>5} pts")
    print(cor(f"\n  Fonte: tabela ITF {tabela.get('versao', '')}", "dim"))


def exibir_tabela_pontos(tabela: dict, categoria: dict, chave: dict) -> None:
    rodadas = pontuacao.rodadas_com_pontos(tabela, categoria["id"], chave["id"])
    principal = rodadas[pontuacao.FASE_PRINCIPAL]
    maximo = max((r["pontos"] for r in principal), default=0)
    bundles = list(categoria.get("bundles", {}))

    titulo(f"{categoria['nome']} — {pontuacao.descrever_chave(chave)}")
    print(cor("  Pontos de quem para em cada rodada (W = campeao).", "dim"))
    if chave.get("obs"):
        print(cor(f"  Obs: {chave['obs']}", "yellow"))

    cabecalho = f"\n  {'CHAVE PRINCIPAL':<34}{'pts':>5}"
    if bundles:
        cabecalho += "  │" + "".join(f"{pontuacao.nome_bundle(tabela, b):>13}" for b in bundles)
    print(cor(cabecalho, "bold"))
    for r in principal:
        linha = f"  {r['codigo']:<7}{r['nome']:<27}{r['pontos']:>5}"
        if bundles:
            linha += "  │" + "".join(
                f"{'+' + str(r['bundles'][b]) if r['bundles'].get(b) is not None else '—':>13}"
                for b in bundles
            )
        print(linha + "  " + cor(barra(r["pontos"], maximo), "cyan"))
    if bundles:
        print(cor("  Bundles sao pontos extras opcionais: so valem se o torneio oferecer.", "dim"))

    secoes = (
        (pontuacao.FASE_QUALIFYING, "QUALIFYING", "so para quem nao se classifica"),
        (pontuacao.FASE_BONUS, "BONUS DRAW", "consolacao — soma com a chave principal"),
    )
    for fase, nome, explicacao in secoes:
        if not rodadas[fase]:
            continue
        print(cor(f"\n  {nome}", "bold") + cor(f"  ({explicacao})", "dim"))
        for r in rodadas[fase]:
            print(f"  {r['codigo']:<7}{r['nome']:<27}{r['pontos']:>5}  "
                  + cor(barra(r["pontos"], maximo), "cyan"))

    print(cor("\n  Rodadas que nao aparecem nao valem pontos nesta chave.", "dim"))
    print(cor(f"  Fonte: tabela ITF {tabela.get('versao', '')}", "dim"))


def fluxo_tabela_pontos(tabela: dict) -> None:
    while True:
        categoria = escolher_categoria(tabela)
        if not categoria:
            return
        if not categoria.get("por_colocacao", True):
            exibir_regra_especial(tabela, categoria)
        else:
            chave = escolher_chave(categoria)
            if not chave:
                continue
            exibir_tabela_pontos(tabela, categoria, chave)
        perguntar(cor("\nEnter para escolher outro torneio...", "dim"))


def opcoes_de_rodada(linhas: list[dict]) -> list[tuple[str, str]]:
    opcoes = [(r["codigo"], f"{r['nome']:<30}{r['pontos']:>5} pts") for r in linhas]
    opcoes.append((SEM_PONTOS, "Parei numa rodada que nao vale pontos"))
    return opcoes


def pontos_por_colocacao_terminal(tabela: dict) -> tuple[int, dict] | None:
    """Pergunta torneio e colocacao. Devolve (pontos, detalhes para salvar)."""
    categoria = escolher_categoria(tabela, so_por_colocacao=True)
    if not categoria:
        return None
    chave = escolher_chave(categoria)
    if not chave:
        return None
    rodadas = pontuacao.rodadas_com_pontos(tabela, categoria["id"], chave["id"])

    fase = pontuacao.FASE_PRINCIPAL
    if rodadas[pontuacao.FASE_QUALIFYING]:
        fase = escolher("ONDE VOCE TERMINOU", [
            (pontuacao.FASE_PRINCIPAL, "Na chave principal (direto ou vindo do qualifying)"),
            (pontuacao.FASE_QUALIFYING, "No qualifying (nao me classifiquei)"),
        ])
        if not fase:
            return None

    detalhes = {"categoria": categoria["id"], "chave": chave["id"], "fase": fase}
    rodada = escolher("ATE ONDE VOCE CHEGOU", opcoes_de_rodada(rodadas[fase]))
    if not rodada:
        return None
    if rodada == SEM_PONTOS:
        print(cor("\n  Essa colocacao nao vale pontos: 0 pts.", "yellow"))
        return 0, detalhes
    detalhes["rodada"] = rodada

    bundles = []
    if fase == pontuacao.FASE_PRINCIPAL and categoria.get("bundles"):
        print(cor("\n  Bundles sao pontos extras opcionais que o torneio pode oferecer.", "dim"))
        for bundle_id in categoria["bundles"]:
            nome = pontuacao.nome_bundle(tabela, bundle_id)
            if sim(perguntar(f"  O torneio ofereceu o bundle {nome}? (s/N): ", "n")):
                bundles.append(bundle_id)

    rodada_bonus = None
    if fase == pontuacao.FASE_PRINCIPAL and rodadas[pontuacao.FASE_BONUS] and rodada != "W":
        print(cor(
            "\n  Bonus draw: consolacao para quem perdeu na 1a rodada da chave principal "
            "(ou na 2a, se teve bye).",
            "dim",
        ))
        if sim(perguntar("  Voce jogou o bonus draw? (s/N): ", "n")):
            escolha = escolher(
                "ATE ONDE CHEGOU NO BONUS DRAW",
                opcoes_de_rodada(rodadas[pontuacao.FASE_BONUS]),
                voltar="Nao jogou",
            )
            if escolha and escolha != SEM_PONTOS:
                rodada_bonus = escolha

    calculo = pontuacao.calcular_pontos(
        tabela, categoria["id"], chave["id"], fase, rodada, bundles, rodada_bonus
    )
    print(cor("\n  Pontos do torneio:", "bold"))
    for descricao, pontos in calculo.partes:
        print(f"    {descricao:<52}{pontos:>5}")
    print(cor(f"    {'TOTAL':<52}{calculo.total:>5}", "bold", "green"))
    for aviso in calculo.avisos:
        print(cor(f"    ⚠ {aviso}", "yellow"))

    if rodada_bonus:
        detalhes["rodada"] = f"{rodada} + bonus {rodada_bonus}"
    return calculo.total, detalhes


# ═══════════════════════════════════════════════════════════════════════════════
# ESTIMATIVA DE RANKING
# ═══════════════════════════════════════════════════════════════════════════════
def exibir_estimativa(est: estimativa.Estimativa, genero: str, info: dict) -> None:
    rotulo = itf.PLAYER_TYPE_LABELS.get(genero, genero)
    titulo("ESTIMATIVA DE RANKING")
    print(cor(f"  Base: ranking {rotulo} de {info.get('rank_date') or '?'}", "dim"))

    torneios = est.torneios_no_ranking
    torneios_txt = f"  ·  {torneios} torneio(s)" if est.encontrado and torneios is not None else ""
    print(f"\n  Hoje      {formatar_rank(est.rank_atual):>12}  ·  {est.pontos_atuais} pts{torneios_txt}")
    print(f"  Torneio   {'':>12}  ·  +{est.pontos_torneio} pts")

    if est.rank_melhor == est.rank_pior:
        rank_txt = f"{formatar_rank(est.rank_melhor):>12}"
    else:
        rank_txt = f"entre {formatar_rank(est.rank_melhor)} e {formatar_rank(est.rank_pior)}"
    if est.exata_nos_pontos:
        pontos_txt = f"{est.pontos_max} pts"
    else:
        pontos_txt = f"entre {est.pontos_min} e {est.pontos_max} pts"
    depois = f"  Depois    {rank_txt}  ·  {pontos_txt}"

    movimento = ""
    if est.rank_atual and est.rank_melhor:
        subida = est.rank_atual - est.rank_melhor
        prefixo = "" if est.exata_nos_pontos else "ate "
        if subida > 0:
            movimento = cor(f"   ▲ {prefixo}{subida} posicao(oes)", "green")
        elif subida == 0:
            movimento = cor("   = mesma posicao", "dim")
    elif not est.rank_atual and est.rank_melhor:
        movimento = cor("   ▲ entra no ranking", "green")
    print(cor(depois, "bold") + movimento)

    print()
    for aviso in est.avisos:
        print(cor(f"  ⚠ {aviso}", "yellow"))


def fluxo_estimativa(conn, atleta: atletas.Atleta, tabela: dict) -> atletas.Atleta:
    titulo("ESTIMAR MEU RANKING")
    ranking, info = carregar_ranking(atleta.genero)
    if len(ranking) < itf.MIN_RANKING_PLAYERS:
        print(cor("  Sem ranking da ITF carregado, nao da para estimar.", "red"))
        return atleta
    if not info.get("completo"):
        print(cor(
            "  ⚠ O ranking salvo esta incompleto: posicoes do fim da lista podem sair erradas.",
            "yellow",
        ))

    atleta, jogador = localizar_no_ranking(conn, atleta, ranking)

    modo = escolher("COMO VOCE QUER INFORMAR O RESULTADO", [
        ("colocacao", "Pela colocacao no torneio"),
        ("pontos", "Pelos pontos que ganhei"),
    ])
    if not modo:
        return atleta

    if modo == "colocacao":
        calculado = pontos_por_colocacao_terminal(tabela)
        if calculado is None:
            return atleta
        pontos, detalhes = calculado
    else:
        pontos = perguntar_inteiro("\n  Quantos pontos voce ganhou no torneio? ")
        if pontos is None:
            return atleta
        detalhes = {}

    melhores = pontuacao.melhores_resultados(tabela)
    torneios = itf.parse_inteiro(jogador.get("tournamentsPlayed")) if jogador else 0
    pior = None
    if pontos > 0 and (torneios is None or torneios >= melhores):
        print(cor(
            f"\n  So os {melhores} melhores resultados contam. Se voce souber quanto vale o "
            f"pior deles hoje, a estimativa sai exata.",
            "dim",
        ))
        pior = perguntar_inteiro("  Pontos do seu pior resultado que conta (Enter se nao souber): ")

    est = estimativa.estimar_ranking(ranking, jogador, pontos, melhores, pior)
    exibir_estimativa(est, atleta.genero, info)

    if sim(perguntar("\n  Salvar este resultado no seu historico? (s/N): ", "n")):
        salvar_resultado_terminal(conn, atleta, pontos, modo, detalhes)
    return atleta


def salvar_resultado_terminal(conn, atleta: atletas.Atleta, pontos: int,
                              origem: str, detalhes: dict) -> None:
    hoje = datetime.date.today().isoformat()
    while True:
        torneio = perguntar("  Nome do torneio (ex: BT200 Curitiba), Enter cancela: ")
        if not torneio:
            print(cor("  Nao salvei.", "dim"))
            return
        data = perguntar(f"  Data do torneio AAAA-MM-DD [{hoje}]: ", hoje)
        try:
            atletas.registrar_resultado(conn, atleta.id, {
                "torneio": torneio, "pontos": pontos, "origem": origem, "data": data,
                **detalhes,
            })
        except atletas.ErroValidacao as exc:
            mostrar_erros(exc)
            continue
        print(cor("  ✓ Resultado salvo.", "green"))
        return


# ═══════════════════════════════════════════════════════════════════════════════
# HISTORICO
# ═══════════════════════════════════════════════════════════════════════════════
def fluxo_resultados(conn, atleta: atletas.Atleta, tabela: dict | None) -> None:
    while True:
        resultados = atletas.listar_resultados(conn, atleta.id)
        titulo("MEUS RESULTADOS")
        if not resultados:
            print(cor("  Nenhum resultado salvo ainda.", "dim"))
            print(cor("  Para salvar, use 'Estimar meu ranking' e responda s no final.", "dim"))
            return

        print(cor(f"  {'nº':>3}  {'data':<10}  {'torneio':<28}  {'categoria':<10}  {'rodada':<14}  pts", "bold"))
        for i, r in enumerate(resultados, start=1):
            print(
                f"  {i:>3}  {atletas.data_do_resultado(r).isoformat():<10}  {r['torneio'][:28]:<28}  "
                f"{(r['categoria'] or '—'):<10}  {(r['rodada'] or '—')[:14]:<14}  {r['pontos']}"
            )

        if tabela:
            melhores = pontuacao.melhores_resultados(tabela)
            semanas = tabela["regras_ranking"]["janela_semanas"]
            soma = atletas.soma_dos_melhores(resultados, melhores, semanas)
            print(cor(
                f"\n  Soma dos {melhores} melhores nas ultimas {semanas} semanas: {soma} pts "
                "(so o que esta salvo aqui — nao e o ranking oficial).",
                "dim",
            ))

        acao = escolher("HISTORICO", [("remover", "Remover um resultado")])
        if not acao:
            return
        numero = perguntar_inteiro("  Numero do resultado a remover (Enter cancela): ", 1)
        if numero is None or numero > len(resultados):
            continue
        alvo = resultados[numero - 1]
        if sim(perguntar(f"  Remover '{alvo['torneio']}' ({alvo['pontos']} pts)? (s/N): ", "n")):
            atletas.excluir_resultado(conn, atleta.id, alvo["id"])
            print(cor("  ✓ Removido.", "green"))


# ═══════════════════════════════════════════════════════════════════════════════
# CONTA
# ═══════════════════════════════════════════════════════════════════════════════
def perguntar_genero(padrao: str | None) -> str:
    atual = f" [{atletas.GENEROS[padrao]}]" if padrao in atletas.GENEROS else ""
    while True:
        resposta = perguntar(f"  Ranking: 1 - masculino, 2 - feminino{atual}: ").lower()
        if not resposta:
            return padrao or ""
        if resposta in ("1", "m", "masc", "masculino"):
            return "M"
        if resposta in ("2", "f", "w", "fem", "feminino"):
            return "W"
        print(cor("  Digite 1 para masculino ou 2 para feminino.", "yellow"))


def formulario_perfil(padrao: dict) -> dict:
    """Campos do perfil. Enter mantem o valor entre colchetes; '-' apaga."""
    def campo(rotulo: str, chave: str) -> str:
        atual = padrao.get(chave)
        sufixo = f" [{atual}]" if atual not in (None, "") else ""
        resposta = perguntar(f"  {rotulo}{sufixo}: ", "" if atual is None else str(atual))
        return "" if resposta == "-" else resposta

    return {
        "nome":           campo("Nome completo", "nome"),
        "genero":         perguntar_genero(padrao.get("genero")),
        "nome_itf":       campo("Nome como aparece na ITF, SOBRENOME Nome (opcional)", "nome_itf"),
        "ano_nascimento": campo("Ano de nascimento (opcional)", "ano_nascimento"),
        "nacionalidade":  campo("Nacionalidade, 3 letras como na ITF — ex: BRA (opcional)", "nacionalidade"),
        "cidade":         campo("Cidade (opcional)", "cidade"),
    }


def fluxo_cadastro(conn) -> atletas.Atleta | None:
    titulo("CRIAR CONTA")
    print(cor("  Os dados ficam so neste computador (atletas.db). A senha e guardada como hash.", "dim"))

    dados: dict = {}
    while True:
        email_atual = dados.get("email", "")
        dados["email"] = perguntar(
            f"\n  E-mail{f' [{email_atual}]' if email_atual else ''}: ", email_atual
        )
        senha = ler_senha(f"  Senha (min. {atletas.SENHA_MIN} caracteres): ")
        confirmacao = ler_senha("  Repita a senha: ")
        dados.update(formulario_perfil(dados))

        if senha != confirmacao:
            print(cor("  ✗ As senhas nao conferem.", "red"))
        else:
            try:
                atleta = atletas.cadastrar(conn, dados, senha)
                break
            except atletas.ErroValidacao as exc:
                mostrar_erros(exc)

        if not sim(perguntar("  Corrigir e tentar de novo? (S/n): ", "s")):
            return None

    print(cor(f"\n  ✓ Conta criada. Bem-vindo(a), {atleta.nome}!", "green", "bold"))

    # Vincula ja, se o ranking estiver salvo; baixar agora atrasaria o cadastro.
    cache = itf.ler_cache(atleta.genero)
    if cache and cache.get("jogadores"):
        atleta, _ = procurar_e_vincular(conn, atleta, cache["jogadores"])
    else:
        print(cor("  Na primeira estimativa de ranking eu procuro voce no ranking da ITF.", "dim"))
    return atleta


def fluxo_login(conn) -> atletas.Atleta | None:
    titulo("ENTRAR")
    email = perguntar("  E-mail: ")
    senha = ler_senha("  Senha: ")
    try:
        atleta = atletas.autenticar(conn, email, senha)
    except atletas.ErroLogin as exc:
        print(cor(f"  ✗ {exc}", "red"))
        return None
    print(cor(f"\n  ✓ Ola, {atleta.nome}!", "green", "bold"))
    return atleta


def exibir_cadastro(atleta: atletas.Atleta) -> None:
    titulo("MEU CADASTRO")
    vinculo = (
        f"{atleta.nome_itf} (id {atleta.itf_player_id})" if atleta.itf_player_id
        else cor("nao vinculado", "yellow")
    )
    for rotulo, valor in (
        ("E-mail", atleta.email),
        ("Nome", atleta.nome),
        ("Ranking", atletas.GENEROS.get(atleta.genero, atleta.genero)),
        ("Nome na ITF", atleta.nome_itf or "—"),
        ("Vinculo ITF", vinculo),
        ("Nascimento", atleta.ano_nascimento or "—"),
        ("Nacionalidade", atleta.nacionalidade or "—"),
        ("Cidade", atleta.cidade or "—"),
    ):
        print(f"  {rotulo:<14} {valor}")


def fluxo_meu_cadastro(conn, atleta: atletas.Atleta) -> atletas.Atleta:
    while True:
        exibir_cadastro(atleta)
        acao = escolher("O QUE FAZER", [
            ("editar", "Editar meus dados"),
            ("itf", "Vincular (ou refazer o vinculo) ao ranking ITF"),
            ("senha", "Trocar senha"),
        ])
        if not acao:
            return atleta

        if acao == "editar":
            dados = formulario_perfil({
                campo: getattr(atleta, campo) for campo in atletas.CAMPOS_PERFIL
            })
            try:
                atleta = atletas.atualizar_perfil(conn, atleta.id, dados)
                print(cor("  ✓ Dados atualizados.", "green"))
            except atletas.ErroValidacao as exc:
                mostrar_erros(exc)

        elif acao == "itf":
            ranking, _ = carregar_ranking(atleta.genero)
            if len(ranking) < itf.MIN_RANKING_PLAYERS:
                print(cor("  Sem ranking da ITF carregado, nao da para vincular agora.", "red"))
                continue
            atleta, _ = procurar_e_vincular(conn, atleta, ranking)

        elif acao == "senha":
            atual = ler_senha("  Senha atual: ")
            nova = ler_senha(f"  Nova senha (min. {atletas.SENHA_MIN} caracteres): ")
            if nova != ler_senha("  Repita a nova senha: "):
                print(cor("  ✗ As senhas nao conferem.", "red"))
                continue
            try:
                atletas.alterar_senha(conn, atleta.id, atual, nova)
                print(cor("  ✓ Senha trocada.", "green"))
            except atletas.ErroValidacao as exc:
                mostrar_erros(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def rodar_tierlist() -> None:
    """A tierlist original, sem mudancas. Ela encerra com sys.exit em alguns
    erros; aqui isso so volta para o menu."""
    try:
        itf.main()
    except SystemExit:
        pass


def main():
    print(cor("╔══════════════════════════════════════════════════════════╗", "bold"))
    print(cor("║  ITF Beach Tennis — App do Atleta                        ║", "bold"))
    print(cor("╚══════════════════════════════════════════════════════════╝", "bold"))

    try:
        tabela = pontuacao.carregar_tabela()
    except pontuacao.ErroPontuacao as exc:
        print(cor(f"\n  ⚠ {exc}", "red"))
        print(cor("  Pontos por rodada e estimativa de ranking ficam desligados.", "red"))
        tabela = None

    conn = atletas.conectar()
    atleta: atletas.Atleta | None = None
    try:
        while True:
            if atleta is None:
                opcao = escolher("MENU", [
                    ("entrar", "Entrar"),
                    ("criar", "Criar conta"),
                    ("pontos", "Pontos por rodada de um torneio"),
                    ("tierlist", "Tierlist de duplas"),
                ], voltar="Sair")
            else:
                print(cor(f"\nConectado como {atleta.nome} ({atleta.email})", "green"))
                opcao = escolher("MENU", [
                    ("estimar", "Estimar meu ranking"),
                    ("resultados", "Meus resultados"),
                    ("pontos", "Pontos por rodada de um torneio"),
                    ("tierlist", "Tierlist de duplas"),
                    ("perfil", "Meu cadastro"),
                    ("logout", "Sair da conta"),
                ], voltar="Fechar o app")

            if opcao is None:
                break
            if opcao in ("pontos", "estimar") and tabela is None:
                print(cor("  Tabela de pontos indisponivel (veja o aviso no inicio).", "red"))
                continue

            if opcao == "entrar":
                atleta = fluxo_login(conn)
            elif opcao == "criar":
                atleta = fluxo_cadastro(conn)
            elif opcao == "pontos":
                fluxo_tabela_pontos(tabela)
            elif opcao == "tierlist":
                rodar_tierlist()
            elif opcao == "estimar":
                atleta = fluxo_estimativa(conn, atleta, tabela)
            elif opcao == "resultados":
                fluxo_resultados(conn, atleta, tabela)
            elif opcao == "perfil":
                atleta = fluxo_meu_cadastro(conn, atleta)
            elif opcao == "logout":
                print(cor(f"  Ate mais, {atleta.nome}!", "dim"))
                atleta = None
    except (EntradaEncerrada, KeyboardInterrupt):
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
