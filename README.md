# RankingBt

App de auxílio de jovens pros de beach tennis: ranking, pontuação da ITF
e simulações de dupla, com acesso por convite.

A branch `trabalho-seguranca` contém o reforço de segurança da aplicação:
TLS com PKI própria, log de auditoria assinado e bloqueio automático no
firewall. A aplicação-base foi gerada com auxílio de IA; a declaração
completa está no documento-resumo do trabalho.

## Arquitetura

Quatro contêineres em duas redes IP distintas:

```
atacante ──┐
           ├── rede externa 172.29.0.0/24 ─── proxy (Nginx, TLS 1.3)
                                               │  + defesa (vigia)
                                 rede interna 172.28.0.0/24
                                               │
                                              app (FastAPI)
```

- **proxy** termina o TLS e é o único nó com porta publicada.
- **app** não tem porta publicada e só existe na rede interna.
- **defesa** compartilha o namespace de rede do proxy e escreve as regras
  de firewall; roda com todas as capabilities removidas exceto NET_ADMIN.
- **atacante** está em outra rede e não tem rota até o app.

## Requisitos

- Docker e Docker Compose
- OpenSSL (no Windows, acompanha o Git for Windows)
- Python 3.11+ (apenas para gerar os certificados e verificar o log)

## Instalação e execução

As chaves privadas não são versionadas. Gere a PKI local primeiro:

```
python gerar_certificados.py
```

O script pede uma senha para proteger a chave da CA. Para não digitar,
defina antes a variável de ambiente `BT_SENHA_CA`.

Depois suba o ambiente:

```
docker compose up -d --build
```

Acesse **https://localhost**. O navegador vai avisar que o certificado não
é confiável: isso é esperado e correto, porque a CA que o assinou foi
criada por este script e não está na lista de autoridades do sistema.
Prossiga pelo aviso, ou instale `infra/ca/ca.crt` como raiz confiável.

Crie o primeiro administrador com:

```
docker compose exec app python gerenciar.py admin seu@email.com
```

## Reproduzir os testes

| ID | O que comprova | Comando |
|----|----------------|---------|
| T01 | TLS 1.3 e cadeia válida | `openssl s_client -connect localhost:443 -CAfile infra/ca/ca.crt` |
| T02 | Extensões do certificado | `openssl x509 -in infra/certs/servidor.crt -noout -text` |
| T03 | HTTP é redirecionado | `curl -I http://localhost/` |
| T04 | App inalcançável pelo atacante | `docker exec bt-atacante ping -c1 172.28.0.10` |
| T05 | Segmentação de DNS | `docker exec bt-atacante nslookup app` |
| T06 | Tráfego HTTP é legível | `docker exec bt-atacante tcpdump -i eth0 -A port 80` |
| T07 | Tráfego HTTPS é ilegível | mesma captura, trocando para `port 443` |
| T08 | Log de auditoria gravado | `docker compose exec app cat /dados/seguranca.log` |
| T09 | Cadeia do log íntegra | `docker compose exec app python auditoria.py` |
| T10 | Adulteração detectada | alterar uma linha do log e repetir o T09 |
| T11 | Detecção de força bruta | `docker compose logs defesa` |
| T12 | Bloqueio no firewall | `docker exec bt-defesa iptables -L INPUT -n` |
| T13 | Tráfego legítimo preservado | `curl -sk https://localhost/entrar` |

O contêiner atacante já vem com `curl`, `tcpdump` e `nmap` instalados.

Para liberar um IP bloqueado durante os testes:

```
docker exec bt-defesa iptables -D INPUT -s <ip> -j DROP
```

## Arquivos de segurança

| Arquivo | Função |
|---------|--------|
| `gerar_certificados.py` | Cria a CA e emite o certificado do servidor |
| `auditoria.py` | Log de eventos com HMAC encadeado; verifica a cadeia |
| `vigia.py` | Lê o log, detecta abuso e bloqueia no iptables |
| `infra/nginx/rankingbt.conf` | TLS, redirecionamento e cabeçalhos do proxy |
| `Dockerfile` | Imagem do app, usuário não-root |
| `Dockerfile.defesa` | Imagem do vigia, com iptables |
| `Dockerfile.atacante` | Imagem do atacante, com as ferramentas de teste |
| `docker-compose.yml` | Topologia, redes, volumes e capabilities |

## Chaves privadas

`*.key` está no `.gitignore` e no `.dockerignore`. Nenhuma chave privada
entra no repositório nem em camada de imagem — camada de imagem é
imutável, e segredo copiado para dentro dela não sai mais. Cada máquina
gera as suas chaves com `gerar_certificados.py`.
