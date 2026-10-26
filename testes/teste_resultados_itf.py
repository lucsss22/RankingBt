"""Conversao dos dados da ITF em resultados com pontos (resultados_itf), com
respostas reais salvas em testes/dados_itf e casos montados a mao."""
import datetime
import json

from _base import DADOS_ITF, check, fim
import pontuacao
import resultados_itf as R

D = datetime.date
TAB = pontuacao.carregar_tabela()
CAL = {t["tournamentKey"].upper(): t for t in json.load(open(DADOS_ITF / "calendario_amostra.json", encoding="utf-8"))["items"]}

print("== datas e categoria ==")
check(R.datas_do_torneio("23 Oct to 25 Oct 2026") == (D(2026, 10, 23), D(2026, 10, 25)), "datas no mesmo mês")
check(R.datas_do_torneio("28 Sep to 01 Oct 2026") == (D(2026, 9, 28), D(2026, 10, 1)), "datas virando o mês")
check(R.datas_do_torneio("30 Dec to 02 Jan 2027") == (D(2026, 12, 30), D(2027, 1, 2)), "datas virando o ano")
check(R.datas_do_torneio("30 Dec 2025 to 02 Jan 2026") == (D(2025, 12, 30), D(2026, 1, 2)), "datas com os dois anos")
check(R.datas_do_torneio("lixo") == (None, None), "data inválida")
check(R.entrada_no_ranking(D(2026, 10, 25)) == D(2026, 10, 26), "domingo -> segunda seguinte")
check(R.entrada_no_ranking(D(2026, 10, 24)) == D(2026, 10, 26), "sábado -> segunda seguinte")
check(R.entrada_no_ranking(D(2026, 10, 19)) == D(2026, 10, 26), "segunda -> segunda da semana seguinte")
check(R.chave_do_link("/en/tournament/bt200-florianopolis/bra/2026/b-tour-bra-2026-068/") == "B-TOUR-BRA-2026-068", "chave do torneio pelo link")
check(R.categoria_do_torneio("Sand Series X", "SS100") == ("SS100", None), "categoria do calendário")
check(R.categoria_do_torneio("BT200 Florianópolis")[0] == "BT200", "categoria pelo nome")
check(R.categoria_do_torneio("II BT10 Alboraia")[0] == "BT10", "categoria no meio do nome")
check(R.categoria_do_torneio("Beach Tennis World Championships")[0] == "WCH", "Mundial")
check(R.categoria_do_torneio("Sand Series Tour Finals")[0] is None, "Tour Finals não é calculado")
check(R.categoria_do_torneio("Sand Series Maresias")[0] is None, "Sand Series sem calendário fica sem categoria")
check(R.categoria_do_torneio("European Beach Tennis Championships")[0] is None, "campeonato regional sem regra")

print("== rodadas ==")
casos = [(("1st Round", 32), "R32/24"), (("2nd Round", 32), "R16"), (("1st Round", 16), "R16"),
         (("1st Round", 24), "R32/24"), (("Quarter-finals", 32), "QF"), (("Semi-final", 32), "SF"),
         (("Final", 32), "F"), (("1st Round", 48), "R48"), (("2nd Round", 48), "R32/24"), (("3rd Round", 64), "R16")]
erradas = [(e, R.codigo_principal(*e), s) for e, s in casos if R.codigo_principal(*e) != s]
check(not erradas, f"rótulos da chave principal {erradas}")
casos = [(("1st Round", 2), "R1"), (("2nd Round", 2), "FRQ"), (("1st Round", 1), "FRQ"),
         (("2nd Round", 3), "R2"), (("3rd Round", 3), "FRQ")]
erradas = [(e, R.codigo_qualifying(*e)) for e, s in casos if R.codigo_qualifying(*e) != s]
check(not erradas, f"rótulos do qualifying {erradas}")
drawsheet = json.load(open(DADOS_ITF / "drawsheet_bt200_florianopolis_M_M.json", encoding="utf-8"))
check(R.estrutura_do_drawsheet(drawsheet) == {"tamanho": 32, "rodadas": 5}, "chave publicada do BT200 Florianópolis: 32 duplas, 5 rodadas")
check(R.estrutura_do_drawsheet({}) is None, "drawsheet vazio")

def partida(rodada, codigo):
    return {"roundGroup": {"Value": rodada}, "resultCode": codigo}

def evento(*partidas, tipo="Main Draw"):
    return {"drawType": tipo, "matches": list(partidas)}

def r(*partidas, fase=R.PRINCIPAL, tamanho=32, rq=2):
    return R.resultado_do_evento({"matches": list(partidas)}, fase, tamanho, rq)

check(r(partida("Quarter-final", "L"), partida("2nd Round", "W"), partida("1st Round", "W"))["codigo"] == "QF", "perdeu nas quartas")
check(r(partida("Final", "W"), partida("Semi-final", "W"))["codigo"] == "W", "campeão")
check(r(partida("Semi-final", "W"), partida("Quarter-final", "W"))["estado"] == "em_andamento", "venceu a semi e a final não saiu: em andamento")
check(r(partida("Final", ""), partida("Semi-final", "W"))["estado"] == "em_andamento", "final ainda não jogada")
bye = r(partida("2nd Round", "L"), partida("1st Round", "B"))
check(bye["codigo"] == "R32/24", f"bye e derrota na 1ª partida jogada: pontos da rodada anterior ({bye['codigo']})")
check(r(partida("Quarter-final", "L"), partida("2nd Round", "W"), partida("1st Round", "B"))["codigo"] == "QF",
      "bye seguido de vitória: rodada normal")
