"""App web de ponta a ponta (TestClient), sem rede: as buscas na ITF sao
trocadas por versoes que gravam respostas reais salvas em testes/dados_itf."""
import datetime
import html.parser
import json
import re
import sqlite3
import tempfile
import time
import pathlib
import urllib.parse

from _base import DADOS_ITF, PASTA, check, fim
import atletas
import estimativa
import itf_dados

print("== migracao ==")
tmp = pathlib.Path(tempfile.mkdtemp()) / "v1.db"
bruto = sqlite3.connect(tmp)
bruto.executescript(atletas.ESQUEMA_V1)
bruto.execute("PRAGMA user_version = 1")
bruto.execute("INSERT INTO atletas (email, senha_hash, nome, genero, criado_em, atualizado_em) VALUES (?,?,?,?,?,?)",
              ("velho@ex.com", atletas.gerar_hash_senha("senhavelha1"), "Conta Velha", "M", "2026-10-01", "2026-10-01"))
bruto.execute("INSERT INTO resultados (atleta_id, torneio, pontos, origem, criado_em) VALUES (1, 'BT10 Antigo', 3, 'pontos', '2026-10-01')")
bruto.commit(); bruto.close()
c = atletas.conectar(tmp)
check(c.execute("PRAGMA user_version").fetchone()[0] == 4, "banco v1 migrado até a versão 4")
velho = atletas.autenticar(c, "velho@ex.com", "senhavelha1")
check(velho.nome == "Conta Velha" and velho.admin is False, "conta antiga continua entrando (admin=False)")
check(len(atletas.listar_resultados(c, velho.id)) == 1, "resultados antigos preservados na migração")
check(atletas.carregar_tierlist(c, velho.id) is None and atletas.listar_duplas_simuladas(c, velho.id) == [],
      "tabelas novas (tierlist e duplas simuladas) criadas vazias")

tmp3 = pathlib.Path(tempfile.mkdtemp()) / "v3.db"
bruto = sqlite3.connect(tmp3)
for v in (1, 2, 3):
    bruto.executescript(atletas.MIGRACOES[v])
bruto.execute("PRAGMA user_version = 3")
bruto.execute("INSERT INTO atletas (email, senha_hash, nome, genero, criado_em, atualizado_em) VALUES (?,?,?,?,?,?)",
              ("v3@ex.com", atletas.gerar_hash_senha("senhavelha1"), "Conta V3", "M", "2026-10-25", "2026-10-25"))
bruto.execute("INSERT INTO duplas_simuladas (atleta_id, jogador1, rank1, pontos1, jogador2, rank2, pontos2, criado_em) "
              "VALUES (1, 'SILVA Ana', 10, NULL, 'SOUZA Bia', NULL, 300, '2026-10-25')")
bruto.commit(); bruto.close()
c3 = atletas.conectar(tmp3)
antiga = atletas.listar_duplas_simuladas(c3, 1)
check(c3.execute("PRAGMA user_version").fetchone()[0] == 4 and atletas.autenticar(c3, "v3@ex.com", "senhavelha1").nome == "Conta V3"
      and len(antiga) == 1 and antiga[0]["rank1"] == 10 and antiga[0]["pontos2"] == 300 and antiga[0]["itf_id1"] is None,
      "banco v3 → v4: conta e dupla simulada antiga preservadas, sem playerId")
c3.close()

print("== convites / sessoes ==")
check(atletas.normalizar_convite(" bt-ab12 cd34 ") == "BT-AB12-CD34", "normaliza codigo digitado")
check(atletas.normalizar_convite("AB12CD34") == "BT-AB12-CD34", "aceita sem o prefixo")
check(atletas.normalizar_convite("xyz") == "", "codigo curto recusado")
cod = atletas.criar_convite(c, velho.id)
check(re.fullmatch(r"BT-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", cod) is not None, f"formato do convite {cod}")
base = {"email": "novo@ex.com", "nome": "Novo Atleta", "genero": "W"}
for convite, rotulo in (("", "vazio"), ("BT-AAAA-AAAA", "inexistente")):
    try:
        atletas.cadastrar(c, base, "senhaforte9", convite=convite); check(False, f"convite {rotulo} aceito")
    except atletas.ErroValidacao as e:
        check("convite" in e.erros, f"convite {rotulo} recusado")
novo = atletas.cadastrar(c, base, "senhaforte9", convite=cod.lower())
check(novo.genero == "W", "cadastro com convite (digitado em minusculo)")
try:
    atletas.cadastrar(c, {**base, "email": "outro@ex.com"}, "senhaforte9", convite=cod); check(False, "convite reusado")
except atletas.ErroValidacao as e:
    check("convite" in e.erros, "convite nao serve duas vezes")
vencido = atletas.criar_convite(c, validade_dias=0)
try:
    atletas.cadastrar(c, {**base, "email": "v@ex.com"}, "senhaforte9", convite=vencido); check(False, "convite vencido aceito")
except atletas.ErroValidacao:
    check(True, "convite vencido recusado")
cancelado = atletas.criar_convite(c)
check(atletas.revogar_convite(c, cancelado), "cancela convite")
try:
    atletas.cadastrar(c, {**base, "email": "r@ex.com"}, "senhaforte9", convite=cancelado); check(False, "convite cancelado aceito")
except atletas.ErroValidacao:
    check(True, "convite cancelado recusado")
