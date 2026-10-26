"""Ranking da semana: quando conferir, quando baixar, e o app nunca trocar um
ranking completo por um pela metade. Sem rede: o navegador e a coleta da ITF
sao trocados por versoes falsas, e os rankings ficam numa pasta temporaria."""
import datetime
import json
import pathlib
import tempfile
import time

from _base import check, fim
import itf_beach_tennis_tierlist as itf
import itf_dados

# Rankings desta bateria numa pasta propria (nunca os de verdade).
itf.CACHE_DIR = pathlib.Path(tempfile.mkdtemp())

import web

D = datetime.datetime
JOGADORES = [{"playerId": i, "playerGivenName": f"Nome{i}", "playerFamilyName": f"SOBRENOME{i}",
              "rank": i, "points": 1000 - i, "playerNationalityCode": "BRA"} for i in range(1, 31)]


def gravar(genero, rank_date, completo=True, jogadores=JOGADORES):
    itf.gravar_cache(genero, jogadores, len(jogadores), rank_date, completo)


print("== quando o ranking esta atrasado ==")
check(web.segunda_do_ranking(D(2026, 10, 25, 12)) == datetime.date(2026, 10, 19), "domingo: vale o ranking da segunda passada")
check(web.segunda_do_ranking(D(2026, 10, 26, 9)) == datetime.date(2026, 10, 19), "segunda antes das 10h: ainda o da semana passada")
check(web.segunda_do_ranking(D(2026, 10, 26, 10, 30)) == datetime.date(2026, 10, 26), "segunda depois das 10h: o desta segunda")
check(web.segunda_do_ranking(D(2026, 10, 29, 8)) == datetime.date(2026, 10, 26), "quinta: o da segunda desta semana")
check(web.ranking_atrasado("W", D(2026, 10, 25, 12)), "sem arquivo: atrasado")
gravar("M", "19 October 2026")
check(not web.ranking_atrasado("M", D(2026, 10, 25, 12)), "ranking de 19/10 no domingo 25: em dia")
check(web.ranking_atrasado("M", D(2026, 10, 26, 11)), "segunda 26 às 11h com o de 19/10: atrasado")
check(web.ranking_atrasado("M", D(2026, 10, 28, 15)), "PC desligado na segunda e terça: quarta ainda atrasado")
gravar("M", "26 October 2026", completo=False)
check(web.ranking_atrasado("M", D(2026, 10, 27, 11)), "ranking novo mas incompleto: atrasado")

print("== relogio: so busca quando precisa, com intervalo ==")
iniciadas = []
ocupado = [False]
def falso_iniciar(nome, funcao, *args):
    if ocupado[0]:
        return False
    iniciadas.append((nome, funcao, args))
    return True
web.iniciar_tarefa = falso_iniciar
gravar("M", "19 October 2026"); gravar("W", "19 October 2026")
check(not web.verificar_ranking_da_semana(D(2026, 10, 25, 12)) and not iniciadas, "domingo com tudo em dia: não busca")
seg = D(2026, 10, 26, 10, 15)
check(web.verificar_ranking_da_semana(seg) and iniciadas[-1][2] == (("M", "W"),)
      and iniciadas[-1][1] is itf_dados.atualizar_rankings, "segunda 10h15: busca os dois rankings")
check(not web.verificar_ranking_da_semana(seg + datetime.timedelta(hours=2)) and len(iniciadas) == 1,
      "2h depois (ITF ainda sem o novo): espera")
check(web.verificar_ranking_da_semana(seg + datetime.timedelta(hours=3, minutes=1)) and len(iniciadas) == 2,
      "3h depois: tenta de novo")
gravar("M", "26 October 2026")
check(web.verificar_ranking_da_semana(seg + datetime.timedelta(hours=7)) and iniciadas[-1][2] == (("W",),),
      "masculino já novo: busca só o feminino")
quinta = D(2026, 10, 29, 9)
check(web.verificar_ranking_da_semana(quinta) and len(iniciadas) == 4, "quinta (semana sem ranking novo do feminino): busca")
check(not web.verificar_ranking_da_semana(quinta + datetime.timedelta(hours=6)) and len(iniciadas) == 4,
      "de quarta em diante o intervalo é de 12h")
ocupado[0] = True
antes = itf_dados.ultima_tentativa_ranking()
check(not web.verificar_ranking_da_semana(quinta + datetime.timedelta(hours=13))
      and itf_dados.ultima_tentativa_ranking() == antes, "outra busca rodando: não marca tentativa, confere na próxima volta")
ocupado[0] = False
gravar("W", "26 October 2026")
check(not web.verificar_ranking_da_semana(quinta + datetime.timedelta(hours=14)), "tudo em dia: não busca mais na semana")

print("== atualizar_ranking: so baixa quando a ITF publicou outro ==")
publicado = ["26 October 2026"]
coletas = []
class ColetorFalso:
    def __enter__(self):
        self.sessao = object()
        return self
    def __exit__(self, *_):
        pass
    def buscar(self, url):
        assert "take=10&skip=0" in url
        return {"items": [], "rankDate": publicado[0]}
