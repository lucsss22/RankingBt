# BT Ranking — resumo das 4 funcionalidades novas (25/10/2026)

> **Reinicie o `iniciar.bat`.** O servidor que já estava rodando tem o código antigo na
> memória, mas lê os templates novos do disco. Até reiniciar, algumas telas podem dar erro.
> Na primeira execução o banco é atualizado sozinho (versão 2 → 3), sem perder contas.
> Isso foi testado numa cópia do seu `atletas.db`.

Cópia do código anterior: `backups/2026-10-25_antes_das_4_funcionalidades/`.

## Atualização (26/10): "Atualizar meus resultados" não segura mais a tela
- **O problema:** a busca tinha duas etapas. Os torneios do atleta chegaram às 13:40:44, mas a tela continuou em "buscando" até 13:47:46, enquanto o app buscava o tamanho de 8 chaves com a ITF bloqueando várias vezes.
- **Agora:** assim que os torneios chegam, a tela libera e mostra os resultados. O tamanho das chaves é só um ajuste fino, que muda apenas os pontos de quem caiu na 1ª rodada. Ele continua em segundo plano, com um aviso discreto no Perfil.
- **Limite para as chaves:** no máximo 90 segundos e 2 sessões novas do navegador. O que faltar fica para a próxima atualização. Antes, uma busca podia prender a fila de buscas na ITF por 7 minutos ou mais.
- **O ranking semanal funcionou na primeira segunda:** o de 26/10 foi baixado sozinho às 13:15 (masculino, 3.276) e às 13:17 (feminino, 2.197).
- **Testes:** `teste_buscas_itf.py`, com 13 verificações. Um teste antigo dependia do ranking ser o de 19/10 e agora calcula o esperado a partir dos dados. No total, **383 verificações, 0 falhas**.

## Atualização (25/10, 23h50): ranking atualizado sozinho toda segunda
- **Como funciona:** o servidor confere a cada 15 minutos. A partir das 10h de segunda, se o ranking salvo for anterior à segunda-feira, ele pergunta à ITF a data do ranking publicado, lendo só a primeira página, o que é leve. Se for nova, baixa o masculino e o feminino e grava. Quem abrir o app depois já encontra o ranking pronto.
- **A ITF ainda não publicou?** Tenta de novo a cada 3 horas na segunda e na terça, e a cada 12 horas de quarta em diante.
- **PC desligado na segunda?** Atualiza assim que o servidor ligar, a primeira conferência é 1 minuto depois.
- **Nunca mostra ranking pela metade:** a gravação passou a ser atômica (arquivo temporário e troca). Se a ITF bloquear no meio da coleta, o app continua mostrando o último ranking completo, e a próxima tentativa continua de onde parou.
- **O botão "Atualizar ranking da ITF"** do administrador usa a mesma regra: confere a data e só baixa se houver ranking novo. Antes ele reaproveitava o arquivo por 24 horas e podia não baixar o ranking de segunda. Quando já está em dia, avisa "já é o mais novo da ITF".
- **No Início** aparece "atualiza sozinho toda segunda". O administrador vê quando a atualização automática está rodando, ou se falhou.
- **Para desligar:** `BT_ATUALIZAR_RANKING=0` antes de iniciar o servidor.
- **Testes:** `teste_ranking_semana.py`, com 35 verificações (quando busca, intervalos, só o gênero atrasado, ITF sem ranking novo, coleta pela metade, botão do administrador, relógio ligando e desligando com o servidor). No total, **370 verificações, 0 falhas**.

## Atualização (25/10, fim da noite): segurança, otimização e GitHub
### Segurança (revisão do app inteiro)
**O que já estava bem e foi conferido:**
- Senhas com PBKDF2-SHA256 de 600 mil iterações e sal; login com o mesmo tempo de resposta para e-mail inexistente; bloqueio da conta depois de 5 erros.
- Sessão com token aleatório de 256 bits, guardado só como hash; cookie HttpOnly, Secure e SameSite.
- CSRF em todos os formulários de quem está logado; convites com `secrets`, de uso único e com validade.
- Todas as consultas ao banco com parâmetros (sem injeção de SQL); HTML com escape automático.
- Cabeçalhos CSP, X-Frame-Options e nosniff; documentação automática da API desligada; servidor ouvindo só em 127.0.0.1.
- Um atleta só exclui os próprios resultados e duplas; administrador só pelo `gerenciar.py`.

