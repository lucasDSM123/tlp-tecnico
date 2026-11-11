"""Autenticação — mesmo padrão do site: usuário + senha, bcrypt, histórico de acessos.

Diferenças em relação ao site: cada usuário tem um perfil (tecnico/central/admin) e
a conta é bloqueada por alguns minutos após várias senhas erradas.
"""
from datetime import timedelta

import bcrypt
from sqlalchemy import insert, select, update

from app import config
from app.db import agora_utc, engine, historico_acessos, usuarios

# Hash falso: garante que "usuário inexistente" gasta o mesmo tempo que "senha errada".
_HASH_FALSO = bcrypt.hashpw(b"nao-existe", bcrypt.gensalt()).decode()


def _hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def criar_usuario(login: str, nome: str, senha: str, perfil: str = "tecnico",
                  matricula: str | None = None) -> tuple[bool, str]:
    login = login.strip().lower()
    if perfil not in config.PERFIS:
        return False, f"Perfil inválido (use: {', '.join(config.PERFIS)})."
    if len(login) < 3:
        return False, "Login precisa ter ao menos 3 caracteres."
    if len(senha) < config.SENHA_MIN:
        return False, f"A senha precisa ter ao menos {config.SENHA_MIN} caracteres."
    if perfil == "tecnico" and not matricula:
        return False, "Técnico precisa de matrícula (liga o usuário às OS dele na base)."
    with engine.begin() as conn:
        if conn.execute(select(usuarios.c.id).where(usuarios.c.login == login)).first():
            return False, f"O login '{login}' já existe."
        conn.execute(insert(usuarios).values(
            login=login, nome=nome.strip(), senha_hash=_hash(senha), perfil=perfil,
            matricula=(str(matricula).strip() if matricula else None), ativo=True,
            falhas_login=0, criado_em=agora_utc(),
        ))
    return True, "ok"


def alterar_senha(login: str, nova_senha: str) -> bool:
    if len(nova_senha) < config.SENHA_MIN:
        return False
    with engine.begin() as conn:
        r = conn.execute(update(usuarios).where(usuarios.c.login == login.strip().lower())
                         .values(senha_hash=_hash(nova_senha), falhas_login=0, bloqueado_ate=None))
    return r.rowcount > 0


def verificar_login(login: str, senha: str, ip: str | None = None) -> dict | None:
    """Devolve o usuário se login/senha estiverem certos; senão None (sem dizer o motivo)."""
    login = login.strip().lower()
    agora = agora_utc()
    with engine.begin() as conn:
        u = conn.execute(select(usuarios).where(usuarios.c.login == login)).mappings().first()

        if u is None or not u["ativo"]:
            bcrypt.checkpw(senha.encode("utf-8"), _HASH_FALSO.encode())
            return None

        if u["bloqueado_ate"] and u["bloqueado_ate"] > agora:
            return None

        if not bcrypt.checkpw(senha.encode("utf-8"), u["senha_hash"].encode("utf-8")):
            falhas = (u["falhas_login"] or 0) + 1
            valores = {"falhas_login": falhas}
            if falhas >= config.MAX_FALHAS_LOGIN:
                valores = {"falhas_login": 0,
                           "bloqueado_ate": agora + timedelta(minutes=config.BLOQUEIO_MINUTOS)}
            conn.execute(update(usuarios).where(usuarios.c.id == u["id"]).values(**valores))
            return None

        conn.execute(update(usuarios).where(usuarios.c.id == u["id"])
                     .values(falhas_login=0, bloqueado_ate=None))
        conn.execute(insert(historico_acessos).values(
            usuario_id=u["id"], login=u["login"], ip=ip, acessado_em=agora))
        return {"id": u["id"], "login": u["login"], "nome": u["nome"],
                "perfil": u["perfil"], "matricula": u["matricula"]}


def carregar_usuario(usuario_id: int) -> dict | None:
    with engine.connect() as conn:
        u = conn.execute(select(usuarios).where(usuarios.c.id == usuario_id)).mappings().first()
    if u is None or not u["ativo"]:
        return None
    return {"id": u["id"], "login": u["login"], "nome": u["nome"],
            "perfil": u["perfil"], "matricula": u["matricula"]}
