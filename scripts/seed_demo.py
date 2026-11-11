"""Dados FICTÍCIOS para testar o app localmente (não toca em dados reais).

    python -m scripts.seed_demo

Cria 1 técnico (matrícula 9001) com atividades de hoje, 1 usuário da central e imprime
as senhas geradas. Use só em banco de teste.
"""
import secrets
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, insert  # noqa: E402

from app import auth  # noqa: E402
from app.db import agora_utc, engine, init_db, os_base  # noqa: E402
from app.servico import hoje_brt  # noqa: E402

MAT = "9001"
MODELO = [  # (janela, status, tipo, cidade, bairro)
    ("08:30 - 10:30", "Concluída", "Instalação Fibra", "Blumenau", "Velha"),
    ("10:30 - 12:30", "Iniciada", "Instalação Fibra", "Blumenau", "Itoupava Norte"),
    ("14:00 - 16:00", "Não Iniciada", "Reparo", "Pomerode", "Centro"),
    ("16:00 - 18:00", "Não Iniciada", "Instalação Fibra", "Indaial", "Estrada das Areias"),
    ("09:30 - 11:30", "Suspensa", "Reparo", "Gaspar", "Bela Vista"),
    ("08:30 - 10:30", "Não Concluída", "Instalação Fibra", "Blumenau", "Garcia"),
]


def main() -> None:
    init_db()
    hoje, ontem = hoje_brt(), hoje_brt() - timedelta(days=1)
    linhas = []
    for dia, prefixo in ((hoje, "D"), (ontem, "O")):
        for i, (jan, st, tipo, cid, bai) in enumerate(MODELO, 1):
            linhas.append(dict(
                numero_atividade=f"DEMO-{prefixo}{i:03d}", ordem_servico=f"OS-DEMO-{prefixo}{i:03d}",
                login_tecnico=MAT, tecnico="TECNICO DEMO", data=dia.isoformat(), janela=jan,
                inicio=None, termino=None, status=st if prefixo == "D" else "Concluída",
                tipo_atividade=tipo, cidade=cid, bairro=bai, cluster="DEMO", supervisor="SUPERVISOR DEMO",
                atualizado_em=agora_utc()))
    with engine.begin() as conn:
        conn.execute(delete(os_base).where(os_base.c.numero_atividade.like("DEMO-%")))
        conn.execute(insert(os_base), linhas)

    senha_t, senha_c = secrets.token_urlsafe(9), secrets.token_urlsafe(9)
    for login, nome, senha, perfil, mat in (
        ("tecnico.demo", "Técnico Demo", senha_t, "tecnico", MAT),
        ("central.demo", "Central Demo", senha_c, "central", None),
    ):
        if not auth.criar_usuario(login, nome, senha, perfil, mat)[0]:
            auth.alterar_senha(login, senha)
    print("Dados de demonstração criados.\n")
    print(f"  técnico : tecnico.demo / {senha_t}")
    print(f"  central : central.demo / {senha_c}")


if __name__ == "__main__":
    main()
