#!/bin/sh
# T06 - em HTTP o conteudo da conversa e legivel na rede.
tcpdump -i eth0 -w /tmp/http.pcap port 80 >/dev/null 2>&1 &
sleep 2
curl -s http://proxy/entrar -o /dev/null
sleep 2
killall tcpdump
echo "--- o que viajou na porta 80 ---"
tcpdump -r /tmp/http.pcap -A 2>/dev/null \
  | grep -aoE "GET /entrar HTTP/1.1|HTTP/1.1 301 Moved Permanently|Location: https://proxy/entrar" \
  | sort -u
