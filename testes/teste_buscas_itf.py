"""Busca dos resultados do atleta na ITF: os torneios aparecem assim que
chegam, e as chaves (ajuste fino) tem tempo e sessoes novas limitados para nao
prender a fila quando o Incapsula bloqueia. Sem rede: navegador falso."""
import datetime
import json
import re
import time

from _base import DADOS_ITF, check, fim
import itf_beach_tennis_tierlist as itf
import itf_dados
import pontuacao

PID = 800767267
ATIVIDADE = json.load(open(DADOS_ITF / f"atividade_{PID}.json", encoding="utf-8"))
CALENDARIO = json.load(open(DADOS_ITF / "calendario_amostra.json", encoding="utf-8"))["items"]
itf_dados._gravar(itf_dados.ARQUIVO_CALENDARIO, {"coletado_em": time.time(), "torneios": CALENDARIO})

eventos = []           # o que aconteceu, em ordem
bloquear_chave = [None]  # numero da chave (1, 2, ...) em que a ITF bloqueia de vez
lentidao = [0.0]       # segundos que cada chave "demora"


class SessaoFalsa:
    rotacoes = 0


class ColetorFalso:
    def __enter__(self):
        self.sessao = SessaoFalsa()
        self.chaves = 0
        return self

    def __exit__(self, *_):
        pass

    def buscar(self, url):
        if "GetPlayerActivity" in url:
            eventos.append("atividade")
            return ATIVIDADE
        if "GetEventFilters" in url:
            self.chaves += 1
            eventos.append(f"chave{self.chaves}:rotacoes={self.sessao.rotacoes}")
            if bloquear_chave[0] == self.chaves:
                raise itf_dados.ErroColetaITF("A ITF não respondeu.")
            time.sleep(lentidao[0])
            return {"filters": []}   # chave ainda nao publicada
        raise AssertionError(f"busca inesperada: {url}")


itf_dados.ColetorITF = ColetorFalso
DATA_REF = datetime.date(2026, 10, 19)


def rodar():
    eventos.clear()
    return itf_dados.atualizar_atividade(PID, "M", pontuacao.carregar_tabela(), DATA_REF,
                                         ao_salvar_atividade=lambda: eventos.append("pode_mostrar"))


def limpar_chaves():
    for arquivo in (itf_dados.PASTA_CACHE / "chaves").glob("*.json"):
        arquivo.unlink()


print("== os torneios aparecem antes das chaves ==")
faltam = rodar()
chaves = [e for e in eventos if e.startswith("chave")]
check(eventos[:2] == ["atividade", "pode_mostrar"] and chaves, f"atividade gravada e liberada antes das {len(chaves)} chaves")
check(itf_dados.ler_atividade(PID) is not None and faltam == 0, "sem bloqueio: busca todas as chaves pendentes")
check(all(e.endswith(f"rotacoes={itf.MAX_ROTACOES - itf_dados.ROTACOES_PARA_CHAVES}") for e in chaves),
      f"as chaves só podem abrir {itf_dados.ROTACOES_PARA_CHAVES} sessões novas")
pendentes = len(chaves)

print("== ITF bloqueando: as chaves param e ficam para depois ==")
limpar_chaves()
bloquear_chave[0] = 2
faltam = rodar()
check(faltam == pendentes - 1 and len([e for e in eventos if e.startswith("chave")]) == 2,
      f"bloqueou na 2ª chave: para ali, sem erro, e {faltam} ficam para a próxima")
bloquear_chave[0] = None

print("== limite de tempo das chaves ==")
limpar_chaves()
itf_dados.SEGUNDOS_PARA_CHAVES = 0.05
lentidao[0] = 0.06
faltam = rodar()
check(len([e for e in eventos if e.startswith("chave")]) == 1 and faltam == pendentes - 1,
      "passado o tempo, não começa outra chave")
itf_dados.SEGUNDOS_PARA_CHAVES, lentidao[0] = 90, 0.0

print("== no app: a tela libera assim que os torneios chegam ==")
import web
import atletas
from fastapi.testclient import TestClient

durante = {}
def atividade_falsa(player_id, genero, tabela, data_ref, ao_salvar_atividade=None):
    ao_salvar_atividade()
    durante["atividade"] = web.tarefa_rodando(f"atividade:{player_id}")
    durante["chaves"] = web.tarefa_rodando(f"chaves:{player_id}")
    durante["outra"] = web.iniciar_tarefa("calendario", lambda: None)
    durante["pagina"] = cli.get("/perfil").text
    return 3
web.itf_dados.atualizar_atividade = atividade_falsa

conn = atletas.conectar()
cli = TestClient(web.app, base_url="https://testserver")
cli.post("/cadastro", data={"convite": atletas.criar_convite(conn), "email": "a@ex.com", "senha": "senhaforte9",
                            "senha2": "senhaforte9", "nome": "Atleta", "genero": "M", "nome_itf": "",
                            "ano_nascimento": "", "nacionalidade": "", "cidade": ""})
atletas.vincular_itf(conn, conn.execute("SELECT id FROM atletas").fetchone()[0], PID, "Atleta")
web._TAREFAS[f"atividade:{PID}"] = {"rodando": True, "inicio": time.time()}
check(web.buscar_resultados_itf(PID, "M", DATA_REF) == 3, "a busca roda inteira e diz quantas chaves ficaram")
check(durante["atividade"] is False, "com os torneios gravados, a busca do atleta já aparece como terminada")
check(durante["chaves"] is True and durante["outra"] is False,
      "as chaves continuam segurando a vez: outra busca na ITF espera")
check("Seus torneios já estão abaixo" in durante["pagina"] and "Buscando seus torneios" not in durante["pagina"]
      and 'action="/perfil/resultados/atualizar"' not in durante["pagina"],
      "o perfil mostra os torneios com um aviso discreto, sem 'buscando'")
check(not web.tarefa_rodando(f"chaves:{PID}"), "terminadas as chaves, libera a vez")
r = cli.get("/perfil")
check("Seus torneios já estão abaixo" not in r.text and 'action="/perfil/resultados/atualizar"' in r.text,
      "depois volta o botão de atualizar")
token = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
web._TAREFAS.clear()
itf_dados._gravar(itf_dados._arquivo_atividade(PID), {"coletado_em": 0, "itens": []})
r = cli.post("/perfil/resultados/atualizar", data={"csrf": token}, follow_redirects=False)
check(r.status_code == 303 and "aguardar=1" in r.headers["location"], "o botão inicia a busca")
for _ in range(50):
    if not web.tarefa_rodando(f"atividade:{PID}") and not web.tarefa_rodando(f"chaves:{PID}"):
        break
    time.sleep(0.05)
check(web.estado_tarefa(f"atividade:{PID}").get("ok") and web.estado_tarefa(f"atividade:{PID}").get("resultado") == 3,
      "pelo botão, a tarefa termina bem")
conn.close()
fim()
