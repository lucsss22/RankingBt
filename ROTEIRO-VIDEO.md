# Roteiro do vídeo — PSE102A Projeto Final

Limite: **10:00**. Conteúdo depois disso não é avaliado.
Mínimo 720p, áudio audível, fonte do terminal legível.

---

## Antes de gravar — checklist

- [ ] Fechar o servidor antigo (a janela do `iniciar.bat`, se estiver aberta)
- [ ] Fonte do terminal em **16pt ou mais** (exigência do enunciado)
- [ ] Ambiente limpo: `docker compose down` e depois `docker compose up -d --build`
- [ ] **Duas contas criadas** no ambiente Docker: uma admin, uma comum
- [ ] Liberar IP bloqueado de testes anteriores
- [ ] Abrir **dois terminais**: um para comandos, outro com `docker compose logs -f defesa`
- [ ] Câmera ligada e rosto visível no começo e no fim
- [ ] **Não digitar senha com a tela sendo gravada** — faça login antes de começar

Criar as contas (o convite devolve um código; cadastre-se em `https://localhost/cadastro`):

    docker compose exec app python gerenciar.py convite
    docker compose exec app python gerenciar.py admin SEU_EMAIL

**Reset antes de cada ensaio do bloqueio** — tira a regra do firewall e zera
os contadores do vigia. Leva 4 segundos:

    docker exec bt-defesa iptables -D INPUT -s 172.29.0.40 -j DROP
    docker compose restart defesa

> ⚠️ **Use o PowerShell, não o Git Bash.** No Git Bash o caminho `/demo/...`
> é convertido em caminho do Windows e o comando falha. Essa é a mesma
> armadilha do MSYS que apareceu na geração dos certificados.

**O `openssl` já funciona em qualquer janela do PowerShell.** O apelido ficou
gravado no seu perfil (`Microsoft.PowerShell_profile.ps1`), então vale também
num terminal aberto no meio da gravação. Não precisa rodar nada antes.

Para remover algum dia: é a última linha do arquivo que `$PROFILE` aponta.

**Use sempre `curl.exe`, nunca `curl`.** No PowerShell, `curl` é apelido para
o `Invoke-WebRequest`, que não entende as opções do curl e trava pedindo a
`Uri`. O `curl.exe` é o curl de verdade, que vem no Windows. E no lugar de
`/dev/null` use `NUL`, que é o equivalente do Windows.

Isso vale só para os comandos rodados **no seu PowerShell**. Dentro dos
contêineres (`docker exec ... curl ...`) é Linux, e lá `curl` e `/dev/null`
são os corretos.

---

## 0:00 – 1:00 · Equipe, problema e cenário

**Na câmera, você falando.**

- Nome, matrícula, disciplina, projeto individual.
- O cenário: RankingBt, aplicação web que atletas de beach tennis usam para
  acompanhar ranking e pontuação da ITF. Fica exposta na internet.
- **O ativo protegido:** o banco com e-mails, hashes de senha e sessões dos
  atletas — e a disponibilidade do serviço.
- **Declare já:** "a aplicação-base foi gerada com auxílio de IA; o trabalho
  de segurança é o que vou demonstrar, e a declaração está no documento."
- As cinco propriedades endereçadas: confidencialidade, integridade,
  disponibilidade, autenticidade e não-repúdio.

---

## 1:00 – 3:00 · Arquitetura e mecanismos

**Slide com a topologia, ou o `docker-compose.yml` na tela.**

    atacante ──┐
               ├── externa 172.29.0.0/24 ─── proxy (Nginx, TLS 1.3)
                                               │  + defesa (vigia)
                                 interna 172.28.0.0/24
                                               │
                                              app (FastAPI)

Quatro decisões, uma frase cada:

1. **O app não publica porta.** Só existe na rede interna. Para alcançá-lo, o
   pedido tem que passar pelo proxy.
2. **Duas redes, não uma.** O atacante está na externa e não tem rota até o
   app — segmentação, não apenas ausência de porta.
3. **O proxy tem TLS 1.3 com certificado emitido por uma CA que eu criei.**
   Saí do ngrok de propósito: ali o certificado era de terceiro e eu não
   configurava nada.
