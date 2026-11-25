"""
Gerar certificados — recria a PKI do projeto em qualquer maquina
=================================================================
O repositorio guarda os certificados, mas nunca as chaves privadas: o
.gitignore bloqueia *.key. Entao quem clona o projeto roda este script
uma vez e obtem a PKI completa — uma CA propria e o certificado do proxy.

A chave privada nunca viaja. Cada maquina gera a sua, e quem clona fica
com uma autoridade certificadora dele, nao com uma copia da nossa.

A chave da CA e cifrada com AES-256 e pede senha. Para automatizar,
defina a variavel de ambiente BT_SENHA_CA: o script a entrega ao openssl
por 'env:', e nao na linha de comando, que apareceria na lista de
processos do sistema.

Rodar:  python gerar_certificados.py
"""

import os
import pathlib
import shutil
import subprocess
import sys

PASTA = pathlib.Path(__file__).resolve().parent
CA = PASTA / "infra" / "ca"
CERTS = PASTA / "infra" / "certs"

BITS_CA = 4096
BITS_SERVIDOR = 2048
DIAS_CA = 3650
DIAS_SERVIDOR = 365

EXTENSOES = (
    "basicConstraints = critical, CA:FALSE\n"
    "keyUsage = critical, digitalSignature, keyEncipherment\n"
    "extendedKeyUsage = serverAuth\n"
    "subjectAltName = DNS:localhost, DNS:proxy, IP:127.0.0.1\n"
)

CANDIDATOS = (
    r"C:\Program Files\Git\mingw64\bin\openssl.exe",
    r"C:\Program Files\Git\usr\bin\openssl.exe",
    r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
)


def achar_openssl() -> str:
    """Procura o openssl: variavel OPENSSL, PATH, locais conhecidos."""
    indicado = os.environ.get("OPENSSL", "")
    if indicado and pathlib.Path(indicado).exists():
        return indicado
    achado = shutil.which("openssl")
    if achado:
        return achado
    for caminho in CANDIDATOS:
        if pathlib.Path(caminho).exists():
            return caminho
    raise SystemExit(
        "openssl nao encontrado. Instale, ou aponte o caminho:\n"
        "  Windows: $env:OPENSSL = 'C:\\Program Files\\Git\\mingw64\\bin\\openssl.exe'\n"
        "  Linux:   sudo apt install openssl"
    )


def senha(flag: str) -> list[str]:
    """Senha da CA por variavel de ambiente, nunca na linha de comando."""
    if os.environ.get("BT_SENHA_CA"):
        return [flag, "env:BT_SENHA_CA"]
    return []


def rodar(openssl: str, *args: str) -> None:
    """Executa o openssl deixando a saida visivel (senha e prompts)."""
    resultado = subprocess.run((openssl, *args), text=True)
    if resultado.returncode != 0:
        raise SystemExit(f"\nFALHOU: openssl {args[0]} "
                         f"(codigo {resultado.returncode})")


def escrever(caminho: pathlib.Path, texto: str) -> None:
    """Grava em ASCII e com LF: sem BOM, que o openssl nao sabe ler."""
    caminho.write_text(texto, encoding="ascii", newline="\n")


def configuracao(unidade: str, nome_comum: str, ca: bool = False) -> str:
    """Identidade do titular. Sem e-mail: certificado e arquivo publico.

    Com ca=True acrescenta as extensoes da autoridade. Elas sao
    obrigatorias: -config substitui o openssl.cnf do sistema, entao sem
    declarar CA:TRUE aqui a CA nasce sem poder de assinar, e o
    "openssl verify" recusa a cadeia (error 79, invalid CA certificate).
    """
    texto = (
        "[req]\n"
        "prompt = no\n"
        "distinguished_name = dn\n"
    )
    if ca:
        texto += "x509_extensions = ca_ext\n"
    texto += (
        "\n"
        "[dn]\n"
        "C = BR\n"
        "ST = Parana\n"
        "L = Curitiba\n"
        "O = RankingBt\n"
        f"OU = {unidade}\n"
        f"CN = {nome_comum}\n"
    )
    if ca:
        texto += (
            "\n"
            "[ca_ext]\n"
            "basicConstraints = critical, CA:TRUE\n"
            "keyUsage = critical, keyCertSign, cRLSign\n"
            "subjectKeyIdentifier = hash\n"
        )
    return texto


def main() -> int:
    openssl = achar_openssl()
    print(f"openssl: {openssl}")
    rodar(openssl, "version")

    CA.mkdir(parents=True, exist_ok=True)
    CERTS.mkdir(parents=True, exist_ok=True)
    escrever(CA / "ca.cnf", configuracao("Autoridade Certificadora",
                                         "RankingBt Root CA", ca=True))
    escrever(CERTS / "servidor.cnf", configuracao("Servidor Web", "localhost"))
    escrever(CERTS / "servidor.ext", EXTENSOES)

    ca_key, ca_crt = CA / "ca.key", CA / "ca.crt"
    srv_key, srv_csr = CERTS / "servidor.key", CERTS / "servidor.csr"
    srv_crt = CERTS / "servidor.crt"

    if not ca_key.exists():
        print(f"\n--- chave da CA (RSA {BITS_CA}, cifrada com AES-256) ---")
        rodar(openssl, "genpkey", "-algorithm", "RSA",
              "-pkeyopt", f"rsa_keygen_bits:{BITS_CA}", "-aes256",
              "-out", str(ca_key), *senha("-pass"))
        # Chave nova invalida o certificado antigo: o par nao casa mais.
        ca_crt.unlink(missing_ok=True)
    else:
        print("\n--- chave da CA ja existe; reaproveitando ---")

    if not ca_crt.exists():
        print(f"\n--- certificado raiz autoassinado ({DIAS_CA} dias) ---")
        rodar(openssl, "req", "-x509", "-new", "-key", str(ca_key),
              "-sha256", "-days", str(DIAS_CA), "-out", str(ca_crt),
              "-config", str(CA / "ca.cnf"), *senha("-passin"))

    if not srv_key.exists():
        print(f"\n--- chave do servidor (RSA {BITS_SERVIDOR}, sem senha) ---")
        rodar(openssl, "genpkey", "-algorithm", "RSA",
              "-pkeyopt", f"rsa_keygen_bits:{BITS_SERVIDOR}",
              "-out", str(srv_key))
    else:
        print("\n--- chave do servidor ja existe; reaproveitando ---")

    # O certificado e sempre reemitido: garante que casa com a chave e a
    # CA atuais, mesmo que alguma das duas tenha sido trocada agora.
    print("\n--- pedido de certificado (CSR) ---")
    rodar(openssl, "req", "-new", "-key", str(srv_key), "-out", str(srv_csr),
          "-config", str(CERTS / "servidor.cnf"))

    print(f"\n--- assinatura pela CA ({DIAS_SERVIDOR} dias) ---")
    rodar(openssl, "x509", "-req", "-in", str(srv_csr),
          "-CA", str(ca_crt), "-CAkey", str(ca_key), "-CAcreateserial",
          "-days", str(DIAS_SERVIDOR), "-sha256",
          "-extfile", str(CERTS / "servidor.ext"), "-out", str(srv_crt),
          *senha("-passin"))

    print("\n--- conferindo a cadeia ---")
    rodar(openssl, "verify", "-CAfile", str(ca_crt), str(srv_crt))
    rodar(openssl, "x509", "-in", str(srv_crt), "-noout",
          "-subject", "-issuer", "-dates")
    print("\nPKI pronta. Agora: docker compose up -d --build")
    return 0


if __name__ == "__main__":
    sys.exit(main())