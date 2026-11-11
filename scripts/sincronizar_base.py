"""Copia as OS recentes da base tratada para a tabela os_base do TLP Técnico.

A cópia é enxuta (só as colunas necessárias e os últimos N dias) e fica no projeto
NOVO do Neon, assim o app do técnico não consome a cota do banco do dashboard.

Origem (escolha uma):
    --excel caminho\\PRODUCAO_TLP_TRATADA.xlsx      (o mesmo arquivo que o upload_dados.py lê)
    --origem-url postgresql://...                    (ou variável ORIGEM_DATABASE_URL: banco do dashboard)

Exemplos:
    python -m scripts.sincronizar_base --excel "D:\\DASH EM STREAMILIT\\TLP_ANALYTICS\\data\\PRODUCAO_TLP_TRATADA.xlsx"
    python -m scripts.sincronizar_base --dias 30

Dá para encadear como mais um passo depois do upload_dados.py no orquestrador.
"""
import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, delete, insert  # noqa: E402

from app.db import _normalizar_url, agora_utc, engine, init_db, os_base  # noqa: E402
from app.servico import hoje_brt  # noqa: E402

TABELA_ORIGEM = "producao_tlp_tratada"
MAPA = {  # coluna na base -> coluna em os_base
    "numero_atividade": "numero_atividade", "Ordem de Serviço": "ordem_servico",
    "Login Técnico": "login_tecnico", "Técnico": "tecnico", "Data": "data", "Janela": "janela",
    "Início": "inicio", "Término": "termino", "Status": "status",
    "Tipo de Atividade": "tipo_atividade", "Cidade": "cidade", "Bairro": "bairro",
    "Cluster": "cluster", "Supervisor": "supervisor",
}


def _id_texto(v):
    if pd.isna(v):
        return None
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        return str(v).strip() or None


def _texto(v):
    return None if pd.isna(v) else str(v).strip()


def ler_origem(excel: str | None, url: str | None) -> pd.DataFrame:
    if excel:
        print(f"Lendo {excel} ...")
        try:
            import python_calamine  # noqa: F401  (leitor rápido, se estiver instalado)
            motor = "calamine"
        except ImportError:
            motor = "openpyxl"
        return pd.read_excel(excel, engine=motor, usecols=list(MAPA))
    colunas = ", ".join(f'"{c}"' for c in MAPA)
    print("Lendo a base do Neon de origem ...")
    eng = create_engine(_normalizar_url(url))
    with eng.connect() as conn:
        return pd.read_sql(f'SELECT {colunas} FROM "{TABELA_ORIGEM}"', conn)


def transformar(df: pd.DataFrame, dias: int) -> list[dict]:
    df = df[list(MAPA)].rename(columns=MAPA).copy()
    data = pd.to_datetime(df["data"], format="%d/%m/%y", errors="coerce")
    sem_ano_curto = data.isna()
    if sem_ano_curto.any():
        data[sem_ano_curto] = pd.to_datetime(df.loc[sem_ano_curto, "data"], dayfirst=True, errors="coerce")
    df["data"] = data.dt.strftime("%Y-%m-%d")

    corte = (hoje_brt() - timedelta(days=dias)).isoformat()
    df = df[df["data"].notna() & (df["data"] >= corte)]

    df["numero_atividade"] = df["numero_atividade"].map(_id_texto)
    df["login_tecnico"] = df["login_tecnico"].map(_id_texto)
    df = df[df["numero_atividade"].notna() & df["login_tecnico"].notna()]
    for c in ("ordem_servico", "tecnico", "janela", "inicio", "termino", "status",
              "tipo_atividade", "cidade", "bairro", "cluster", "supervisor"):
        df[c] = df[c].map(_texto)
    df = df.drop_duplicates(subset="numero_atividade", keep="last")
    df["atualizado_em"] = agora_utc()
    return df.astype(object).where(df.notna(), None).to_dict("records")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--excel")
    ap.add_argument("--origem-url", default=os.getenv("ORIGEM_DATABASE_URL"))
    ap.add_argument("--dias", type=int, default=45, help="quantos dias para trás copiar (padrão 45)")
    a = ap.parse_args()
    if not a.excel and not a.origem_url:
        print("[ERRO] Informe --excel ou --origem-url (ou ORIGEM_DATABASE_URL).")
        return 1

    try:
        registros = transformar(ler_origem(a.excel, a.origem_url), a.dias)
    except Exception as e:
        print(f"[ERRO] Falha ao ler a origem: {e}")
        return 1
    if not registros:
        print("[AVISO] Nada para copiar (base vazia ou fora do período). Destino mantido.")
        return 1

    init_db()
    corte = min(r["data"] for r in registros)
    with engine.begin() as conn:  # tudo ou nada
        conn.execute(delete(os_base).where(os_base.c.data >= corte))
        for i in range(0, len(registros), 2000):
            conn.execute(insert(os_base), registros[i:i + 2000])
    print(f"OK: {len(registros)} OS copiadas (a partir de {corte}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