4. **O contêiner de defesa roda com uma única capability**, `NET_ADMIN`, e lê
   o log em modo somente leitura.

Mostre `docker compose ps` com os quatro no ar.

---

## 3:00 – 7:00 · A proteção em ação

### 3:00 – 3:40 · TLS e a cadeia de confiança

Navegador em `https://localhost`. **Vai aparecer aviso de certificado.**

> "Esse aviso é o sistema de confiança funcionando. O navegador seguiu a
> cadeia, chegou na minha CA, não a encontrou na lista de autoridades do
> sistema operacional e desconfiou. Está certo em desconfiar."

Prossiga pelo aviso e mostre o app carregado, já logado.

### 3:40 – 4:30 · A PKI por dentro

    "" | openssl s_client -connect localhost:443 -CAfile infra/ca/ca.crt | Select-String "Protocol  :","Cipher    :","Verify return code","issuer="

Sai filtrado, só o que importa: **`issuer=... CN=RankingBt Root CA`**,
**`Verify return code: 0 (ok)`**, **`Protocol: TLSv1.3`** e a cifra negociada.
Aparecem também as linhas `depth=1` e `depth=0` — são os dois degraus da
cadeia sendo validados, da raiz até o servidor. Vale apontar.

> "Validando contra a minha CA, a cadeia fecha. O certificado é legítimo — só
> não é emitido por uma autoridade pública."

    curl.exe -sI http://localhost/ | Select-String "HTTP/","Location:"

> "A porta 80 responde 301 para HTTPS. Não existe caminho em claro: se o
> atleta digitar http, é redirecionado antes de enviar qualquer senha."

### 4:30 – 5:30 · Confidencialidade em trânsito

Em HTTP o conteúdo é legível — o comando está em `demo/captura-http.sh`:

    docker exec bt-atacante sh /demo/captura-http.sh

Em HTTPS eu mando uma senha e procuro por ela na captura:

    docker exec bt-atacante sh /demo/captura-https.sh

> "Zero ocorrências. A senha saiu de um lado, chegou no outro, e não existe em
> nenhum byte do que passou pela rede."

**Diga também o que o TLS não esconde:** o nome do host aparece em claro no
SNI do ClientHello. O TLS protege *o que* você diz, não *com quem* você fala.

> ⚠️ Esse script envia um login errado, então ele **já conta como a primeira
> falha** para o vigia — e isso joga a seu favor. No bloco de ataque o
> contador segue de `(2/5)` até `(5/5)` naturalmente, numa sequência contínua
> na tela. **Não rode o reset em câmera.** O reset serve só para ensaiar o
> ataque mais de uma vez.

### 5:30 – 6:00 · Isolamento e superfície de ataque

    docker exec bt-atacante ping -c 2 172.28.0.10
    docker exec bt-atacante nmap -Pn --top-ports 100 proxy

> "O atacante está na mesma máquina física e não alcança o app: 100% de perda.
> E no único nó exposto, só duas portas abertas."

### 6:00 – 7:00 · Ataque, detecção e bloqueio

**Deixe o segundo terminal com `docker compose logs -f defesa` visível.**

    docker exec bt-atacante sh /demo/ataque.sh

No terminal do vigia aparece `(1/5)` até `(5/5)` e então **`BLOQUEADO`**.

    docker exec bt-defesa iptables -L INPUT -n
    docker exec bt-atacante curl -sk -m 8 -o /dev/null -w "atacante: %{http_code}\n" https://proxy/entrar
    curl.exe -sk -o NUL -w "host: %{http_code}`n" https://localhost/entrar

> "O atacante perde acesso, código 000, pacote descartado. E o tráfego
> legítimo continua em 200. O bloqueio é cirúrgico, e expira em 15 minutos
> para que um erro de digitação de um atleta não vire banimento eterno."

**A frase que amarra as duas camadas:** o limite por IP dentro do Python decide
no próprio pedido, mas gasta CPU para decidir; o firewall leva até dois
segundos para reagir e depois descarta o pacote antes de a aplicação acordar.
Defesa em profundidade com custos e latências diferentes.

---

## 7:00 – 9:00 · Testes, evidências e diagnóstico