check(c.execute("SELECT COUNT(*) FROM atletas WHERE email IN ('outro@ex.com','v@ex.com','r@ex.com')").fetchone()[0] == 0,
      "nenhuma conta criada pelas tentativas recusadas")
sit = {x["codigo"]: x["situacao"] for x in atletas.listar_convites(c)}
check(sit[cod] == "usado" and sit[vencido] == "expirado" and sit[cancelado] == "cancelado", f"situacoes: {sorted(set(sit.values()))}")
t1 = atletas.criar_sessao(c, novo.id); t2 = atletas.criar_sessao(c, novo.id)
check(atletas.atleta_da_sessao(c, t1).id == novo.id, "sessao valida")
check(c.execute("SELECT COUNT(*) FROM sessoes WHERE token_hash = ?", (t1,)).fetchone()[0] == 0, "token nao fica no banco em claro")
atletas.alterar_senha(c, novo.id, "senhaforte9", "outrasenha2", sessao_atual=t1)
check(atletas.atleta_da_sessao(c, t1) is not None and atletas.atleta_da_sessao(c, t2) is None, "troca de senha derruba as outras sessoes")
atletas.encerrar_sessao(c, t1)
check(atletas.atleta_da_sessao(c, t1) is None, "sair encerra a sessao")
check(atletas.definir_admin(c, "NOVO@ex.com").admin is True, "define admin pelo e-mail")
check(atletas.definir_admin(c, "naoexiste@ex.com") is None, "admin de e-mail inexistente devolve None")
hoje = datetime.date(2026, 10, 25)
res = [{"pontos": p, "data": d, "criado_em": "2026-10-25"} for p, d in
       ((72, "2026-10-01"), (200, "2025-09-01"), *((5, "2026-09-01"),) * 12)]
check(atletas.soma_dos_melhores(res, 10, 52, hoje) == 72 + 9 * 5, "soma dos 10 melhores ignora o que saiu da janela")

print("== duplas simuladas (banco) ==")
sid = atletas.adicionar_dupla_simulada(c, novo.id, {"jogador1": "SILVA Ana", "rank1": "10", "jogador2": "SOUZA Bia", "pontos2": "300"})
check(atletas.listar_duplas_simuladas(c, novo.id)[0]["id"] == sid, "salva dupla simulada")
for ruim, campo in (({"jogador1": "", "jogador2": "X Y"}, "jogador1"),
                    ({"jogador1": "A B", "jogador2": "X Y", "rank1": "5", "pontos1": "10"}, "pontos1"),
                    ({"jogador1": "A B", "jogador2": "X Y", "rank2": "-3"}, "rank2")):
    try:
        atletas.adicionar_dupla_simulada(c, novo.id, ruim); check(False, f"dupla inválida aceita {ruim}")
    except atletas.ErroValidacao as e:
        check(campo in e.erros, f"dupla simulada recusada: {campo}")
sid2 = atletas.adicionar_dupla_simulada(c, novo.id, {"jogador1": "NOME Itf", "itf_id1": 800767267, "rank1": "10",
                                                     "jogador2": "SOUZA Bia", "pontos2": "300"})
s2 = next(s for s in atletas.listar_duplas_simuladas(c, novo.id) if s["id"] == sid2)
check(s2["itf_id1"] == 800767267 and s2["rank1"] is None and s2["itf_id2"] is None and s2["pontos2"] == 300,
      "com playerId o rank digitado é ignorado (vem do ranking)")
atletas.excluir_dupla_simulada(c, novo.id, sid2)
check(not atletas.excluir_dupla_simulada(c, velho.id, sid), "não exclui dupla de outro atleta")
check(atletas.excluir_dupla_simulada(c, novo.id, sid), "exclui a própria dupla")
c.close()

# ─── app web ──────────────────────────────────────────────────────────────
print("== web ==")
from fastapi.testclient import TestClient
import web

# Nada de rede nos testes: qualquer busca real na ITF quebra o teste.
def _proibido(*_, **__):
    raise RuntimeError("busca real na ITF durante o teste")
web.itf.buscar_ranking_itf = _proibido
itf_dados.ColetorITF.__enter__ = _proibido

CALENDARIO = json.load(open(DADOS_ITF / "calendario_amostra.json", encoding="utf-8"))["items"]
chamadas = []

def falso_calendario():
    chamadas.append("calendario")
    itf_dados._gravar(itf_dados.ARQUIVO_CALENDARIO, {"coletado_em": time.time(), "torneios": CALENDARIO})

def falsa_chave(chave):
    chamadas.append(f"chave:{chave}")
    drawsheet = json.load(open(DADOS_ITF / "drawsheet_bt200_florianopolis_M_M.json", encoding="utf-8"))
    import resultados_itf
    itf_dados._gravar(itf_dados._arquivo_chave(chave), {
        "coletado_em": time.time(), "publicada": True,
        "eventos": {"M": {"principal": resultados_itf.estrutura_do_drawsheet(drawsheet)}}})

def falsa_atividade(player_id, genero, tabela, data_ref):
    chamadas.append(f"atividade:{player_id}")
    itens = json.load(open(DADOS_ITF / f"atividade_{player_id}.json", encoding="utf-8"))["items"]
    itf_dados._gravar(itf_dados._arquivo_atividade(player_id), {"coletado_em": time.time(), "itens": itens})

web.itf_dados.atualizar_calendario = falso_calendario
web.itf_dados.atualizar_chave = falsa_chave
web.itf_dados.atualizar_atividade = falsa_atividade

