# Entendendo cada saída — em português comum

Leia antes de gravar. Para cada demonstração: o que o comando faz, o que a
saída quer dizer, e a frase que você pode falar.

---

## 1. `docker compose ps`

### O que o comando faz
Pergunta ao Docker: "quais máquinas do meu projeto estão ligadas agora?"

Cada contêiner é como um **computador pequeno e separado**, rodando dentro do
seu Windows. São quatro, e cada um tem um trabalho só.

### O que a saída quer dizer

    bt-app        Up 27 minutes   8000/tcp
    bt-atacante   Up 27 minutes
    bt-defesa     Up 9 minutes
    bt-proxy      Up 30 minutes   0.0.0.0:443->443/tcp

- `Up` = ligado e funcionando.
- A coluna da direita é **quais portas estão abertas para fora**.
- Repare: só o `bt-proxy` tem `0.0.0.0:443->443`. Isso quer dizer "qualquer um
  que alcançar esta máquina pela porta 443 chega aqui".
- O `bt-app` mostra `8000/tcp` **sem** `0.0.0.0->`. Isso é diferente: ele
  escuta na porta 8000, mas **ninguém de fora consegue chegar nela**. Só quem
  já está dentro da rede interna do Docker.

### A frase
> "Quatro máquinas. Só o proxy tem porta aberta para fora. A aplicação escuta
> numa porta que ninguém de fora alcança."

---

## 2. `openssl s_client` — o crachá do servidor

### O que o comando faz
O `openssl` é um canivete suíço de criptografia. O `s_client` faz ele se
comportar **como se fosse um navegador**: conecta no servidor, pede o
certificado e mostra tudo que aconteceu.

**O que é um certificado:** é o **crachá do site**. Ele diz "eu sou o
localhost" e vem **assinado por um cartório**. O cartório, em segurança, se
chama *Autoridade Certificadora* — a CA.

Você criou o seu próprio cartório no dia 22. Ele se chama `RankingBt Root CA`.

### O que a saída quer dizer

    issuer=... CN=RankingBt Root CA

`issuer` = **quem assinou o crachá**. Neste caso, o seu cartório.

    depth=1 ... CN=RankingBt Root CA
    depth=0 ... CN=localhost

Esses são os **degraus da cadeia**, de cima para baixo:
- `depth=1` é o cartório (a raiz).
- `depth=0` é o crachá do servidor.

O programa confere: "o crachá do servidor foi mesmo assinado por esse
cartório?" — e os dois degraus passaram.

    Verify return code: 0 (ok)

**Zero é sucesso** aqui (como em quase todo programa de linha de comando:
0 = deu certo, qualquer outro número = deu erro). Quer dizer: a assinatura
confere, o crachá é legítimo.

    Protocol  : TLSv1.3
    Cipher    : TLS_AES_256_GCM_SHA384

`TLSv1.3` é a **versão do protocolo de cifragem** — a mais nova, de 2018.
`Cipher` é **qual algoritmo foi escolhido** para embaralhar os dados:
AES de 256 bits, no modo GCM.

> O servidor e o cliente *negociam* isso no começo da conversa: cada um diz o
> que sabe fazer e os dois escolhem o melhor em comum. Você configurou o Nginx
> para só aceitar TLS 1.2 e 1.3, então versões velhas e quebradas nem entram
> na negociação.

### A frase
> "Conectei como se fosse um navegador. O certificado foi assinado pela minha
> CA, a cadeia valida nos dois degraus, e a conexão negociou TLS 1.3 com
> AES-256."

---

## 3. `curl.exe -sI http://localhost/` — a porta 80 fechada

### O que o comando faz
`curl` é um programa que faz pedido de página, igual ao navegador, mas sem
janela. O `-I` pede **só o cabeçalho**, não a página inteira — é como perguntar
"o que você responderia?" sem baixar o conteúdo.

Repare que eu pedi `http://`, **sem o S**. Ou seja: sem cifragem.

### O que a saída quer dizer

    HTTP/1.1 301 Moved Permanently
    Location: https://localhost/

`301` é um **código de resposta**. Os principais:
- `200` = deu certo, aqui está
- `301` / `303` = mudou de endereço, vá para outro lugar
- `400` = você mandou algo errado
- `403` = você não tem permissão
- `429` = você está pedindo demais, calma
- `000` = **não houve resposta nenhuma** (o pedido nem chegou)

`Location:` é **para onde ele está te mandando**: a mesma página, mas em
`https://`.

