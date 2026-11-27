# Testes que você faz direto no navegador

Sete demonstrações sem digitar um comando. Três delas mostram controles que
**não aparecem em nenhum teste do terminal** — valem a pena no vídeo.

Tudo em `https://localhost`, logado como Lucas. Abra as ferramentas de
desenvolvedor com **F12**.

---

## 1. O cookie que o JavaScript não consegue ler ⭐

**O melhor teste do conjunto.** Dez segundos, e prova um controle real.

### Como fazer
1. Clique no botão de tema uma vez (para o cookie de tema existir)
2. **F12** → aba **Console**
3. Digite e dê Enter:

       document.cookie

### O que você vai ver

    'bt_tema=a'

Só isso. **O `bt_sessao` não aparece.**

### Por que isso importa
A página tem dois cookies: `bt_tema`, que guarda sua preferência de cor, e
`bt_sessao`, que é **a sua identidade logada** — quem tiver esse valor entra
como você, sem senha.

O `bt_sessao` foi gravado com a marca **`HttpOnly`**, que significa: *"o
navegador guarda e envia, mas nenhum JavaScript da página pode ler"*.

Consequência: se alguém conseguisse injetar um script malicioso na página
(ataque de XSS), esse script **não conseguiria roubar a sua sessão**. Ele
leria o tema e nada mais.

### A frase
> "Dois cookies nesta página. O JavaScript lê o do tema e não lê o de sessão,
> porque o de sessão é HttpOnly. Mesmo que alguém injete script aqui, não
> rouba a minha sessão."

---

## 2. As marcas do cookie, visualmente

### Como fazer
**F12** → aba **Application** → menu esquerdo, **Storage → Cookies** →
`https://localhost`

### O que você vai ver
Uma tabela com os dois cookies. Na linha do `bt_sessao`, colunas marcadas:

| Coluna | Marcada? | O que quer dizer |
|---|---|---|
| `HttpOnly` | ✔ | JavaScript não lê |
| `Secure` | ✔ | só viaja por HTTPS, nunca em claro |
| `SameSite` | `Lax` | não é enviado em pedido vindo de outro site |

E na linha do `bt_tema`, o `HttpOnly` está **vazio** — porque o tema não é
segredo.

### Por que o `SameSite` importa
Sem ele, um site malicioso poderia fazer o seu navegador enviar um pedido para
o RankingBt **com o seu cookie junto**, e a aplicação acharia que foi você.
Isso se chama CSRF. O `SameSite=Lax` é a primeira barreira; o token nos
formulários é a segunda.

### A frase
> "O cookie de sessão tem três proteções: HttpOnly, Secure e SameSite. Cada
> uma fecha um caminho diferente de roubo de sessão."

---

## 3. Os cabeçalhos de segurança

### Como fazer
**F12** → aba **Network** → recarregue a página (**F5**) → clique na primeira
linha da lista (o documento) → aba **Headers** → role até **Response Headers**

### O que você vai ver

    content-security-policy: default-src 'self'; script-src 'self'; ...
    x-frame-options: DENY
    x-content-type-options: nosniff
    referrer-policy: same-origin
    permissions-policy: camera=(), microphone=(), geolocation=()
    strict-transport-security: max-age=300
    cache-control: no-store

### O que cada um faz

| Cabeçalho | Instrução que ele dá ao navegador |
|---|---|
| `content-security-policy` | "só execute script que veio deste mesmo site" — trava XSS |
| `x-frame-options: DENY` | "não deixe ninguém colocar esta página dentro de um iframe" — trava clickjacking |
| `x-content-type-options: nosniff` | "não tente adivinhar o tipo do arquivo" |
| `referrer-policy` | "não conte para outros sites de onde o usuário veio" |
| `permissions-policy` | "esta página não usa câmera, microfone nem localização" |
| `strict-transport-security` | "pelos próximos N segundos, só fale comigo por HTTPS" |
| `cache-control: no-store` | "não guarde esta página em cache" — ela tem dados do atleta |