class Tags(html.parser.HTMLParser):
    VAZIOS = {"meta", "link", "input", "br", "img", "hr", "path", "circle", "rect", "source", "area", "col", "wbr"}
    def __init__(self):
        super().__init__(); self.pilha = []; self.erros = []
    def handle_starttag(self, tag, attrs):
        if tag not in self.VAZIOS: self.pilha.append(tag)
    def handle_startendtag(self, tag, attrs): pass
    def handle_endtag(self, tag):
        if tag in self.VAZIOS: return
        if self.pilha and self.pilha[-1] == tag: self.pilha.pop()
        else: self.erros.append(f"</{tag}> com pilha {self.pilha[-3:]}")

def html_ok(texto, nome):
    p = Tags(); p.feed(texto)
    ok = not p.erros and not p.pilha
    check(ok, f"HTML bem fechado: {nome}" + ("" if ok else f" {p.erros[:2]} sobrou {p.pilha[-3:]}"))

def csrf_de(texto):
    m = re.search(r'name="csrf" value="([0-9a-f]+)"', texto)
    return m.group(1) if m else ""

def esperar(cliente, nome):
    for _ in range(50):
        if not cliente.get(f"/tarefa?nome={nome}").json()["rodando"]:
            return True
        time.sleep(0.1)
    return False

cli = TestClient(web.app, base_url="https://testserver")
r = cli.get("/", follow_redirects=False)
check(r.status_code == 303 and r.headers["location"] == "/entrar", "raiz sem login vai para /entrar")
r = cli.get("/inicio", follow_redirects=False)
check(r.status_code == 303 and r.headers["location"] == "/entrar", "pagina protegida sem login vai para /entrar")
check(cli.get("/tarefa?nome=x", follow_redirects=False).status_code == 303, "status de tarefa exige login")
r = cli.get("/entrar")
check(r.status_code == 200 and "Criar conta com convite" in r.text, "tela de entrar")
html_ok(r.text, "entrar")
for h in ("content-security-policy", "x-frame-options", "x-content-type-options", "referrer-policy"):
    check(h in r.headers, f"cabecalho {h}")
check(r.headers.get("cache-control") == "no-store", "paginas sem cache")
check("public" in cli.get("/static/app.css").headers.get("cache-control", ""), "estaticos com cache")
r = cli.get("/cadastro?convite=bt-ab12-cd34")
check('value="BT-AB12-CD34"' in r.text, "link de convite preenche o codigo")
html_ok(r.text, "cadastro")

conn = atletas.conectar()
convite = atletas.criar_convite(conn)
form = {"convite": convite, "email": "lucas@ex.com", "senha": "senhaforte9", "senha2": "senhaforte9",
        "nome": "Lucas Cobucci", "genero": "M", "nome_itf": "", "ano_nascimento": "", "nacionalidade": "bra", "cidade": ""}
r = cli.post("/cadastro", data={**form, "convite": ""}, follow_redirects=False)
check(r.status_code == 400 and "Informe o código do convite" in r.text, "cadastro sem convite recusado")
r = cli.post("/cadastro", data={**form, "senha2": "diferente9"}, follow_redirects=False)
check(r.status_code == 400 and "não conferem" in r.text, "senhas diferentes recusadas")
html_ok(r.text, "cadastro com erros")
r = cli.post("/cadastro", data=form, follow_redirects=False)
check(r.status_code == 303 and r.headers["location"] == "/inicio?msg=bem_vindo", "cadastro com convite cria conta")
ck = r.headers.get("set-cookie", "")
check("HttpOnly" in ck and "Secure" in ck and "samesite=lax" in ck.lower(), "cookie de sessao HttpOnly+Secure+SameSite")
r = TestClient(web.app, base_url="https://testserver").post("/cadastro", data={**form, "email": "x@ex.com"}, follow_redirects=False)
check(r.status_code == 400, "mesmo convite nao cria segunda conta")

r = cli.get("/inicio?msg=bem_vindo")
check(r.status_code == 200 and "Olá, Lucas" in r.text and "Vincule sua conta" in r.text and "Conta criada" in r.text, "inicio de conta nova")
check("Conta criada" not in cli.get("/inicio?msg=<b>oi</b>").text, "msg desconhecida na URL nao aparece na pagina")
check("Definir minha meta" in r.text, "cartão da meta no início")
html_ok(r.text, "inicio")
check("/convites" not in r.text, "menu sem convites para nao-admin")
r = cli.get("/perfil")
check("Vincule sua conta ao ranking ITF para ver seus torneios" in r.text, "perfil sem vínculo pede para vincular antes dos resultados")
r = cli.get("/perfil/itf?nome=GIANOTTI Nicolas")
check("Nicolas Gianotti" in r.text and "Sou eu" in r.text, "acha candidato no ranking")
html_ok(r.text, "perfil_itf")
pid = re.search(r'name="player_id" value="(\d+)"', r.text).group(1)
r = cli.post("/perfil/itf", data={"player_id": pid}, follow_redirects=False)
check(r.status_code == 400, "POST sem csrf recusado")
token = csrf_de(cli.get("/perfil").text)
r = cli.post("/perfil/itf", data={"player_id": "123", "csrf": token}, follow_redirects=False)
check(r.status_code == 400, "nao vincula playerId que nao esta no ranking")
r = cli.post("/perfil/itf", data={"player_id": pid, "csrf": token}, follow_redirects=False)
check(r.status_code == 303, "vincula com csrf")
ranking = json.load(open(PASTA / "ranking_itf_M.json", encoding="utf-8"))["jogadores"]
gianotti = next(j for j in ranking if j["playerId"] == int(pid))
gp, gt = gianotti["points"], gianotti["tournamentsPlayed"]
r = cli.get("/inicio")
check(f"#{gianotti['rank']}</span>" in r.text and f">{gp}<" in r.text and f">{gt}<" in r.text
      and "10 de 10 resultados contando" in r.text, f"cartao de ranking com dados reais (#{gianotti['rank']}, {gp} pts, {gt} torneios)")