### 7:00 – 7:50 · O log é prova, não anotação

    docker compose exec app tail -3 /dados/seguranca.log

Mostre uma linha: `seq`, timestamp, evento, IP, usuário, detalhe e **`mac`**.

> "Cada linha é assinada com HMAC-SHA256, e o MAC inclui o MAC da linha
> anterior. É uma cadeia: alterar, apagar ou reordenar qualquer linha invalida
> todas as seguintes."

    docker compose exec app python auditoria.py

Agora **adultere e mostre a detecção**:

    docker exec bt-app sh /demo/adulterar.sh

> "Troquei um e-mail e a verificação acusa. Sem a chave não há como recalcular
> o MAC — e a chave não está no contêiner de defesa, porque para contar falhas
> ele não precisa dela."

**Esteja pronto para o `FALHA linha 1`:** o e-mail que o script troca aparece
já na primeira linha do log. Explique que a cadeia acusa o **primeiro** ponto
de ruptura, e que tudo depois dele fica sob suspeita — num log encadeado não
existe "corromperam só o meio".

### 7:50 – 8:30 · Hardening, com número

    docker exec bt-app id
    docker exec bt-app sh -c "grep CapEff /proc/1/status"
    docker exec bt-defesa sh -c "grep CapEff /proc/1/status"
    docker exec bt-defesa sh -c "echo forjado >> /dados/seguranca.log"

> "O app roda como usuário comum, com **zero** capabilities. O vigia precisa
> escrever regra de firewall, então roda como root — mas com todas as
> capabilities removidas e uma única devolvida: `NET_ADMIN`, o bit 12. E
> tentando escrever no log, ele recebe *Permission denied*: a montagem é
> somente leitura. Quem detecta não altera a evidência."

### 8:30 – 9:00 · Problemas encontrados e limitações

Conte **um** problema — o melhor é este:

> "Um defeito meu de retorno inconsistente não era exercitado por nenhum
> teste, porque aquele caminho só executa na segunda chamada da função. Foi a
> análise estática que achou. Teste prova o caminho percorrido; analisador
> verifica o que ninguém percorreu."

E declare **as duas limitações**, sem rodeio:

> "A cadeia garante integridade e ordenação, mas não completude: quem apagar
> os últimos registros deixa um prefixo válido, e o verificador aceita. A
> mitigação é ancorar o último MAC num canal independente. Também não trato
> IPv6 no bloqueio, porque o iptables é IPv4."

---

## 9:00 – 10:00 · Conclusão

- O que foi alcançado: PKI própria, segmentação de rede, log assinado,
  bloqueio automático e hardening com capability única — **14 evidências
  reprodutíveis por linha de comando**, não por captura de tela.
- Reprodutibilidade: `python gerar_certificados.py` e `docker compose up -d`
  sobem o ambiente em qualquer máquina, sem nunca receber chave privada.
- Trabalhos futuros: ACME/Let's Encrypt no lugar da CA própria, mantendo a
  arquitetura; ancoragem externa do MAC; suporte a IPv6 no bloqueio.
- **Na câmera, fechando:** o aprendizado principal, em uma frase.

---

## Se o tempo apertar, corte nesta ordem

1. O `nmap` (5:30) — bom, mas dispensável
2. O bloco de hardening (7:50) — vira parágrafo no documento
3. O `curl -I` do redirecionamento (4:30) — mencione sem mostrar

**Nunca corte:** a captura HTTP versus HTTPS, o ataque com bloqueio, e a
adulteração do log sendo detectada. São os três que provam RA2 e RA3.

---

## Tempos medidos de cada comando

Cronometrados no ambiente real, para você saber onde a tela fica parada e
onde precisa estar falando:

| Comando | Duração |
|---|---|
| `curl -I http://localhost/` | instantâneo |
| `nmap -Pn --top-ports 100 proxy` | instantâneo |
| `docker exec bt-app sh /demo/adulterar.sh` | 1 s |
| `docker exec bt-atacante sh /demo/ataque.sh` | 1 s |
| `openssl s_client ...` | 3 s |
| `docker compose restart defesa` | 4 s |
| `ping -c 2` no app (falha por timeout) | 4 s |
| `sh /demo/captura-http.sh` | 5 s |
| `sh /demo/captura-https.sh` | 5 s |

