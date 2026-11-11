"""Cria um usuário do TLP Técnico (técnico, central ou admin).

Exemplos (rode na pasta TLP_TECNICO):
    python -m scripts.criar_usuario --login joao.silva --nome "João Silva" --perfil tecnico --matricula 12345
    python -m scripts.criar_usuario --login central01 --nome "Central Contorno 01" --perfil central

A senha é pedida no terminal (não aparece na tela nem fica no histórico).
O usuário do técnico é NOVO e separado da matrícula: a matrícula só liga o login às OS dele.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth, config  # noqa: E402
from app.db import init_db  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login", required=True)
    ap.add_argument("--nome", required=True)
    ap.add_argument("--perfil", choices=config.PERFIS, default="tecnico")
    ap.add_argument("--matricula", help="Login Técnico da base (obrigatório para perfil tecnico)")
    ap.add_argument("--redefinir-senha", action="store_true", help="só troca a senha de um login existente")
    a = ap.parse_args()

    init_db()
    senha = getpass.getpass("Senha: ")
    if senha != getpass.getpass("Confirme a senha: "):
        print("[ERRO] As senhas não coincidem.")
        return 1

    if a.redefinir_senha:
        ok = auth.alterar_senha(a.login, senha)
        print("Senha alterada." if ok else "[ERRO] Login não encontrado ou senha curta demais.")
        return 0 if ok else 1

    ok, msg = auth.criar_usuario(a.login, a.nome, senha, a.perfil, a.matricula)
    print(f"Usuário '{a.login}' criado ({a.perfil})." if ok else f"[ERRO] {msg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