**Corrigido:**
- **Limite por endereço de rede**: 10 logins ou cadastros errados em 10 minutos e aquele aparelho espera. Antes, alguém podia testar muitos e-mails, ou adivinhar convites, e cada tentativa gasta ~0,5 s de CPU do seu PC. Em IPv6 conta a rede /64 inteira.
- **Tamanho máximo de envio** (512 KB): um envio gigante podia encher a memória do PC antes de qualquer verificação.
- **Redirecionamento aberto** no botão de tema sem JavaScript: um endereço começando com `//` podia levar para outro site.
- **Nome de arquivo das chaves de torneio**: agora só aceita letras, números e hífen. Antes já só recebia chaves conferidas no calendário; esta é uma proteção a mais.
- **`requirements.txt`**: versões mínimas com as correções de segurança conhecidas (starlette, h11, python-multipart, jinja2). As versões instaladas no seu PC já estavam atualizadas.

**Riscos baixos que ficaram (aceitáveis para um app só com convidados):**
- Um atleta pode vincular a conta a qualquer jogador do ranking que ainda não esteja vinculado, porque não há como provar identidade na ITF.
- O formulário de login não tem CSRF (o máximo que alguém conseguiria é logar você na conta dele).
- Quem souber o e-mail de alguém pode bloquear a conta dessa pessoa por 15 minutos errando a senha 5 vezes.

### Otimização
- **Ranking em memória com os cálculos prontos**: pontos ordenados, jogador por ID, países e rank limite são calculados uma vez por download do ranking, e não mais a cada página.
- **Calendário da ITF em memória** até o arquivo mudar (eram ~600 KB lidos do disco a cada página de Pontos e Meta).
- **Leitura dos campos do JSON da ITF** (`primeiro_valor`, no script original) sem montar cópia desnecessária. O resultado é idêntico, testado em todos os 3.258 jogadores.
- **Medido no mesmo momento, antes × depois**: Estimar −30%, Meta −37%, Tierlist −15% a −41%, Perfil −32%, Pontos −40%. Todas as telas já respondiam em menos de 0,1 s; agora ficaram mais leves para o PC.
- **Limpeza**: imports sem uso e uma mensagem que nenhuma rota usava. O linter não acha mais nada.

### Testes
- `python testes/rodar_todos.py`: **335 verificações, 0 falhas**.
- 15 verificações novas: limite por IP (inclusive para convites), envio grande com e sem Content-Length, redirecionamento do tema, caminho com `..`, calendário em memória. E a prova de que as otimizações dão exatamente o mesmo resultado que antes.
- Navegador: busca no ranking e "Sou eu" (58 verificações) e as telas principais, sem erros.
- `gerenciar.py` e `app.py` funcionando.

### GitHub
- **Git iniciado na pasta**, com `.gitignore` que deixa de fora o banco de contas (`atletas.db`), a chave dos formulários (`segredo.key`), caches e rankings baixados da ITF, backups e arquivos `.bak`.
- **Os testes precisam do `ranking_itf_M.json`**, que não sobe para o GitHub. Num clone novo, baixe o ranking antes de rodá-los (botão do Início ou `app.py`).

## Atualização (25/10, noite): dupla simulada com busca no ranking e "Sou eu"
- **Busca pelo nome da ITF**: no formulário da dupla simulada, conforme você digita (2 letras ou mais) aparece a lista do ranking com rank, pontos e país.
  - A busca acha pelo começo de cada pedaço do nome, sem acento: "sil jo" acha "SILVA Joao".
  - Quem tem o nome inteiro aparece primeiro, depois os melhores do ranking.
- **Ao escolher alguém da lista**, o app guarda o ID da ITF, e o rank passa a vir sempre do ranking do dia. Rank e pontos manuais somem. Se você mexer no nome depois, a escolha é desfeita.
- **"Sou eu"**: caixa no Atleta 1 que usa o seu vínculo com a ITF. Só aparece para quem vinculou a conta e quando o ranking da tierlist é o do seu gênero. Funciona mesmo sem JavaScript.
- **Quem não está no ranking** continua como antes: nome e, se quiser, rank ou pontos.
- **No celular**, ao tocar no nome o campo sobe para o topo, e a lista aparece acima do teclado.
- **Banco versão 4**: duas colunas novas na dupla simulada, para o ID da ITF. Testei numa cópia do seu `atletas.db` (v3 → v4): contas, sessões, convites, listas e duplas ficaram idênticas.
- **Testes**: `python testes/rodar_todos.py` dá **320 verificações, 0 falhas**.
  - O teste antigo "ranking feminino sem cache avisa" passou a simular a falta do arquivo, porque agora o ranking feminino existe na pasta.
  - Navegador (Chromium) em 390 px com toque e em 1280 px com teclado e mouse, temas A e B: 58 verificações, nenhum erro de JavaScript e nenhuma rolagem horizontal.
