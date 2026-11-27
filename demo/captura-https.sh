#!/bin/sh
# T07 - a mesma conversa em HTTPS, com uma senha dentro, e ilegivel.
SENHA="SENHA_SECRETA_123"
tcpdump -i eth0 -w /tmp/https.pcap port 443 >/dev/null 2>&1 &
sleep 2
curl -sk https://proxy/entrar -X POST -o /dev/null \
  -d "email=vitima@teste.com&senha=$SENHA"
sleep 2
killall tcpdump
echo "--- procurando a senha na captura da porta 443 ---"
printf "ocorrencias de %s: " "$SENHA"
tcpdump -r /tmp/https.pcap -A 2>/dev/null | grep -ac "$SENHA"
printf "linhas HTTP legiveis:  "
tcpdump -r /tmp/https.pcap -A 2>/dev/null | grep -acE "GET |POST |HTTP/1"
echo "--- amostra do que de fato passou ---"
tcpdump -r /tmp/https.pcap -X 2>/dev/null | sed -n "/length 1[0-9][0-9]/,+3p" | head -5
