"""Testes dos modulos: atletas (conta, login, resultados), pontuacao e
estimativa. Os 44 testes originais."""
import json, tempfile, time, pathlib
from _base import PASTA, check, fim
import atletas, pontuacao, estimativa

print("== atletas ==")
tmp = pathlib.Path(tempfile.mkdtemp()) / "t.db"
conn = atletas.conectar(tmp)
check(conn.execute("PRAGMA user_version").fetchone()[0] == max(atletas.MIGRACOES), "esquema na versao atual")
try:
    atletas.cadastrar(conn, {"email": "x", "nome": "A", "genero": "Z", "nome_itf": "Lucas",
                             "ano_nascimento": "1800", "nacionalidade": "BR"}, "123")
    check(False, "cadastro invalido deveria falhar")
except atletas.ErroValidacao as e:
    check(set(e.erros) == {"email", "senha", "nome", "genero", "nome_itf", "ano_nascimento", "nacionalidade"},
          f"todos os erros juntos: {sorted(e.erros)}")
a = atletas.cadastrar(conn, {"email": " Lucas@Ex.com ", "nome": "Lucas  Cobucci", "genero": "M",
                             "nome_itf": "COBUCCI Lucas", "ano_nascimento": "2000", "nacionalidade": "bra"}, "senhaforte9")
check(a.email == "lucas@ex.com" and a.nome == "Lucas Cobucci" and a.nacionalidade == "BRA", "normaliza email/nome/nacionalidade")
h = conn.execute("SELECT senha_hash FROM atletas").fetchone()[0]
check(h.startswith("pbkdf2_sha256$600000$") and "senhaforte9" not in h, "senha guardada so como hash")
for senha, campo in (("12345678", "comum"), ("lucas@ex.com", "igual email")):
    try:
        atletas.validar_senha(senha, "lucas@ex.com"); check(False, f"senha {campo} aceita")
    except atletas.ErroValidacao:
        check(True, f"senha {campo} recusada")
try:
    atletas.cadastrar(conn, {"email": "LUCAS@ex.com", "nome": "Outro", "genero": "M"}, "outrasenha1")
    check(False, "email duplicado aceito")
except atletas.ErroValidacao as e:
    check("email" in e.erros, "email duplicado recusado (sem diferenciar maiusculas)")
check(atletas.autenticar(conn, "LUCAS@EX.COM", "senhaforte9").id == a.id, "login ok")
for email, senha in (("lucas@ex.com", "errada123"), ("naoexiste@ex.com", "errada123")):
    try:
        atletas.autenticar(conn, email, senha); check(False, "login errado aceito")
    except atletas.ErroLogin as e:
        check(str(e) == "E-mail ou senha incorretos.", f"mensagem igual p/ {email}")
t0 = time.perf_counter()
try:
    atletas.autenticar(conn, "naoexiste@ex.com", "x")
except atletas.ErroLogin:
    pass
dt_inex = time.perf_counter() - t0
t0 = time.perf_counter()
try:
    atletas.autenticar(conn, "lucas@ex.com", "x")
except atletas.ErroLogin:
    pass
dt_ex = time.perf_counter() - t0
check(dt_inex > 0.5 * dt_ex, f"tempo parecido com e sem conta ({dt_inex:.2f}s vs {dt_ex:.2f}s)")
# ja houve 2 falhas na conta; mais 3 bloqueiam
ultima = ""
for i in range(3):
    try:
        atletas.autenticar(conn, "lucas@ex.com", "errada123")
    except atletas.ErroLogin as e:
        ultima = str(e)
check("bloqueada" in ultima, "bloqueia na 5a falha")
try:
    atletas.autenticar(conn, "lucas@ex.com", "senhaforte9"); check(False, "login com conta bloqueada")
except atletas.ErroLogin as e:
    check("bloqueada" in str(e), "senha certa nao entra durante o bloqueio")
conn.execute("UPDATE atletas SET bloqueado_ate = ?", (time.time() - 1,)); conn.commit()
check(atletas.autenticar(conn, "lucas@ex.com", "senhaforte9").id == a.id, "entra depois do bloqueio")
conn.execute("UPDATE atletas SET senha_hash = ?", (atletas.gerar_hash_senha("senhaforte9", 1000),)); conn.commit()
atletas.autenticar(conn, "lucas@ex.com", "senhaforte9")
check("$600000$" in conn.execute("SELECT senha_hash FROM atletas").fetchone()[0], "hash antigo refeito no login")
a = atletas.vincular_itf(conn, a.id, 123, "COBUCCI Lucas")
b = atletas.cadastrar(conn, {"email": "b@ex.com", "nome": "Bia", "genero": "W"}, "senhadabia1")
try:
    atletas.vincular_itf(conn, b.id, 123, "X Y"); check(False, "mesmo playerId em duas contas")
except atletas.ErroValidacao:
    check(True, "playerId nao vincula em duas contas")
a = atletas.atualizar_perfil(conn, a.id, {"cidade": "Curitiba", "email": "hack@ex.com", "senha_hash": "x"})
check(a.cidade == "Curitiba" and a.email == "lucas@ex.com" and a.itf_player_id == 123, "edicao so mexe em campos do perfil")
a = atletas.atualizar_perfil(conn, a.id, {"genero": "W"})
check(a.itf_player_id is None, "trocar genero desfaz o vinculo ITF")
try:
    atletas.alterar_senha(conn, a.id, "errada", "novasenha1"); check(False, "troca com senha atual errada")
except atletas.ErroValidacao:
    check(True, "troca de senha exige a atual")