itf_dados.ColetorITF = ColetorFalso
modo_coleta = ["completa"]
def coleta_falsa(sessao, genero):
    coletas.append(genero)
    completa = modo_coleta[0] == "completa"
    jogadores = JOGADORES if completa else JOGADORES[:12]
    gravar(genero, publicado[0], completo=completa, jogadores=jogadores)
    return jogadores
itf.coletar_ranking = coleta_falsa
gravar("M", "26 October 2026")
check(itf_dados.atualizar_ranking("M") == "em_dia" and coletas == [], "ITF com a mesma data: não baixa (só a 1ª página)")
publicado[0] = "02 November 2026"
check(itf_dados.atualizar_ranking("M") == "baixado" and coletas == ["M"]
      and itf.ler_cache("M")["rank_date"] == "02 November 2026", "ITF com ranking novo: baixa e grava")
modo_coleta[0] = "parcial"; publicado[0] = "09 November 2026"
try:
    itf_dados.atualizar_ranking("M"); check(False, "coleta pela metade passou como ok")
except itf_dados.ErroColetaITF as exc:
    check("parou no meio" in str(exc), "coleta pela metade: erro (e a próxima tentativa continua)")
check(web.ranking_atrasado("M", D(2026, 11, 10, 12)), "incompleto continua atrasado para o relógio")
modo_coleta[0] = "completa"
falhas = []
original = itf_dados.atualizar_ranking
def um_falha(genero):
    if genero == "M":
        raise itf_dados.ErroColetaITF("Incapsula")
    falhas.append(genero)
    return "baixado"
itf_dados.atualizar_ranking = um_falha
try:
    itf_dados.atualizar_rankings(("M", "W")); check(False, "erro do masculino sumiu")
except itf_dados.ErroColetaITF as exc:
    check(falhas == ["W"] and "masculino: Incapsula" in str(exc), "masculino falhou e o feminino foi baixado mesmo assim")
itf_dados.atualizar_ranking = original

print("== o app nunca troca o ranking completo por um pela metade ==")
web._RANKINGS.clear()
gravar("M", "26 October 2026")
check(web.dados_ranking("M")["rank_date"] == "26 October 2026", "carrega o ranking completo")
time.sleep(0.02)
gravar("M", "02 November 2026", completo=False, jogadores=JOGADORES[:15])
check(web.dados_ranking("M")["rank_date"] == "26 October 2026" and len(web.dados_ranking("M")["jogadores"]) == 30,
      "arquivo novo incompleto: continua mostrando o completo anterior")
time.sleep(0.02)
itf.arquivo_cache("M").write_text('{"jogadores": [', encoding="utf-8")
check(web.dados_ranking("M")["rank_date"] == "26 October 2026", "arquivo ilegível: continua com o completo anterior")
time.sleep(0.02)
gravar("M", "02 November 2026")
check(web.dados_ranking("M")["rank_date"] == "02 November 2026", "chegou o novo completo: troca")
check(not list(itf.CACHE_DIR.glob("*.tmp")) and json.loads(itf.arquivo_cache("M").read_text(encoding="utf-8"))["completo"],
      "gravação do ranking é atômica (sem .tmp sobrando)")
web._RANKINGS.clear()
gravar("W", "02 November 2026", completo=False, jogadores=JOGADORES[:15])
check(len(web.dados_ranking("W")["jogadores"]) == 15, "sem ranking completo na memória (servidor recém-ligado): usa o parcial")

print("== botao do administrador usa a mesma regra ==")
import re
from fastapi.testclient import TestClient
import atletas
conn = atletas.conectar()
convite = atletas.criar_convite(conn)
cli = TestClient(web.app, base_url="https://testserver")
cli.post("/cadastro", data={"convite": convite, "email": "adm@ex.com", "senha": "senhaforte9", "senha2": "senhaforte9",
                            "nome": "Admin", "genero": "M", "nome_itf": "", "ano_nascimento": "", "nacionalidade": "", "cidade": ""})
atletas.definir_admin(conn, "adm@ex.com")
r = cli.get("/inicio")
check("atualiza sozinho toda segunda" in r.text, "início avisa que o ranking atualiza sozinho")
token = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
iniciadas.clear()
r = cli.post("/ranking/atualizar", data={"csrf": token, "genero": "M"}, follow_redirects=False)
check(r.status_code == 303 and iniciadas and iniciadas[-1][1] is itf_dados.atualizar_ranking and iniciadas[-1][2] == ("M",),
      "botão 'Atualizar ranking' confere a data na ITF antes de baixar")
web._TAREFAS["ranking:M"] = {"rodando": False, "ok": True, "resultado": "em_dia"}
check("já é o mais novo da ITF" in cli.get("/inicio").text, "ranking já em dia: o administrador fica sabendo")
web._TAREFAS["ranking:semana"] = {"rodando": True, "inicio": time.time()}
check("Baixando o ranking novo da semana" in cli.get("/inicio").text, "administrador vê a atualização automática rodando")
conn.close()

import threading
def relogio_vivo():
    return any(t.name == "ranking-da-semana" and t.is_alive() for t in threading.enumerate())
with TestClient(web.app, base_url="https://testserver"):
    check(relogio_vivo(), "o relógio do ranking liga junto com o servidor")
time.sleep(0.2)
check(not relogio_vivo(), "e para quando o servidor desliga")
fim()
