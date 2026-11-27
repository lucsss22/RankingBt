#!/bin/sh
# T11 - cinco senhas erradas, o suficiente para o vigia bloquear.
for i in 1 2 3 4 5; do
  curl -sk -m 10 -o /dev/null \
    -w "tentativa $i: HTTP %{http_code}\n" \
    -X POST https://proxy/entrar \
    -d "email=vitima@teste.com&senha=chute$i"
done