- **Reinicie o `iniciar.bat`** para ativar. Até lá a tierlist continua abrindo, só sem a busca e sem o "Sou eu".

## O que mudou

### 1. Tierlist: dupla fora da lista e ranking do parceiro
- **Regra da ITF** (Regulamento 2026, item 14), em `tierlist_regras.py`:
  - ordem: duplas com dois ranqueados pela soma dos ranks, depois as com um ranqueado (pelo rank dele), depois as sem ranking;
  - desempate pelo melhor atleta individual;
  - empate total aparece marcado como "empate · sorteio".
- **Faixas no lugar dos tiers S/A**:
  - cabeças da chave (8 na chave de 32);
  - chave principal (20 entradas diretas na de 32; vale o número do regulamento para cada tamanho, e dá para editar);
  - cabeças do qualy (16 no qualy de 32, 8 no de 16, ou seja metade da chave, no máximo 16);
  - qualifying;
  - fora da chave.
  - Dupla sem ninguém ranqueado não vira cabeça.
- **Lista salva por usuário**: a última lista colada continua lá ao voltar, em qualquer aparelho.
- **Dupla simulada**: nome de cada atleta e, se quiser, o rank *ou* os pontos. Sem rank nem pontos, o app procura o nome no ranking. Fica salva até ser excluída; dá para ter até 20.
- **Ranking mínimo do parceiro**:
  - escolha o atleta (você ou outro) e o alvo (uma faixa ou uma posição exata);
  - o app mostra o pior rank que o parceiro pode ter e a posição que a dupla teria com um parceiro sem ranking;
  - a busca é exata e foi conferida contra força bruta;
  - mostra os 20 atletas reais mais próximos do limite, sem quem já está na lista, com filtro de país (começa no seu).
- **Celular**: a coluna "Faixa" vira etiqueta curta embaixo da dupla, para os nomes e a soma caberem.

### 2. Pontos por rodada: torneio real
- **Duas abas**: "Torneio real" e "Manual" (a manual é a de antes, sem mudanças).
- **Busca no calendário da ITF**: por nome, país (começa no seu, ou Brasil) e período (próximos, últimos 60 dias ou todos).
- **Ao escolher o torneio**:
  - a categoria vem do calendário;
  - o tamanho da chave (principal e qualy, masculino e feminino) vem da chave publicada pela ITF;
  - se a ITF ainda não publicou, você escolhe o tamanho, e o botão "Buscar chave na ITF" tenta de novo.
- **Botão "Estimar meu ranking neste torneio"**: abre a estimativa com a categoria, a chave e o nome do torneio já preenchidos.

### 3. Perfil: meus resultados na ITF
- **O que mostra**: torneio, data, categoria, parceiro, até onde chegou e pontos (chave principal ou qualy, mais o bonus draw).
- **Etiquetas**: "conta · vence dd/mm/aa", "fora dos 10 melhores", "entra no ranking em…", "em andamento", "sem cálculo" e "fora das 52 semanas".
- **Comparação com o oficial**: a soma calculada aparece ao lado do total oficial. **No seu caso deu 14 pts em 5 resultados, igual ao oficial.**
- **Botão "Atualizar meus resultados"**: busca na ITF a atividade do atleta, o calendário e as chaves dos torneios em que o tamanho muda os pontos. Não repete a busca em menos de 10 minutos.
- **Estimativa exata**: quando a soma confere com o oficial, a estimativa usa sozinha o seu pior resultado que conta, e você não precisa digitar nada.

### 4. Meta de ranking (nova página, `/meta`)
- **Entrada**: você digita a posição que quer alcançar.
- **O que mostra**:
  - os pontos que garantem essa posição (os de quem está nela hoje);
  - o seu total hoje e na data da meta (daqui a 4 semanas), já sem os pontos que vencem até lá;
  - quanto falta.
- **Por categoria** (BT10 a Mundial, chave de 32): até onde precisa chegar, já descontando o pior resultado quando você tem 10 ou mais.
- **Próximos torneios** (8 semanas, filtro de país): a mesma conta, torneio a torneio, na data em que os pontos de cada um entram.
- **Sem os resultados da ITF**: usa o total oficial; com 10 ou mais torneios, na hipótese mais pessimista, e avisa.
- **Onde fica**: no menu lateral do computador; no celular, pelo Início e pelo botão na tela Estimar.