atletas.alterar_senha(conn, a.id, "senhaforte9", "novasenha1")
check(atletas.autenticar(conn, "lucas@ex.com", "novasenha1").id == a.id, "login com a senha nova")
rid = atletas.registrar_resultado(conn, a.id, {"torneio": "BT200 Curitiba", "pontos": 72, "origem": "colocacao",
                                               "categoria": "BT200", "data": "2026-10-12"})
for ruim in ({"torneio": "", "pontos": 1, "origem": "pontos"}, {"torneio": "x", "pontos": -1, "origem": "pontos"},
             {"torneio": "x", "pontos": 1, "origem": "chute"},
             {"torneio": "x", "pontos": 1, "origem": "pontos", "data": "12/10/2026"}):
    try:
        atletas.registrar_resultado(conn, a.id, ruim); check(False, f"resultado invalido aceito {ruim}")
    except atletas.ErroValidacao:
        pass
check(len(atletas.listar_resultados(conn, a.id)) == 1, "resultados invalidos recusados")
check(not atletas.excluir_resultado(conn, b.id, rid), "nao apaga resultado de outro atleta")
check(atletas.excluir_resultado(conn, a.id, rid) and not atletas.listar_resultados(conn, a.id), "apaga o proprio")
conn.close()

print("== pontuacao ==")
tab = pontuacao.carregar_tabela(PASTA / "pontuacao_itf_2026.json")
r = pontuacao.rodadas_com_pontos(tab, "BT200", "32x32")
check([x["pontos"] for x in r["principal"]] == [200, 120, 72, 36, 18, 9], "BT200 32x32 chave principal")
check([(x["codigo"], x["pontos"]) for x in r["qualifying"]] == [("FRQ", 5), ("R1", 2)], "BT200 32x32 qualifying (R2 nao existe)")
check(r["principal"][2]["bundles"] == {"TV": 7, "HOSPITALITY": 3, "OFFICIATING": 2}, "bundles BT200 na SF")
c = pontuacao.calcular_pontos(tab, "BT400", "32x32", "principal", "SF", ["TV", "OFFICIATING"])
check(c.total == 144 + 14 + 4, f"BT400 SF + TV + Officiating = {c.total}")
c = pontuacao.calcular_pontos(tab, "BT100", "32x32", "principal", "R32/24", [], "W")
check(c.total == 5 + 3, f"BT100 1a rodada + campeao do bonus = {c.total}")
c = pontuacao.calcular_pontos(tab, "BT200", "48x0", "principal", "R48", ["TV"])
check(c.total == 5 and any("R48" in a for a in c.avisos), "R48 sem valor de bundle vira aviso")
c = pontuacao.calcular_pontos(tab, "BT10", "32x32", "principal", "R32/24")
check(c.total == 0 and c.avisos, "rodada sem pontos (null) = 0 com aviso")
for args in (("TOUR_FINALS", "8x0", "principal", "W"), ("BT50", "99x9", "principal", "W"),
             ("BT50", "32x32", "principal", "R48x")):
    try:
        pontuacao.calcular_pontos(tab, *args); check(False, f"deveria recusar {args}")
    except pontuacao.ErroPontuacao:
        check(True, f"recusa {args[:2]} {args[3]}")
check(pontuacao.melhores_resultados(tab) == 10, "regra dos 10 melhores vem da tabela")
total_chaves = sum(len(c["chaves"]) for c in tab["categorias"])
check(total_chaves == 43, f"43 chaves na tabela ({total_chaves})")

print("== estimativa ==")
dados = json.load(open(PASTA / "ranking_itf_M.json", encoding="utf-8"))
rk = dados["jogadores"]
poucos = next(j for j in rk if j["tournamentsPlayed"] < 10 and 100 < j["rank"] < 600)
e = estimativa.estimar_ranking(rk, poucos, 72, 10)
alvo = poucos["points"] + 72
esperado = 1 + sum(1 for j in rk if j["points"] > alvo)
check(e.exata_nos_pontos and e.pontos_max == alvo and e.rank_melhor == esperado,
      f"<10 torneios: #{poucos['rank']} {poucos['points']}pts +72 -> #{e.rank_melhor} {e.pontos_max}pts")
muitos = next(j for j in rk if j["tournamentsPlayed"] >= 10 and 50 < j["rank"] < 300)
e = estimativa.estimar_ranking(rk, muitos, 72, 10)
check(not e.exata_nos_pontos and e.pontos_min < e.pontos_max and e.rank_melhor <= e.rank_pior,
      f">=10 torneios vira faixa: {e.pontos_min}-{e.pontos_max} pts, #{e.rank_melhor}-#{e.rank_pior}")
check(e.pontos_min == muitos["points"] + max(0, 72 - muitos["points"] // 10), "limite inferior = atuais + (novos - media)")
e = estimativa.estimar_ranking(rk, muitos, 72, 10, pior_resultado=30)
check(e.exata_nos_pontos and e.pontos_max == muitos["points"] + 42, "com o pior resultado sai exato")
e = estimativa.estimar_ranking(rk, muitos, 20, 10, pior_resultado=30)
check(e.pontos_max == muitos["points"] and e.rank_melhor == muitos["rank"], "resultado pior que o pior que conta nao muda nada")
e = estimativa.estimar_ranking(rk, None, 9, 10)
check(e.rank_atual is None and e.pontos_max == 9 and e.rank_melhor == 1 + sum(1 for j in rk if j["points"] > 9),
      "fora do ranking entra com os pontos do torneio")
e = estimativa.estimar_ranking(rk, None, 0, 10)
check(e.rank_melhor is None, "0 pontos = sem ranking")
check(estimativa.localizar_atleta(rk, player_id=rk[0]["playerId"]) is rk[0], "acha por playerId")
check(estimativa.localizar_atleta(rk, nome="GIANOTTI Nicolas")["playerId"] == rk[0]["playerId"], "acha pelo nome (match da tierlist)")
fim()
