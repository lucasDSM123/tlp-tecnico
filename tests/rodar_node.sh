#!/bin/bash
cd "$(dirname "$0")/.."
export DATABASE_URL="sqlite:////tmp/e2e_node.db" SECRET_KEY=x AMBIENTE=dev
rm -f /tmp/e2e_node.db
python3 - <<'PY'
from app import auth
from app.db import init_db, engine, os_base, agora_utc
from app.servico import hoje_brt
from sqlalchemy import insert
init_db()
auth.criar_usuario("tec1","Técnico Um","senha-forte-1","tecnico","111")
auth.criar_usuario("cl1","Central Um","senha-forte-3","central")
with engine.begin() as c:
    c.execute(insert(os_base),[dict(numero_atividade="A1",ordem_servico="OS-A1",login_tecnico="111",tecnico="X",data=hoje_brt().isoformat(),janela="10:30 - 12:30",status="Iniciada",tipo_atividade="Instalação",cidade="Blumenau",bairro="Centro",atualizado_em=agora_utc())])
PY
python3 -m uvicorn app.main:app --port 8765 --log-level warning &
PID=$!
sleep 2.5
node tests/node_rede.js
RC=$?
kill $PID
exit $RC