print("== pontos por rodada ==")
r = cli.get("/pontos?cat=BT400&chave=32x32")
check(r.status_code == 200 and ">400<" in r.text and "Hospitality" in r.text and "+40" in r.text, "pontos BT400 com bundles (manual)")
html_ok(r.text, "pontos manual")
r = cli.get("/pontos?cat=TOUR_FINALS")
check("por vitória" in r.text and "1000" in r.text, "Tour Finals por vitoria")
r = cli.get("/pontos?cat=XYZ&chave=lixo")
check(r.status_code == 200 and "BT200 / Regional Championships 1 — tamanho da chave" in r.text, "parametro invalido cai no padrao")
r = cli.get("/pontos")
check("Torneio real" in r.text and "Baixar calendário" in r.text, "sem calendário: oferece baixar")
html_ok(r.text, "pontos sem calendario")
token = csrf_de(r.text)
r = cli.post("/itf/calendario", data={"csrf": token}, follow_redirects=False)
check(r.headers["location"] == "/pontos?aguardar=calendario" and esperar(cli, "calendario") and "calendario" in chamadas,
      "baixar calendário roda em segundo plano")
check(cli.get("/tarefa?nome=calendario").json()["ok"] is True, "status da tarefa: terminou bem")
r = cli.post("/itf/calendario", data={"csrf": token}, follow_redirects=False)
check(r.headers["location"] == "/pontos" and chamadas.count("calendario") == 1, "calendário fresco não é baixado de novo")
r = cli.get("/pontos?periodo=todos&pais=BRA&busca=florian")
check("BT200 Florianópolis" in r.text and "B-TOUR-BRA-2026-068" in r.text, "busca no calendário por nome e país")
html_ok(r.text, "pontos busca")
check("BT10 Embalse" not in cli.get("/pontos?periodo=todos&pais=BRA").text, "filtro de país (Brasil) tira a Argentina")
check("BT10 Embalse" in cli.get("/pontos?periodo=todos&pais=&busca=embalse").text, "todos os países")
r = cli.get("/pontos?torneio=B-TOUR-BRA-2026-068")
check("BT200 Florianópolis" in r.text and "Buscar chave na ITF" in r.text and "ainda não publicada" in r.text
      and ">200<" in r.text, "torneio real sem chave: categoria automática, tamanho manual e botão de buscar a chave")
check("torneio_nome=BT200%20Florian" in r.text, "link para estimar leva o nome do torneio")
html_ok(r.text, "pontos torneio")
r = cli.post("/itf/chave", data={"csrf": token, "torneio": "B-TOUR-BRA-2026-068"}, follow_redirects=False)
check(r.status_code == 303 and esperar(cli, "chave:B-TOUR-BRA-2026-068"), "busca a chave em segundo plano")
r = cli.get("/pontos?torneio=B-TOUR-BRA-2026-068")
check("Chave da ITF" in r.text and "chave principal 32" in r.text and "Buscar chave na ITF" not in r.text,
      "com a chave publicada o tamanho vem sozinho")
check(cli.post("/itf/chave", data={"csrf": token, "torneio": "NAO-EXISTE"}).status_code == 400, "chave de torneio fora do calendário recusada")
check(cli.get("/pontos?torneio=NAO-EXISTE").status_code == 404, "torneio desconhecido: 404")

