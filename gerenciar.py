"""
BT Ranking — administracao pelo terminal do PC
==============================================
Convites e administradores. Fica fora do app web de proposito: so quem tem
acesso a este computador da poder de administrador.

Uso:
    python gerenciar.py convite [--dias 14]     cria um convite e mostra o codigo
    python gerenciar.py convites                lista os convites
    python gerenciar.py admin EMAIL             da acesso de administrador
    python gerenciar.py admin EMAIL --remover   tira o acesso

O administrador ve a tela de Convites no app e o botao de atualizar o ranking.
"""

import argparse
import sys

import atletas


def main() -> int:
    parser = argparse.ArgumentParser(description="Convites e administradores do BT Ranking.")
    comandos = parser.add_subparsers(dest="comando", required=True)

    convite = comandos.add_parser("convite", help="cria um convite")
    convite.add_argument("--dias", type=int, default=atletas.VALIDADE_CONVITE_DIAS,
                         help=f"validade em dias (padrao {atletas.VALIDADE_CONVITE_DIAS})")
    comandos.add_parser("convites", help="lista os convites")
    admin = comandos.add_parser("admin", help="liga ou desliga o administrador")
    admin.add_argument("email")
    admin.add_argument("--remover", action="store_true", help="tira o acesso de administrador")

    args = parser.parse_args()
    conn = atletas.conectar()
    try:
        if args.comando == "convite":
            if args.dias < 1:
                parser.error("--dias precisa ser 1 ou mais")
            codigo = atletas.criar_convite(conn, validade_dias=args.dias)
            print(f"Convite: {codigo}  (vale {args.dias} dia(s))")
            print(f"Link:    <endereco do ngrok>/cadastro?convite={codigo}")

        elif args.comando == "convites":
            lista = atletas.listar_convites(conn)
            if not lista:
                print("Nenhum convite criado ainda.")
            for c in lista:
                usado = f" por {c['usado_por_nome']}" if c["usado_por_nome"] else ""
                print(f"{c['codigo']}  {c['situacao']:<10} ate {c['expira_em'][:10]}{usado}")

        elif args.comando == "admin":
            atleta = atletas.definir_admin(conn, args.email, admin=not args.remover)
            if atleta is None:
                print(f"Nenhuma conta com o e-mail {args.email}.", file=sys.stderr)
                return 1
            estado = "agora e administrador" if atleta.admin else "nao e mais administrador"
            print(f"{atleta.nome} ({atleta.email}) {estado}.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
