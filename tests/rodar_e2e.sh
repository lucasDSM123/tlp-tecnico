#!/bin/bash
# uso: rodar_e2e.sh [com_proxy]
cd "$(dirname "$0")/.."
export DATABASE_URL="sqlite:////tmp/e2e_ui.db" SECRET_KEY=x AMBIENTE=dev
rm -f /tmp/e2e_ui.db
python3 - <<'PY'
from app import auth
from app.db import init_db, engine, os_base, agora_utc
from app.servico import hoje_brt
from sqlalchemy import insert
init_db()
auth.criar_usuario("tec1","Técnico Um","senha-forte-1","tecnico","111")
auth.criar_usuario("cl1","Central Um","senha-forte-3","central")
h=hoje_brt().isoformat()
def o(n,st,j): return dict(numero_atividade=n,ordem_servico="OS-"+n,login_tecnico="111",tecnico="X",data=h,janela=j,status=st,tipo_atividade="Instalação Fibra",cidade="Blumenau",bairro="Itoupava Norte",atualizado_em=agora_utc())
with engine.begin() as c:
    c.execute(insert(os_base),[o("A1","Iniciada","10:30 - 12:30"),o("A2","Concluída","08:30 - 10:30"),o("A3","Suspensa","14:00 - 16:00")])
PY
python3 -m uvicorn app.main:app --port 8765 --log-level warning & P1=$!
if [ "$1" = "com_proxy" ]; then python3 tests/proxy_lento.py 20 5 30 & P2=$!; export BASE=http://127.0.0.1:8766; fi
sleep 2.5
python3 tests/e2e_ui.py
RC=$?
kill $P1 $P2 2>/dev/null
exit $RC