### A frase
> "Sete cabeçalhos de segurança em toda resposta. Cada um é uma instrução ao
> navegador fechando um tipo de ataque: script injetado, clickjacking,
> vazamento de origem, página com dados pessoais ficando em cache."

---

## 4. O certificado, pelo cadeado

### Como fazer
Clique no ícone à esquerda da URL (vai estar com o aviso de "Não seguro") →
**"O certificado não é válido"** ou **Certificado** → aba **Detalhes**

### O que você vai ver
- **Emitido para:** `localhost`
- **Emitido por:** `RankingBt Root CA` ← **o seu cartório**
- Validade de um ano
- Em Detalhes: a extensão **Nome alternativo da entidade** com
  `localhost`, `proxy`, `127.0.0.1`

### A frase
> "Emitido para localhost, emitido por RankingBt Root CA — que é a autoridade
> certificadora que eu criei. O navegador avisa porque essa autoridade não
> está na lista do sistema operacional, e está certo em avisar."

---

## 5. A versão do TLS, sem terminal

### Como fazer
**F12** → se não houver aba **Security**, clique em **»** (mais abas) →
**Security** → recarregue a página

### O que você vai ver

    Connection - secure connection settings
    The connection to this site is encrypted using a modern cipher suite.
    protocol: TLS 1.3
    key exchange: X25519
    cipher: AES_256_GCM

É a **mesma informação** que o `openssl s_client` mostra, mas visual.

### A frase
> "O navegador confirma: TLS 1.3, AES de 256 bits. É a mesma informação do
> openssl, vista pelo lado do cliente."

---

## 6. O redirecionamento, ao vivo

### Como fazer
Na barra de endereço, digite e dê Enter:

    http://localhost

(com `http`, sem o S)

### O que você vai ver
A URL **troca sozinha** para `https://localhost`. Você nunca chega a carregar
nada em claro.

Se quiser provar que foi o servidor: **F12 → Network** antes de digitar. Você
verá duas linhas, a primeira com status **301**.

### A frase
> "Pedi em HTTP e o servidor me mandou para o HTTPS antes de entregar
> qualquer coisa. Não existe caminho em claro."

---

## 7. O controle de acesso, na janela anônima

### Como fazer
Na janela anônima, logada como **Emily** (conta comum), digite na barra:

    https://localhost/convites

### O que você vai ver
Uma página de erro: **403 — Só administradores acessam esta página.**

E na janela normal, logado como Lucas, o mesmo endereço abre a tela de
convites normalmente.

### Por que isso importa
É o mesmo endereço, o mesmo servidor, o mesmo momento. **O que muda é quem
está pedindo.** Isso é controle de acesso baseado em papel — o RA1 do
enunciado.

E repare: esse acesso negado **vira linha no log de auditoria**. Depois de
fazer o teste, vale mostrar:

    docker compose exec app tail -2 /dados/seguranca.log

Você vai ver o evento `ACESSO_NEGADO` com o e-mail da Emily.

### A frase
> "Mesma URL, mesmo servidor. Com a conta comum, 403. E a tentativa ficou
> registrada no log assinado."

---

## ⚠️ Um teste que você NÃO deve fazer no navegador

**Não erre a senha cinco vezes no navegador.**

O vigia conta falhas por endereço, e o endereço que ele vê quando você usa o
navegador do Windows é o do gateway do Docker. Cinco erros e **ele bloqueia
você** — a tela para de responder no meio da gravação.

Se acontecer, o conserto é:

    docker exec bt-defesa iptables -L INPUT -n
    docker exec bt-defesa iptables -D INPUT -s <o ip que apareceu> -j DROP

A demonstração de força bruta deve ser feita **de dentro do contêiner
atacante**, como está no roteiro.

---

## Sugestão para o vídeo

Os testes 1, 2 e 3 mostram controles que **nenhum comando do terminal
demonstra**. Se você tiver 90 segundos sobrando, encaixe-os no bloco de
3:00–7:00, logo depois de mostrar o app carregado. São visuais, rápidos e
fáceis de narrar — e provam três camadas que o documento afirma.
