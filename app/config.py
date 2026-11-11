"""Configurações do TLP Técnico (lidas do ambiente / .env)."""
import json
import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")

APP_NAME = "TLP Técnico"
FUSO = ZoneInfo("America/Sao_Paulo")  # servidores costumam rodar em UTC

AMBIENTE = os.getenv("AMBIENTE", "dev").lower()
PRODUCAO = AMBIENTE in ("producao", "prod", "production")
CONFIAR_PROXY = os.getenv("CONFIAR_PROXY", "0") == "1"
DB_POOL = os.getenv("DB_POOL", "").lower()
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR.parent / 'demo_tlp_tecnico.db'}"

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if PRODUCAO:
        raise RuntimeError("Defina SECRET_KEY no ambiente de produção.")
    SECRET_KEY = secrets.token_urlsafe(32)  # dev: sessões somem a cada reinício

# --- Login (mesmo padrão do site: usuário + senha com bcrypt) ---------------
PERFIS = ("tecnico", "central", "admin")
SENHA_MIN = 8
MAX_FALHAS_LOGIN = 5
BLOQUEIO_MINUTOS = 10
SESSAO_HORAS = 12

# --- Fluxo de conclusão ------------------------------------------------------
# Status da base em que o técnico pode pedir "concluir com sucesso". A base só
# atualiza a cada ~30 min, então a OS em atendimento pode ainda constar como
# "em rota" ou "Não Iniciada".
STATUS_ELEGIVEIS = ("Iniciada", "em rota", "Não Iniciada")

PEDIDO_VALIDADE_MIN = 60       # pedido sem decisão expira
TESTE_TIMEOUT_INICIO_S = 30    # celular não reagiu ao comando de teste
TESTE_TIMEOUT_EXEC_S = 90      # teste começou e não terminou
TESTE_VALIDADE_MIN = 15        # idade máxima do teste para a central aprovar

POLL_TECNICO_MS = 2000
POLL_CENTRAL_MS = 3000

# --- Teste de rede -----------------------------------------------------------
TESTE_MODOS = {
    "completo": {"ping_n": 20, "down_ms": 5000, "up_ms": 5000},
    "rapido":   {"ping_n": 10, "down_ms": 4000, "up_ms": 0},
}
DOWN_MAX_BYTES = 60 * 1024 * 1024
# Download do teste servido por um endpoint externo gratuito (ex.: https://speed.cloudflare.com/__down),
# para não pagar saída de dados do servidor. Vazio = usa o download do próprio servidor.
DOWN_URL_EXTERNA = os.getenv("DOWN_URL_EXTERNA", "").strip()
DOWN_BYTES_EXTERNO = int(os.getenv("DOWN_BYTES_EXTERNO", "25000000"))

_CRITERIOS_PADRAO = {
    # tipo "max": quanto menor, melhor | tipo "min": quanto maior, melhor
    # bom = limite para ficar verde | minimo = limite para ficar amarelo (abaixo disso, vermelho)
    "latencia_ms":   {"rotulo": "Latência",  "unidade": "ms",   "tipo": "max", "bom": 80,  "minimo": 150},
    "jitter_ms":     {"rotulo": "Jitter",    "unidade": "ms",   "tipo": "max", "bom": 20,  "minimo": 40},
    "perda_pct":     {"rotulo": "Perda",     "unidade": "%",    "tipo": "max", "bom": 1,   "minimo": 3},
    "download_mbps": {"rotulo": "Download",  "unidade": "Mbps", "tipo": "min", "bom": 30,  "minimo": 10},
    "upload_mbps":   {"rotulo": "Upload",    "unidade": "Mbps", "tipo": "min", "bom": 10,  "minimo": 3},
}


def carregar_criterios() -> dict:
    """Critérios de 'rede OK'. Edite criterios_rede.json (na raiz) para ajustar."""
    criterios = json.loads(json.dumps(_CRITERIOS_PADRAO))
    arq = BASE_DIR.parent / "criterios_rede.json"
    if arq.exists():
        for chave, regra in json.loads(arq.read_text(encoding="utf-8")).items():
            if chave in criterios:
                criterios[chave].update(regra)
    return criterios


CRITERIOS = carregar_criterios()