check(r(partida("Quarter-final", "O"), partida("2nd Round", "W"), partida("1st Round", "W"))["codigo"] == "QF",
      "deu W.O. nas quartas depois de vencer: pontos das quartas")
desistiu = r(partida("1st Round", "O"))
check(desistiu["estado"] == "sem_pontos", "desistiu sem jogar nenhuma partida: não pontua")
check(r(partida("2nd Round", "L"), partida("1st Round", "W"), fase=R.QUALIFYING)["codigo"] == "FRQ", "qualy: perdeu na rodada final")
check(r(partida("2nd Round", "W"), partida("1st Round", "O"), fase=R.QUALIFYING)["estado"] == "classificado", "qualy: classificou (W.O. recebido antes)")

print("== atividade real: Lucas ==")
lucas = json.load(open(DADOS_ITF / "atividade_800767267.json", encoding="utf-8"))["items"]
res = R.resultados_do_atleta(lucas, TAB, CAL, {}, "M")
resumo = R.marcar_contando(res, D(2026, 10, 19), 10)
check(resumo["soma"] == 14 and resumo["contando"] == 5, f"14 pts em 5 resultados = ranking oficial de 19/10/2026 ({resumo['soma']} / {resumo['contando']})")
check(resumo["incertos"] == 0 and resumo["pior"] is None, "nenhum resultado sem cálculo; menos de 10, então não há pior que conta")
por_nome = {}
for x in res:
    por_nome.setdefault(x.torneio, x)
floripa = por_nome["BT200 Florianópolis"]
check(floripa.fase == R.PRINCIPAL and floripa.rodada == "R32/24" and floripa.pontos == 9,
      "veio do qualy e perdeu na 1ª rodada da principal: 9 pts da chave principal")
check(not floripa.ativo and floripa.entrada == D(2026, 10, 26), "torneio desta semana ainda não entrou no ranking de 19/10")
curitiba = por_nome["BT50 Curitiba"]
check(curitiba.rodada == "R16" and curitiba.pontos == 5 and curitiba.conta and curitiba.parceiro,
      f"BT50 Curitiba: oitavas, 5 pts, conta, parceiro {curitiba.parceiro}")
matinhos = por_nome["BT400 Matinhos"]
check(matinhos.fase == R.QUALIFYING and matinhos.pontos == 4 and matinhos.presumido,
      "BT400 Matinhos: 1ª rodada do qualy (4 pts), tamanho presumido")
check(matinhos.vence == D(2027, 2, 8), "vence 52 semanas depois de entrar")

com_chave = R.resultados_do_atleta(lucas, TAB, CAL, {"B-TOUR-BRA-2026-068": {"M": {"principal": {"tamanho": 16, "rodadas": 4}}}}, "M")
floripa16 = next(x for x in com_chave if x.torneio == "BT200 Florianópolis")
check(floripa16.rodada == "R16" and floripa16.pontos == 9 and not floripa16.presumido,
      "com a chave publicada (16) a 1ª rodada vira R16 e deixa de ser presumida")

bt10 = {"tournamentName": "BT10 Teste", "tournamentLink": "/en/tournament/bt10-teste/bra/2026/b-tour-bra-2026-999/",
        "dates": "01 Oct to 03 Oct 2026",
        "events": [evento(partida("1st Round", "L"))]}
p32 = R.resultados_do_atleta([bt10], TAB)[0].pontos
p16 = R.resultados_do_atleta([bt10], TAB, chaves={"B-TOUR-BRA-2026-999": {"M": {"principal": {"tamanho": 16, "rodadas": 4}}}})[0].pontos
check((p32, p16) == (0, 1), f"BT10: 1ª rodada vale 0 na chave de 32 e 1 na de 16 ({p32}, {p16})")

bonus = {"tournamentName": "BT400 Teste", "tournamentLink": "/en/tournament/x/bra/2026/b-tour-bra-2026-998/",
         "dates": "01 Oct to 03 Oct 2026",
         "events": [evento(partida("1st Round", "L")),
                    evento(partida("Final", "W"), partida("Semi-final", "W"), tipo="Consolation Draw")]}
b = R.resultados_do_atleta([bonus], TAB)[0]
check(b.pontos == 18 + 17 and b.bonus_rodada == "W", f"bonus draw soma com a chave principal (18 + 17 = {b.pontos})")

print("== atividade real: Gianotti ==")
gianotti = json.load(open(DADOS_ITF / "atividade_800636282.json", encoding="utf-8"))["items"]
res_g = {x.torneio: x for x in R.resultados_do_atleta(gianotti, TAB, CAL, {}, "M")}
check(res_g["Beach Tennis World Championships"].pontos == 1000, "campeão mundial: 1000")
check(res_g["BT400 Rio de Janeiro"].rodada == "QF" and res_g["BT400 Rio de Janeiro"].pontos == 72, "W.O. nas quartas do BT400 Rio: 72")
check(res_g["BT200 Florianópolis"].situacao == "em_andamento", "torneio em andamento não pontua ainda")
check(res_g["European Beach Tennis Championships"].situacao == "sem_regra", "Europeu fica sem cálculo (RC1/RC2)")
check(res_g["Sand Series Brasília"].categoria == "SS100" and res_g["Sand Series Brasília"].pontos == 800,
      "Sand Series com categoria do calendário: campeão SS100 = 800")

print("== validade ==")
check(sorted(R.pontos_validos(res, D(2026, 10, 19))) == [1, 1, 3, 4, 5], "pontos que valem em 19/10/2026")
check(sorted(R.pontos_validos(res, D(2027, 2, 15))) == [1, 3, 5, 9], "em 15/02/2027 os de fevereiro de 2026 venceram e o BT200 Floripa entrou")
fim()
