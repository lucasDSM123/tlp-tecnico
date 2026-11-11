import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_dir}/teste.db"
os.environ["SECRET_KEY"] = "chave-de-teste"
os.environ["AMBIENTE"] = "dev"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, insert  # noqa: E402

from app import auth  # noqa: E402
from app.db import agora_utc, engine, init_db, metadata, os_base  # noqa: E402
from app.main import app  # noqa: E402
from app.servico import hoje_brt  # noqa: E402

H = {"X-TLP": "1"}


@pytest.fixture()
def base():
    """Banco limpo + 2 técnicos, 1 central e OS de hoje."""
    init_db()
    with engine.begin() as conn:
        for t in reversed(metadata.sorted_tables):
            conn.execute(delete(t))
    auth.criar_usuario("tec1", "Técnico Um", "senha-forte-1", "tecnico", "111")
    auth.criar_usuario("tec2", "Técnico Dois", "senha-forte-2", "tecnico", "222")
    auth.criar_usuario("cl1", "Central Um", "senha-forte-3", "central")
    hoje = hoje_brt().isoformat()
    def os(n, mat, st, data=hoje):
        return dict(numero_atividade=n, ordem_servico="OS-" + n, login_tecnico=mat, tecnico="X", data=data,
                    janela="10:30 - 12:30", status=st, tipo_atividade="Instalação", cidade="Blumenau",
                    bairro="Centro", atualizado_em=agora_utc())
    with engine.begin() as conn:
        conn.execute(insert(os_base), [
            os("A1", "111", "Iniciada"), os("A2", "111", "Concluída"), os("A3", "111", "Suspensa"),
            os("B1", "222", "Iniciada"), os("OLD", "111", "Iniciada", "2020-01-01"),
        ])


def logar(login, senha):
    c = TestClient(app)
    r = c.post("/login", data={"login": login, "senha": senha}, follow_redirects=False)
    return c, r


@pytest.fixture()
def tec(base):
    c, r = logar("tec1", "senha-forte-1"); assert r.status_code == 303; return c


@pytest.fixture()
def tec2(base):
    c, r = logar("tec2", "senha-forte-2"); assert r.status_code == 303; return c


@pytest.fixture()
def cl(base):
    c, r = logar("cl1", "senha-forte-3"); assert r.status_code == 303; return c