print("== estimativa ==")
r = cli.get("/estimar?modo=colocacao&cat=BT200&chave=32x32&rodada=SF")
check(r.status_code == 200 and "Pontos do torneio" in r.text and ">72<" in r.text, "estimativa por colocacao")
minimo = gp + max(0, 72 - gp // 10)
check("Seu pior resultado" in r.text and f"{minimo}–{gp + 72} pts" in r.text, f"jogador com {gt} torneios: pede o pior e mostra faixa")
html_ok(r.text, "estimar")
r = cli.get("/estimar?modo=colocacao&cat=BT200&chave=32x32&rodada=SF&pior=50")
check(f">{gp + 22} pts<" in r.text, f"com o pior resultado sai exato ({gp} + 72 - 50)")
r = cli.get("/estimar?modo=colocacao&cat=BT400&chave=32x32&rodada=SF&bundles=TV&bundles=HACK&bonus=W")
check("Bundle TV" in r.text and "Campeão do bonus draw" in r.text and ">175<" in r.text and "HACK" not in r.text,
      "bundle e bonus somam (144 + 14 + 17), bundle invalido ignorado")
r = cli.get("/estimar?modo=colocacao&cat=BT10&chave=32x32&rodada=SF&fase=qualifying")
check(r.status_code == 200, "fase/rodada que nao combinam nao quebram")
r = cli.get("/estimar?modo=pontos&pontos=abc")
check("número inteiro" in r.text, "pontos invalidos avisam")
r = cli.get("/estimar?modo=pontos&pontos=36&torneio_nome=BT200 Florianópolis")
check('value="BT200 Florianópolis"' in r.text, "nome do torneio real preenche o salvar")
html_ok(r.text, "estimar por pontos")

token = csrf_de(r.text)
r = cli.post("/resultados", data={"csrf": token, "torneio": "BT200 Curitiba", "data": "2026-10-12", "pontos": "72",
                                  "origem": "colocacao", "categoria": "BT200", "chave": "32x32", "fase": "principal", "rodada": "SF"},
             follow_redirects=False)
check(r.status_code == 303, "salva resultado")
r = cli.post("/resultados", data={"csrf": token, "torneio": "", "pontos": "-5", "origem": "x"}, follow_redirects=False)
check(r.status_code == 400 and "Algo deu errado" in r.text, "resultado invalido vira pagina de erro")
r = cli.get("/resultados")
check("BT200 Curitiba" in r.text and "12/10/2026" in r.text and "72 pts" in r.text, "lista de resultados com soma")
html_ok(r.text, "resultados")
rid = re.search(r'/resultados/(\d+)/remover', r.text).group(1)
cli.post(f"/resultados/{rid}/remover", data={"csrf": token})
check("BT200 Curitiba" not in cli.get("/resultados").text, "remove resultado")

print("== perfil: resultados da ITF ==")
r = cli.get("/perfil")
check("Buscar meus resultados na ITF" in r.text, "perfil vinculado oferece buscar os resultados")
r = cli.post("/perfil/resultados/atualizar", data={"csrf": token}, follow_redirects=False)
check(r.status_code == 303 and esperar(cli, f"atividade:{pid}") and f"atividade:{pid}" in chamadas, "busca os resultados em segundo plano")
r = cli.get("/perfil")
check("World Championships" in r.text and "Campeão" in r.text and "conta · vence" in r.text, "perfil lista os torneios e quais contam")
check("Oficial:" in r.text, "soma que não bate com o oficial mostra a diferença")
check("Torneios mais antigos" not in r.text or "<details" in r.text, "histórico antigo recolhido")
html_ok(r.text, "perfil com resultados")
r = cli.post("/perfil/resultados/atualizar", data={"csrf": token}, follow_redirects=False)
check("msg=recente" in r.headers["location"] and chamadas.count(f"atividade:{pid}") == 1, "não busca de novo em menos de 10 minutos")
r = cli.get("/estimar?modo=colocacao&cat=BT200&chave=32x32&rodada=SF")
check("Seu pior resultado entre os" in r.text, "resultado da ITF que não confere: continua pedindo o pior")

# Conta vinculada ao Lucas real: os resultados da ITF batem com o oficial.
lucas_cli = TestClient(web.app, base_url="https://testserver")
convite2 = atletas.criar_convite(conn)
lucas_cli.post("/cadastro", data={**form, "convite": convite2, "email": "lucas2@ex.com", "nome": "Lucas Real"})
lucas_id = conn.execute("SELECT id FROM atletas WHERE email = 'lucas2@ex.com'").fetchone()[0]
atletas.vincular_itf(conn, lucas_id, 800767267, "lucas Cobucci Babula Alves")
falsa_atividade(800767267, "M", None, None)
import resultados_itf, pontuacao
lucas_rank = next(j for j in ranking if j["playerId"] == 800767267)
itens = json.load(open(DADOS_ITF / "atividade_800767267.json", encoding="utf-8"))["items"]
esperado = resultados_itf.marcar_contando(
    resultados_itf.resultados_do_atleta(itens, pontuacao.carregar_tabela(), itf_dados.calendario_por_chave()),
    web.dia_do_ranking(web.dados_ranking("M")), 10)["soma"]
r = lucas_cli.get("/perfil")
if esperado == lucas_rank["points"]:
    check(f"Confere com o oficial ({lucas_rank['points']} pts)" in r.text, f"resultados da ITF conferem com o oficial ({esperado} pts)")
else:
    check(f"{esperado} pts" in r.text and "Oficial:" in r.text, f"ranking salvo mudou: mostra {esperado} e a diferença")
check("BT50 Curitiba" in r.text and "Oitavas de final" in r.text and "BT10 Curitiba 1" in r.text, "torneio, rodada e parceiro do Lucas")
check("entra no ranking em 26/10" in r.text, "torneio que terminou depois do ranking salvo: mostra quando entra")

print("== meta ==")
r = lucas_cli.get("/meta")
check(r.status_code == 200 and "Onde você quer chegar" in r.text, "meta sem alvo mostra o formulário")
html_ok(r.text, "meta sem alvo")
check("número inteiro" in lucas_cli.get("/meta?alvo=abc").text, "alvo inválido avisa")
necessario, _ = estimativa.pontos_para_posicao(ranking, 1000, 800767267)
r = lucas_cli.get("/meta?alvo=1000&pais=BRA")
check(f">{necessario}<" in r.text and "Faltam" in r.text and "Por categoria" in r.text and "Próximos torneios" in r.text,
      f"meta para o #1000: precisa de {necessario} pts")
check("BT400" in r.text and any(f in r.text for f in ("Entrar na chave principal", "Chegar às", "Chegar à", "Ser campeão", "Meta já garantida")),
      "meta mostra até onde chegar por categoria")
html_ok(r.text, "meta com alvo")
r = lucas_cli.get(f"/meta?alvo={lucas_rank['rank'] + 5}")
check("dentro da meta" in r.text, "alvo pior que a posição atual: meta já alcançada")
r = cli.get("/meta?alvo=1")
check("já está em" in r.text, "líder do ranking já está no #1")

print("== tierlist ==")
r = lucas_cli.get("/tierlist")
check("Cole a lista do torneio" in r.text, "tierlist vazia")
html_ok(r.text, "tierlist vazia")
def nome(j): return f"{j['playerFamilyName'].upper()} {j['playerGivenName']}"
lista = "\n".join(f"{i}\n{nome(ranking[2 * i])}\n{nome(ranking[2 * i + 1])}" for i in range(1, 25))
lista += "\n25\nGIANOTTI Nicolas\nFULANO Inexistente"
token = csrf_de(cli.get("/tierlist").text)
t0 = time.perf_counter()
r = cli.post("/tierlist", data={"csrf": token, "genero": "M", "chave": "32x32", "corte": "", "lista": lista}, follow_redirects=False)
check(r.status_code == 303 and r.headers["location"].startswith("/tierlist?msg=lista_salva"), "salva a lista e volta para a tierlist")
r = cli.get("/tierlist")
dt = time.perf_counter() - t0
check(r.text.count('faixa faixa-cabeca"') == 8 + 1 and "Qualifying a partir daqui" in r.text,
      f"25 duplas numa 32x32: 8 cabeças e o corte do qualifying ({dt:.1f}s)")
check("sua dupla" in r.text, "destaca a dupla do atleta logado")
html_ok(r.text, "tierlist")
outro = TestClient(web.app, base_url="https://testserver")
outro.post("/entrar", data={"email": "lucas@ex.com", "senha": "senhaforte9"})
check("FULANO Inexistente" in outro.get("/tierlist").text, "lista salva na conta, aparece em outro aparelho")
check("FULANO Inexistente" not in lucas_cli.get("/tierlist").text, "cada atleta vê só a própria lista")

top3000 = next(j for j in ranking if j["points"] >= 3000 and j["rank"] > 1)
r = cli.post("/tierlist/simuladas", data={"csrf": token, "jogador1": "TESTE Um", "rank1": "5",
                                          "jogador2": "TESTE Dois", "pontos2": str(top3000["points"])}, follow_redirects=False)
check(r.status_code == 303, "adiciona dupla simulada")
r = cli.get("/tierlist")
check("TESTE Um" in r.text and "etiqueta-simulada" in r.text, "dupla simulada aparece na tierlist")
linha_simulada = r.text[r.text.index("TESTE Um") - 900:r.text.index("TESTE Um")]
check('faixa-cabeca"' in linha_simulada, "simulada com #5 e um top da ITF entra como cabeça")
r = cli.post("/tierlist/simuladas", data={"csrf": token, "jogador1": "A B", "rank1": "5", "pontos1": "9",
                                          "jogador2": "C D"})
check(r.status_code == 400 and "não os dois" in r.text, "rank e pontos juntos: erro no campo")
html_ok(r.text, "tierlist com erro na simulada")
sid = re.search(r"/tierlist/simuladas/(\d+)/excluir", cli.get("/tierlist").text).group(1)
check(lucas_cli.post(f"/tierlist/simuladas/{sid}/excluir", data={"csrf": csrf_de(lucas_cli.get("/tierlist").text)}).status_code == 200
      and "TESTE Um" in cli.get("/tierlist").text, "outro atleta não exclui a sua simulada")
cli.post(f"/tierlist/simuladas/{sid}/excluir", data={"csrf": token})
check("TESTE Um" not in cli.get("/tierlist").text, "exclui a dupla simulada")

print("== tierlist: escolher no ranking e 'Sou eu' ==")
check(TestClient(web.app, base_url="https://testserver").get("/ranking/buscar?genero=M&q=gianot", follow_redirects=False).status_code == 303,
      "busca no ranking exige login")
r = cli.get("/ranking/buscar?genero=M&q=gianot")
achados = r.json()["jogadores"]
check(r.status_code == 200 and achados and achados[0]["id"] == int(pid) and achados[0]["rank"] == gianotti["rank"]
      and achados[0]["pontos"] == gp and achados[0]["pais"], "busca acha pelo começo do nome, com rank, pontos e país")
check(cli.get("/ranking/buscar?genero=X&q=gianot").json()["jogadores"] == []
      and cli.get("/ranking/buscar?genero=M&q=g").json()["jogadores"] == [], "gênero inválido ou 1 letra: lista vazia")
r = cli.get("/tierlist")
check('name="eu1"' in r.text and "data-sou-eu=" in r.text and r.text.count('data-buscar-ranking="M"') == 2,
      "formulário da dupla com 'Sou eu' e busca nos dois atletas")
eu_json = json.loads(re.search(r'data-sou-eu="([^"]+)"', r.text).group(1).replace("&#34;", '"').replace("&quot;", '"'))
check(eu_json["id"] == int(pid) and eu_json["rank"] == gianotti["rank"], "dados do 'Sou eu' saem do vínculo com a ITF")
cli_id = conn.execute("SELECT id FROM atletas WHERE email = 'lucas@ex.com'").fetchone()[0]
alvo = ranking[300]
nome_alvo = web.itf.obter_nome_jogador(alvo)
r = cli.post("/tierlist/simuladas", data={"csrf": token, "jogador1": "", "eu1": "1",
                                          "jogador2": "texto digitado", "itf2": str(alvo["playerId"]), "rank2": "7"},
             follow_redirects=False)
check(r.status_code == 303, "adiciona dupla com 'Sou eu' e atleta escolhido no ranking")
s = atletas.listar_duplas_simuladas(conn, cli_id)[-1]
check(s["itf_id1"] == int(pid) and s["itf_id2"] == alvo["playerId"] and s["jogador2"] == nome_alvo and s["rank2"] is None,
      "guarda o playerId e o nome da ITF; o rank digitado junto é ignorado")
r = cli.get("/tierlist")
i = r.text.index(nome_alvo)
linha = r.text[r.text.rfind("<tr", 0, i):r.text.find("</tr>", i)]
check(f"#{alvo['rank']}<" in linha and f"#{gianotti['rank']}<" in linha and "sua dupla" in linha,
      f"ranks vêm do ranking (#{gianotti['rank']} e #{alvo['rank']}) e a dupla é marcada como sua")
html_ok(r.text, "tierlist com dupla escolhida no ranking")
r = cli.post("/tierlist/simuladas", data={"csrf": token, "jogador1": "NINGUEM Silva", "itf1": "123",
                                          "jogador2": "OUTRO Fulano", "rank2": "50"}, follow_redirects=False)
s = atletas.listar_duplas_simuladas(conn, cli_id)[-1]
check(r.status_code == 303 and s["itf_id1"] is None and s["jogador1"] == "NINGUEM Silva" and s["rank2"] == 50,
      "playerId fora do ranking é ignorado e vale o nome digitado")
r = cli.post("/tierlist/simuladas", data={"csrf": token, "jogador1": "", "itf1": str(alvo["playerId"]), "jogador2": ""})
check(r.status_code == 400 and f'name="itf1" value="{alvo["playerId"]}"' in r.text and f"No ranking: #{alvo['rank']}" in r.text
      and "Informe o nome do atleta" in r.text, "erro no formulário mantém quem foi escolhido no ranking")
html_ok(r.text, "tierlist com erro e atleta escolhido")
for s in atletas.listar_duplas_simuladas(conn, cli_id):
    atletas.excluir_dupla_simulada(conn, cli_id, s["id"])
sem_vinculo = TestClient(web.app, base_url="https://testserver")
sem_vinculo.post("/cadastro", data={**form, "convite": atletas.criar_convite(conn), "email": "semvinculo@ex.com"})
r = sem_vinculo.get("/tierlist")
check(r.status_code == 200 and 'name="eu1"' not in r.text and 'data-buscar-ranking="M"' in r.text,
      "sem vínculo com a ITF: sem 'Sou eu', mas com a busca")

r = cli.get("/tierlist?alvo=principal&rank_atleta=1500")
check("resultado-parceiro" in r.text and "alvo: Chave principal (até a 20ª)" in r.text, "ranking mínimo do parceiro para entrar direto")
m = re.search(r"Parceiro precisa ser</span><span class=\"numero numero-grande destaque\">#(\d+)<", r.text)
check(m is not None or "Não dá" in r.text or "Qualquer parceiro" in r.text, "mostra o rank máximo do parceiro (ou que não dá)")
html_ok(r.text, "tierlist com parceiro")
r = cli.get("/tierlist?alvo=cabeca_qualy&atleta=GIANOTTI Nicolas&pais=")
check("Atletas que atendem" in r.text or "Qualquer parceiro" in r.text, "lista atletas reais que atendem")
check("Escolha a faixa ou digite a posição" in cli.get("/tierlist?alvo=posicao&posicao=abc").text, "posição inválida avisa")

# Simula o ranking feminino ainda nao baixado, tenha ou nao o arquivo na pasta.
arquivo_real = web.itf.arquivo_cache
sem_arquivo = pathlib.Path(tempfile.mkdtemp())
web.itf.arquivo_cache = lambda g: sem_arquivo / f"ranking_itf_{g}.json" if g == "W" else arquivo_real(g)
r = cli.post("/tierlist", data={"csrf": token, "genero": "W", "chave": "32x32", "lista": lista})
web.itf.arquivo_cache = arquivo_real
check(r.status_code == 400 and "ainda não foi baixado" in r.text, "ranking feminino sem cache avisa")
r = cli.post("/tierlist", data={"csrf": token, "genero": "M", "chave": "32x32", "lista": "abc"})
check(r.status_code == 400 and "Não entendi a lista" in r.text, "lista mal formatada avisa e não salva")
check("FULANO Inexistente" in cli.get("/tierlist").text, "lista anterior continua salva depois do erro")

print("== convites, tema, senha ==")
check(cli.get("/convites").status_code == 403, "convites bloqueado para nao-admin")
check(cli.post("/ranking/atualizar", data={"csrf": token, "genero": "M"}).status_code == 403, "atualizar ranking bloqueado para nao-admin")
atletas.definir_admin(conn, "lucas@ex.com")
r = cli.get("/convites")
check(r.status_code == 200, "convites para admin")
html_ok(r.text, "convites")
r = cli.post("/convites", data={"csrf": token}, follow_redirects=False)
novo_cod = r.headers["location"].split("novo=")[1]
r = cli.get(f"/convites?novo={novo_cod}")
check(novo_cod in r.text and "wa.me" in r.text and f"https://testserver/cadastro?convite={novo_cod}" in r.text, "convite novo com link e WhatsApp")
cli.post(f"/convites/{novo_cod}/cancelar", data={"csrf": token})
check("situacao-cancelado" in cli.get("/convites").text, "cancela convite pela web")
check("Atualizar ranking da ITF" in cli.get("/inicio").text, "admin ve o botao de atualizar ranking")

r = cli.post("/tema", data={"tema": "b"}, headers={"referer": "https://testserver/pontos"}, follow_redirects=False)
check(r.headers["location"] == "/pontos" and "bt_tema=b" in r.headers.get("set-cookie", ""), "troca de tema sem JS volta para a pagina")
r = cli.post("/tema", data={"tema": "b"}, headers={"referer": "https://evil.example/x"}, follow_redirects=False)
check(r.headers["location"] == "/x", "tema nao redireciona para outro site")
for referer in ("https://evil.example//evil.example/x", "https://evil.example/\\evil.example"):
    r = cli.post("/tema", data={"tema": "b"}, headers={"referer": referer}, follow_redirects=False)
    check(r.headers["location"] == "/", f"tema: caminho {urllib.parse.urlsplit(referer).path!r} não vira redirecionamento externo")
cli.cookies.set("bt_tema", "b")
check('data-tema="b"' in cli.get("/inicio").text, "tema B aplicado pelo cookie")
cli.cookies.set("bt_tema", "<script>")
check('data-tema="a"' in cli.get("/inicio").text, "tema invalido volta ao A")

r = outro.get("/inicio", follow_redirects=False)
check(r.status_code == 200, "login em outro aparelho")
token = csrf_de(cli.get("/perfil").text)
r = cli.post("/perfil/senha", data={"csrf": token, "senha_atual": "senhaforte9", "senha_nova": "novasenha12", "senha_nova2": "novasenha12"}, follow_redirects=False)
check(r.status_code == 303, "troca senha pela web")
check(cli.get("/inicio", follow_redirects=False).status_code == 200, "quem trocou continua logado")
check(outro.get("/inicio", follow_redirects=False).status_code == 303, "outro aparelho foi deslogado")
r = cli.post("/perfil", data={"csrf": token, "nome": "", "genero": "M"})
check(r.status_code == 400 and "Informe o nome" in r.text, "perfil invalido mostra erro")
html_ok(r.text, "perfil com erro")
for i in range(5):
    r = outro.post("/entrar", data={"email": "lucas@ex.com", "senha": "errada999"})
check("bloqueada" in r.text, "bloqueio apos 5 erros pela web")
conn.execute("UPDATE atletas SET bloqueado_ate = NULL"); conn.commit()

print("== limites contra abuso ==")
web._FALHAS_IP.clear()
anonimo = TestClient(web.app, base_url="https://testserver")
for i in range(web.FALHAS_POR_IP):
    r = anonimo.post("/entrar", data={"email": f"naoexiste{i}@ex.com", "senha": "qualquer123"})
check(r.status_code == 400, f"{web.FALHAS_POR_IP} logins errados com e-mails diferentes: ainda responde")
r = anonimo.post("/entrar", data={"email": "lucas@ex.com", "senha": "novasenha12"})
check(r.status_code == 429 and "Muitas tentativas" in r.text, "depois do limite, o mesmo endereço é barrado (até com a senha certa)")
check(anonimo.post("/cadastro", data={**form, "convite": "BT-AAAA-AAAA"}).status_code == 429, "o limite vale também para adivinhar convites")
web._FALHAS_IP.clear()
check(anonimo.post("/entrar", data={"email": "lucas@ex.com", "senha": "novasenha12"}, follow_redirects=False).status_code == 303,
      "passada a janela, entra normalmente")
check(web.origem_do_pedido(type("R", (), {"client": type("C", (), {"host": "2804:18:1908:99d6:b4dd:6a94:c791:afe3"})()})())
      == "2804:18:1908:99d6::/64", "IPv6 conta pela rede /64")
r = anonimo.post("/entrar", content=b"email=a&senha=" + b"x" * (web.MAX_CORPO_BYTES + 10),
                 headers={"content-type": "application/x-www-form-urlencoded"})
check(r.status_code == 413, "envio maior que o limite é recusado (413)")
def _gerador():
    for _ in range(web.MAX_CORPO_BYTES // 65536 + 2):
        yield b"x" * 65536
r = anonimo.post("/entrar", content=_gerador(), headers={"content-type": "application/x-www-form-urlencoded"})
check(r.status_code == 413, "envio grande sem Content-Length também é recusado")
check(itf_dados.ler_chave("../../atletas") is None and itf_dados.ler_chave("B-TOUR-BRA-2026-068") is not None,
      "chave de torneio com '..' não vira caminho de arquivo")
try:
    itf_dados._arquivo_chave("../x"); check(False, "caminho com .. aceito")
except ValueError:
    check(True, "gravar chave com caractere inválido é recusado")
check(itf_dados.ler_calendario() is itf_dados.ler_calendario(), "calendário fica em memória entre pedidos")

check(cli.get("/sw.js").headers["content-type"].startswith("text/javascript"), "service worker servido na raiz")
check(json.loads(cli.get("/manifest.webmanifest").text)["name"] == "BT Ranking", "manifesto do PWA")
check(cli.get("/offline").status_code == 200, "pagina offline")
r = cli.get("/naoexiste")
check(r.status_code == 404 and "Página não encontrada" in r.text, "404 com pagina propria")
r = cli.post("/sair", data={"csrf": token}, follow_redirects=False)
check(r.status_code == 303 and cli.get("/inicio", follow_redirects=False).status_code == 303, "sair encerra a sessao")
conn.close()
fim()