### A frase
> "Pedi em HTTP, sem cifragem. O servidor não respondeu a página: devolveu 301
> e mandou para o HTTPS. Não existe caminho em claro."

---

## 4. `captura-http.sh` — o grampo na linha

### O que o comando faz
O `tcpdump` é um **grampo**: ele escuta tudo que passa pela placa de rede e
grava num arquivo. O script liga o grampo, faz um pedido HTTP comum, desliga o
grampo e procura texto legível no que foi gravado.

### O que a saída quer dizer

    GET /entrar HTTP/1.1
    HTTP/1.1 301 Moved Permanently
    Location: https://proxy/entrar

Isso é **a conversa inteira, legível**, lida de dentro da rede. Quem tiver
acesso ao caminho — o Wi-Fi do café, o roteador, o provedor — lê a mesma coisa.

### A frase
> "Grampeei a rede durante um pedido HTTP. Dá para ler a conversa inteira."

---

## 5. `captura-https.sh` — o mesmo grampo, agora inútil

### O que o comando faz
A mesma coisa, mas o pedido vai por HTTPS **e leva uma senha dentro**:
`SENHA_SECRETA_123`. Depois o script procura essa senha no que foi gravado.

### O que a saída quer dizer

    ocorrencias de SENHA_SECRETA_123: 0
    linhas HTTP legiveis:  0

**Zero e zero.** A senha saiu do seu computador, chegou no servidor, e **não
existe em nenhum byte** do que passou pela rede. Também não há nenhuma linha
de HTTP legível.

    0x0030:  f58f 7cb9 1603 0300 7a02 0000 7603 0368
    0x0040:  c6c3 78ba 1dbb 2ca3 4950 6e9e abbb f969

Isso é o que **de fato** passou: bytes embaralhados. A coluna da esquerda é a
posição, o meio é o conteúdo em hexadecimal, e não há texto reconhecível.

### A frase
> "Mesmo grampo, mesma rede, agora por HTTPS. Mandei uma senha e procurei por
> ela: zero ocorrências. O que passou foi isto aqui — bytes sem sentido."

### E diga também o que o TLS *não* esconde
O nome do servidor (`proxy`) aparece em claro no começo da conversa, antes de
a cifragem começar — o cliente precisa dizer com quem quer falar para receber
o crachá certo. **O TLS esconde o que você diz, não com quem você fala.**

---

## 6. `ping` e `nmap` — tentando alcançar o que não dá

### O que os comandos fazem
`ping` = "você está aí?". Manda um pacotinho e espera resposta.
`nmap` = "quais portas desta máquina estão abertas?" — bate em cada porta e
anota quais respondem.

### O que a saída quer dizer

    2 packets transmitted, 0 packets received, 100% packet loss

Mandei 2, voltou 0. **O atacante não tem caminho até a aplicação.** Não é que
a aplicação recusou: é que o pacote não chega lá, porque estão em redes
separadas.

    80/tcp  open  http
    443/tcp open  https

Só duas portas abertas no proxy. Tudo o mais está fechado. Isso se chama
**superfície de ataque**: quanto menor, menos lugares por onde tentar entrar.

### A frase
> "O atacante está na mesma máquina física e não alcança a aplicação: 100% de
> perda. E no único nó exposto, só duas portas respondem."

---

## 7. O ataque, o vigia e o firewall

### O que o comando faz
`ataque.sh` tenta logar cinco vezes com senha errada, de dentro do contêiner
atacante.

### O que a saída quer dizer

    tentativa 1: HTTP 400
    ...
    tentativa 5: HTTP 400

`400` = login recusado. Cinco vezes.

**No segundo terminal**, o vigia vai mostrando:

    LOGIN_FALHOU de 172.29.0.40 (2/5)
    ...
    LOGIN_FALHOU de 172.29.0.40 (5/5)
    BLOQUEADO 172.29.0.40 por 900s

Ele está **contando as falhas por endereço**. Chegou a 5, bloqueou por 900
segundos (15 minutos).

> `172.29.0.40` é o **endereço do atacante** na rede. Cada contêiner tem o seu,
> como o número de uma casa na rua.

    DROP  all  --  172.29.0.40  0.0.0.0/0

Essa é a **regra de firewall** criada. Leia assim: "descarte (`DROP`) tudo
(`all`) que vier de `172.29.0.40` para qualquer destino (`0.0.0.0/0`)".