### Base nova
| Arquivo | O que faz |
|---|---|
| `itf_dados.py` | Busca na ITF: calendário, chaves e atividade, pelo mesmo Chromium e as mesmas novas tentativas da coleta do ranking. Guarda cache em `cache_itf/`. |
| `resultados_itf.py` | Converte os dados da ITF em pontos pela tabela oficial. Aplica as regras de bye e W.O., qualy só para quem não se classificou, bonus draw, entrada na segunda-feira, validade de 52 semanas e os 10 melhores. |
| `tierlist_regras.py` | Ordem, vagas, faixas e parceiro. |
| `estimativa.py` | Ganhou as funções da meta. |
| `atletas.py` | Banco versão 3: lista da tierlist e duplas simuladas. |
| `web.py` | Executor de buscas na ITF em segundo plano (uma por vez). A página atualiza sozinha quando a busca termina. Telas novas. |
| `testes/` | Testes do projeto, todos rodando numa pasta de dados temporária. |

**Correção de bug antigo:** os atributos extras dos campos de formulário (`inputmode`, `maxlength`, `placeholder`) saíam com aspas escapadas. Também acontecia no cadastro.

## O que foi testado
- `python testes/rodar_todos.py`: **299 verificações, 0 falhas**.

  | Arquivo | Verificações | O que cobre |
  |---|---|---|
  | `teste_modulos.py` | 44 | Os testes originais, agora com o banco na versão 3. |
  | `teste_tierlist.py` | 27 | Ordem, desempate, vagas e faixas de todas as chaves; parceiro igual à força bruta em 300 cenários aleatórios; atletas reais. |
  | `teste_resultados_itf.py` | 47 | Respostas reais da ITF salvas em `testes/dados_itf/`, mais casos de bye, W.O., bonus draw, chave de 16 contra 32 e validade. |
  | `teste_meta.py` | 19 | Pontos para a posição conferidos em 200 alvos do ranking real, descarte do pior e vencimentos. |
  | `teste_web.py` | 160 | Todas as telas antigas e novas de ponta a ponta. As buscas na ITF são trocadas por respostas salvas, e a rede fica bloqueada. |
  | `teste_indice.py` | 2 | Índice de nomes igual à busca original. |

- **ITF de verdade**, numa pasta temporária:
  - calendário com 681 torneios, a sua atividade (22 torneios) e 5 chaves;
  - BT200 Florianópolis com chave publicada; BT400 Marechal Deodoro ainda sem chave;
  - **14 pts calculados = 14 pts oficiais**, todos com o tamanho de chave real.
- **App de terminal** (`app.py`) e **`gerenciar.py`**: funcionando, com o banco na versão 3.
- **Navegador (Chromium)**: Tierlist, Pontos (lista e torneio), Perfil e Meta, em 390 px e 1280 px, nos temas A e B.
  - Nenhum erro de JavaScript e nenhuma rolagem horizontal.
  - Corrigi o que apareceu: buraco no layout da tierlist no computador, tabela espremida no celular, textos da meta, lista inútil de parceiros quando qualquer um serve, e o rótulo do torneio que ainda vai entrar no ranking.

## Pendente / limitações
- **A busca na ITF pode levar minutos.** No teste real, atividade, calendário e chaves levaram cerca de 4 minutos, porque o site bloqueou e o coletor trocou de sessão várias vezes, como no ranking. A tela avisa e atualiza sozinha.
- **Campeonatos regionais** (Europeu etc.) ficam "sem cálculo", porque a ITF não informa se são RC1 ou RC2. **Tour Finals** não é calculado, como você decidiu. **Bundles** não aparecem nos dados da ITF. Nesses casos a soma pode não bater com o oficial, e o perfil mostra a diferença.
- **Chave não publicada**: o tamanho é presumido (chave de 32, qualy de 2 rodadas) e o resultado sai marcado. Isso só muda os pontos de quem caiu na 1ª rodada.
- **Meta**: considera os pontos dos outros atletas como estão hoje. As exceções do regulamento para torneio que muda de semana entre um ano e outro (BT200, BT400, Sand Series e Mundial) não foram implementadas.
- **Ranking de mistas**: fora, como você decidiu. A ITF também não publica.
- **Ranking feminino**: baixado em 25/10 (2.178 jogadoras, ranking de 19/10). Atualize pelo botão do Início, como o masculino.
- **Cabeças do qualy**: o regulamento só fixa "no máximo 2 por seção". Usei a sua regra (metade da chave), limitada a 16.
