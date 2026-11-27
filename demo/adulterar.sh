#!/bin/sh
# T09 e T10 - a cadeia aceita o log intacto e acusa a copia alterada.
echo "--- log original ---"
python auditoria.py /dados/seguranca.log
echo "--- copia com um e-mail trocado ---"
sed "s/vitima@teste.com/invasor@teste.com/" /dados/seguranca.log > /tmp/adulterado.log
python auditoria.py /tmp/adulterado.log