`DROP` não é "recusar". É **jogar fora em silêncio** — o atacante não recebe
nem um "não". Fica esperando até desistir.

    atacante: 000
    host:     200

`000` = **não houve resposta**, o pedido morreu no firewall.
`200` = o seu computador continua sendo atendido normalmente.

### A frase
> "Cinco senhas erradas. O vigia contou, criou a regra de firewall, e o
> atacante parou de receber resposta — código 000. O tráfego legítimo continua
> em 200. O bloqueio é cirúrgico."

---

## 8. `auditoria.py` — o diário lacrado

### O que é o log
Toda vez que acontece algo de segurança (login errado, acesso negado, bloqueio),
a aplicação escreve uma linha num arquivo. Uma linha é assim:

    seq=11 | 2026-11-25T20:12:19Z | LOGIN_FALHOU | ip=172.29.0.40 | usuario=vitima@teste.com | detalhe=E-mail ou senha incorretos. | mac=4417f81a...

- `seq=11` → é a **décima primeira** linha. Numeradas em ordem.
- a data e hora, em UTC (o `Z` no fim significa isso)
- o **evento**, o **endereço** de quem fez, o **usuário** tentado, e o detalhe
- `mac=...` → o **lacre**

### O que é o lacre (`mac`)
É um código calculado a partir de três coisas: o conteúdo da linha, **uma
chave secreta**, e **o lacre da linha anterior**.

Duas consequências:
1. **Sem a chave, ninguém consegue fazer um lacre válido.** Não adianta
   recalcular: você precisa do segredo.
2. **Cada lacre depende do anterior.** Então as linhas formam uma corrente. Se
   alguém mexer na linha 3, o lacre dela muda, e aí a 4 não bate mais, e a 5
   também não — até o fim do arquivo.

### O que a saída quer dizer

    OK    cadeia intacta: 21 linhas verificadas

Recalculei os 21 lacres e todos bateram: **ninguém mexeu no arquivo.**

    FALHA linha 1: MAC invalido - conteudo alterado

Alterei um e-mail na cópia e o lacre da linha 1 não bate mais.

> Vai dizer "linha 1" porque o e-mail que o script troca aparece já na primeira
> linha. A verificação para no **primeiro** ponto quebrado — e daí para frente
> nada mais é confiável.

### A frase
> "Cada linha é lacrada com um código que depende do conteúdo, de uma chave
> secreta e do lacre anterior. Troquei um e-mail numa cópia e a verificação
> acusou. Sem a chave não há como forjar."

---

## 9. `CapEff` — quantos poderes o processo tem

### O que são capabilities
No Linux, ser `root` normalmente significa **poder fazer tudo**. Mas o sistema
quebra esse "tudo" em cerca de 40 poderes separados — mexer na rede, montar
disco, matar processo dos outros, carregar driver, mudar o relógio.

Esses poderes se chamam **capabilities**, e dá para entregar só os que o
programa precisa.

### O que a saída quer dizer

    bt-app     CapEff: 0000000000000000
    bt-defesa  CapEff: 0000000000001000

É um número em hexadecimal onde **cada bit ligado é um poder**.

- A aplicação: **todos zerados**. Nenhum poder especial. É um usuário comum.
- O vigia: **um único bit ligado**, o de número 12, que é `CAP_NET_ADMIN` —
  administrar rede. Ele pode mexer no firewall e **nada mais**: não monta
  disco, não mata processo de outro usuário, não carrega driver.

E quando ele tenta escrever no arquivo de log:

    Permission denied

Porque o log foi montado **somente leitura** para ele. **Quem detecta não
altera a evidência.**

### A frase
> "A aplicação roda com zero capabilities. O vigia precisa escrever regra de
> firewall, então roda como root — mas com todos os poderes removidos e um só
> devolvido: administrar rede. E ele não consegue escrever no log, porque a
> montagem é somente leitura."

---

## Resumo: os números que mais aparecem

| Número | Onde aparece | Quer dizer |
|---|---|---|
| `0` | `Verify return code`, código de saída | **deu certo** |
| `1` | código de saída do `auditoria.py` | deu erro / detectou problema |
| `200` | resposta HTTP | página entregue |
| `301` | resposta HTTP | vá para outro endereço |
| `400` | resposta HTTP | pedido recusado (login errado) |
| `403` | resposta HTTP | você não tem permissão |
| `429` | resposta HTTP | pedidos demais, espere |
| `000` | resposta HTTP | **não houve resposta** (bloqueado) |
| `100% packet loss` | `ping` | não há caminho até lá |