**O ataque dura 1 segundo** — mais rápido que a sua frase. Fale a explicação
*antes* de apertar Enter, e deixe o terminal do vigia visível para o
`BLOQUEADO` aparecer enquanto você conclui. O bloqueio chega até 2 segundos
depois da última tentativa, por causa do intervalo de leitura do log.

As duas capturas são os únicos pontos com espera perceptível: 5 segundos
cada, dos quais 4 são os `sleep` que garantem que o `tcpdump` já está
escutando antes do pedido sair. Use esse tempo para explicar o que vai
aparecer.

---

## Ensaio — o que você deve ver em cada passo

Rode tudo uma vez antes de gravar, conferindo contra esta coluna. Se algum
passo não bater, pare e resolva antes de ligar a gravação.

| # | Comando | O que deve aparecer |
|---|---|---|
| 1 | `docker compose ps` | quatro contêineres, todos `Up` |
| 2 | navegador `https://localhost` | aviso de certificado → Avançadas → Ir para localhost → app com **"Olá, Lucas"** e **Convites** no menu |
| 3 | `"" \| openssl s_client -connect localhost:443 -CAfile infra/ca/ca.crt \| Select-String "Protocol  :","Verify return code","issuer="` | `issuer=... CN=RankingBt Root CA`, `Verify return code: 0 (ok)`, `Protocol: TLSv1.3` — exige o `Set-Alias` antes |
| 4 | `curl.exe -sI http://localhost/ \| Select-String "HTTP/","Location:"` | `HTTP/1.1 301 Moved Permanently` e `Location: https://localhost/` |
| 5 | `docker exec bt-atacante sh /demo/captura-http.sh` | três linhas legíveis: `GET /entrar HTTP/1.1`, `301 Moved Permanently`, `Location: https://proxy/entrar` |
| 6 | `docker exec bt-atacante sh /demo/captura-https.sh` | `ocorrencias de SENHA_SECRETA_123: 0`, `linhas HTTP legiveis: 0`, e hex ilegível |
| 7 | `docker exec bt-atacante ping -c 2 172.28.0.10` | `100% packet loss` |
| 8 | `docker exec bt-atacante nmap -Pn --top-ports 100 proxy` | só `80/tcp open` e `443/tcp open` |
| 9 | `docker exec bt-atacante sh /demo/ataque.sh` | `tentativa 1` a `5`, todas `HTTP 400` |
| 9b | **terminal 2** | `(2/5)` … `(5/5)` e então **`BLOQUEADO 172.29.0.40 por 900s`** |
| 10 | `docker exec bt-defesa iptables -L INPUT -n` | `DROP all -- 172.29.0.40` |
| 11 | atacante tentando de novo | `atacante: 000` |
| 12 | `curl.exe -sk -o NUL -w "host: %{http_code}`n" https://localhost/entrar` | `host: 200` |
| 13 | `docker compose exec app tail -3 /dados/seguranca.log` | linhas com `seq=`, evento, `ip=`, e `mac=` de 64 caracteres |
| 14 | `docker exec bt-app sh /demo/adulterar.sh` | `OK cadeia intacta` e depois `FALHA linha 1: MAC invalido` |
| 15 | `docker exec bt-app sh -c "grep CapEff /proc/1/status"` | `0000000000000000` |
| 16 | `docker exec bt-defesa sh -c "grep CapEff /proc/1/status"` | `0000000000001000` |
| 17 | `docker exec bt-defesa sh -c "echo x >> /dados/seguranca.log"` | `Permission denied` |
| 18 | janela anônima, logada como Emily, abrir `/convites` | página de erro **403** |

### Depois do ensaio, volte ao estado limpo

O ensaio deixa o atacante bloqueado e o contador do vigia usado. Antes de
gravar de verdade:

    docker exec bt-defesa iptables -D INPUT -s 172.29.0.40 -j DROP
    docker compose restart defesa

Confirme que voltou ao normal:

    docker exec bt-defesa iptables -L INPUT -n

A chain `INPUT` tem que estar vazia. Se ainda aparecer `DROP`, rode o
comando de remoção de novo.
