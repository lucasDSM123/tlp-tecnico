"""Banco do TLP Técnico (Neon/PostgreSQL em produção, SQLite nos testes locais)."""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, MetaData,
    String, Table, Text, create_engine,
)
from sqlalchemy.pool import NullPool

from app import config


def agora_utc() -> datetime:
    """UTC 'ingênuo' (sem tzinfo): é o que gravamos no banco."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    """ISO em UTC com 'Z' — o navegador converte para o horário local."""
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


metadata = MetaData()

usuarios = Table(
    "usuarios", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("login", String(50), unique=True, nullable=False),
    Column("nome", String(120), nullable=False),
    Column("senha_hash", Text, nullable=False),
    Column("perfil", String(20), nullable=False, default="tecnico"),
    Column("matricula", String(30)),  # liga o técnico às OS da base (Login Técnico)
    Column("ativo", Boolean, nullable=False, default=True),
    Column("falhas_login", Integer, nullable=False, default=0),
    Column("bloqueado_ate", DateTime),
    Column("criado_em", DateTime, nullable=False, default=agora_utc),
)

historico_acessos = Table(
    "historico_acessos", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("usuario_id", Integer, ForeignKey("usuarios.id"), nullable=False, index=True),
    Column("login", String(50), nullable=False),
    Column("ip", String(64)),
    Column("acessado_em", DateTime, nullable=False, default=agora_utc, index=True),
)

# Cópia enxuta da base tratada (sem dados do cliente além do necessário).
os_base = Table(
    "os_base", metadata,
    Column("numero_atividade", String(30), primary_key=True),
    Column("ordem_servico", String(60)),
    Column("login_tecnico", String(30), index=True),
    Column("tecnico", String(120)),
    Column("data", String(10), index=True),  # AAAA-MM-DD
    Column("janela", String(20)),
    Column("inicio", String(8)),
    Column("termino", String(8)),
    Column("status", String(30)),
    Column("tipo_atividade", String(80)),
    Column("cidade", String(80)),
    Column("bairro", String(80)),
    Column("cluster", String(60)),
    Column("supervisor", String(120)),
    Column("atualizado_em", DateTime, default=agora_utc),
)

pedidos_conclusao = Table(
    "pedidos_conclusao", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("numero_atividade", String(30), nullable=False, index=True),
    Column("ordem_servico", String(60)),
    Column("tecnico_id", Integer, ForeignKey("usuarios.id"), nullable=False, index=True),
    Column("tecnico_nome", String(120)),
    Column("cidade", String(80)),
    Column("bairro", String(80)),
    Column("janela", String(20)),
    Column("tipo_atividade", String(80)),
    # aguardando | testando | em_analise | aprovado | recusado | cancelado | expirado
    Column("status", String(20), nullable=False, default="aguardando", index=True),
    Column("criado_em", DateTime, nullable=False, default=agora_utc),
    Column("decidido_por", Integer, ForeignKey("usuarios.id")),
    Column("decidido_por_nome", String(120)),
    Column("decidido_em", DateTime),
    Column("motivo", Text),
)

testes_rede = Table(
    "testes_rede", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("pedido_id", Integer, ForeignKey("pedidos_conclusao.id"), nullable=False, index=True),
    Column("modo", String(10), nullable=False, default="completo"),
    Column("solicitado_por", Integer, ForeignKey("usuarios.id")),
    Column("solicitado_em", DateTime, nullable=False, default=agora_utc),
    Column("iniciado_em", DateTime),
    Column("finalizado_em", DateTime),
    # solicitado | em_andamento | concluido | falhou | sem_resposta
    Column("status", String(20), nullable=False, default="solicitado"),
    Column("fase", String(20)),  # latencia | download | upload (progresso ao vivo)
    Column("latencia_ms", Float),
    Column("jitter_ms", Float),
    Column("perda_pct", Float),
    Column("download_mbps", Float),
    Column("upload_mbps", Float),
    Column("bytes_down_cliente", Integer),
    Column("bytes_up_cliente", Integer),
    Column("bytes_down_servidos", Integer, nullable=False, default=0),
    Column("bytes_up_recebidos", Integer, nullable=False, default=0),
    Column("resultado", String(12)),  # ok | atencao | reprovado
    Column("detalhes", Text),         # JSON com o nível de cada métrica e alertas
    Column("ip_publico", String(64)),
    Column("user_agent", String(300)),
    Column("tipo_conexao", String(30)),
)
Index("ix_testes_pedido_solicitado", testes_rede.c.pedido_id, testes_rede.c.solicitado_em)


def _normalizar_url(url: str) -> str:
    """Força o driver psycopg2 (mesma regra do site atual)."""
    for prefixo in ("postgres://", "postgresql+psycopg://", "postgresql://"):
        if url.startswith(prefixo):
            return "postgresql+psycopg2://" + url[len(prefixo):]
    return url


def criar_engine(url: str | None = None):
    url = _normalizar_url(url or config.DATABASE_URL)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    opcoes = {"pool_pre_ping": True}
    if config.DB_POOL == "null":
        opcoes["poolclass"] = NullPool
    else:
        opcoes.update(pool_recycle=300, pool_size=5, max_overflow=5)
    return create_engine(url, **opcoes)


engine = criar_engine()


def init_db():
    """Cria as tabelas que ainda não existem (seguro repetir)."""
    metadata.create_all(engine)
