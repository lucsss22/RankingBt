# Contexto para continuar em outro chat

Cole este arquivo inteiro na primeira mensagem do chat novo.

---

## Quem sou e o que e o trabalho

Sou Lucas, 3o periodo da PUCPR. Estou terminando o **trabalho final de
PSE102A - Seguranca da Informacao**, sozinho (equipe individual).
**Entrega: 27/11/2026, improrrogavel, pelo Canvas.**

O projeto e o **RankingBt**: um app web de ranking de beach tennis em
Python/FastAPI. **O codigo original do app foi 100% gerado por IA** - isso e
declarado abertamente no trabalho. O que eu fiz foi a **camada de seguranca**,
com a IA explicando e orientando, nao escrevendo por mim.

## Como quero que voce trabalhe comigo

**Nao edite o codigo por mim.** Explique cada etapa, revise o que eu escrever e
me ajude a corrigir. Se precisar mexer em arquivo de infraestrutura ou
documentacao, pode - mas em codigo de seguranca eu digito.

Duas outras coisas que me ajudam muito:

1. **Rotule tudo que me manda.** Use `RODAR NO TERMINAL` para comando e
   `CONTEUDO DE ARQUIVO` para texto que vai dentro de um arquivo. Eu ja colei
   conteudo de arquivo no PowerShell por falta de rotulo.
2. **Nao presuma que eu entendo a saida dos comandos.** Eu nao entendo. Traduza
   o que apareceu na tela para portugues simples antes de seguir.

## Onde esta tudo

- Pasta: `C:\Users\lucas\Desktop\Prog\PUCpr\3P\SI\RankingBt`
- Branch: `trabalho-seguranca`
- Repo: `https://github.com/lucsss22/RankingBt/tree/trabalho-seguranca`
- Windows 11, PowerShell. Docker Desktop rodando.
- `openssl` ja esta no `$PROFILE` como alias permanente (vem do Git).
- No PowerShell, `curl` e o `Invoke-WebRequest` - tenho que usar `curl.exe`.

## O que eu construi (tudo funcionando e commitado)

| Area | Arquivo | O que faz |
|---|---|---|
| PKI propria | `gerar_certificados.py` | CA raiz do projeto, CSR, cert do servidor com SAN |
| HTTPS | `infra/nginx/rankingbt.conf` | TLS 1.2/1.3, redirect 301, 7 cabecalhos de seguranca, HSTS |
| Log assinado | `auditoria.py` | cadeia HMAC-SHA256, cada MAC inclui o anterior + numero de sequencia; neutraliza CWE-117 |
| Deteccao + bloqueio | `vigia.py` | le o log, conta falhas por IP, bloqueia no iptables (5 falhas / 600s -> DROP 900s) |
| Segmentacao | `docker-compose.yml` | duas redes (172.28.0.0/24 interna, 172.29.0.0/24 externa), 4 conteineres |
| Endurecimento | `Dockerfile` | usuario `atleta` uid 10001, `cap_drop ALL`, proxy-headers |
| Instrumentacao | `web.py` | 6 pontos chamando `auditoria.registrar(...)` |

Commits na branch: `95a31d7` (HTTPS/PKI/segmentacao), `adadf6b` (log de
auditoria), `7e0b682` (bloqueio no firewall), `dd4eb15` (reprodutibilidade).

Ja tem senha com **PBKDF2-SHA256 600k iteracoes**, cookie de sessao
`HttpOnly + Secure + SameSite=Lax`, token CSRF e controle de acesso por papel -
isso era do app base (RA1).

## Documentos de apoio que ja existem na pasta

- `README.md` - requisitos, instalacao, execucao, tabela T01-T13 de evidencias
- `ROTEIRO-VIDEO.md` - roteiro do video em 5 blocos cronometrados
- `ENTENDER-AS-SAIDAS.md` - traducao em portugues de cada tipo de saida
- `TESTES-NO-NAVEGADOR.md` - 7 demos sem terminal (o melhor: `document.cookie`
  mostra `bt_tema` e nao mostra `bt_sessao`, provando o HttpOnly)
- `demo/*.sh` - 4 scripts: `captura-http.sh`, `captura-https.sh`, `ataque.sh`,
  `adulterar.sh`

Estes quatro `.md` e a pasta `demo/` **ainda nao estao commitados**, junto com
uma alteracao no `docker-compose.yml` (montagem da pasta `demo` nos conteineres
`app` e `atacante`).

## Duas limitacoes honestas que eu vou declarar no trabalho

1. **Truncar o fim do log nao e detectado.** Se apagarem as ultimas linhas, o
   que sobra e um prefixo valido da cadeia. O verificador nao sabe quantas
   linhas deveria ter.
2. **Log vazio verifica como intacto**, pela mesma razao.

Mitigacao que vou propor: ancorar o ultimo MAC em um canal independente.

Terceira: o `vigia.py` usa `iptables`, que e IPv4 - **nao bloqueia IPv6**.

## O que FALTA fazer (e e urgente, entrego amanha)

1. **Gravar o video** - maximo 10 minutos, 720p, camera ligada, YouTube nao
   listado ou nuvem com acesso para `luis.gonzaga@pucpr.br`.
   O roteiro esta pronto em `ROTEIRO-VIDEO.md`.
2. **Escrever o documento-resumo em PDF** com as **11 secoes obrigatorias** do
   enunciado. **Nao comecei.** E a maior pendencia.
3. **Confirmar que o repositorio esta publico** (abrir o link numa janela
   anonima).
4. **Commitar** os `.md` de apoio, a pasta `demo/` e o `docker-compose.yml`.
5. **Enviar no Canvas** (PDF + link do video + link do repositorio).

## Mapeamento RA (para o documento)

- **RA1** - autenticacao e controle de acesso (ja existia no app base)
- **RA2** - criptografia (PKI, TLS, HMAC, PBKDF2)
- **RA3** - deteccao, prevencao e endurecimento (log, vigia, firewall, redes,
  capabilities, cabecalhos)

**Somativa 02 = RA2 + RA3.**

## Um aviso pratico

**Nao erro a senha 5 vezes pelo navegador.** O vigia ve o IP do gateway do
Docker e me bloqueia. Se acontecer:

    docker exec bt-defesa iptables -L INPUT -n
    docker exec bt-defesa iptables -D INPUT -s <o ip> -j DROP

A forca bruta tem que ser de dentro do `bt-atacante`.

---

## Por onde comecar no chat novo

Me ajude a **escrever o documento-resumo em PDF com as 11 secoes
obrigatorias**. E o que falta e nao comecei. Depois disso, gravar o video.

**Importante:** junto com este arquivo, cole tambem o **enunciado do trabalho**
no chat novo. Ele e quem lista as 11 secoes obrigatorias, e sem ele o chat novo
nao sabe o que o documento tem que conter.
