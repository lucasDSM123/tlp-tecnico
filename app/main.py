"""TLP Técnico — conclusão de atividade com validação de rede pela central."""
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import api, auth, config
from app.api import ip_cliente
from app.db import init_db
from app.servico import ErroNegocio

BASE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=config.APP_NAME, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, session_cookie="tlp_sessao",
                   max_age=config.SESSAO_HORAS * 3600, same_site="lax", https_only=config.PRODUCAO)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.include_router(api.router)
templates = Jinja2Templates(directory=BASE / "templates")

def _origem_download_externo() -> str:
    if not config.DOWN_URL_EXTERNA:
        return ""
    u = urlsplit(config.DOWN_URL_EXTERNA)
    return f" {u.scheme}://{u.netloc}" if u.scheme and u.netloc else ""


_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'" + _origem_download_externo() +
        "; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


@app.middleware("http")
async def cabecalhos_seguranca(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers["Content-Security-Policy"] = _CSP
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["X-Frame-Options"] = "DENY"
    resposta.headers["Referrer-Policy"] = "same-origin"
    resposta.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    if request.url.path.startswith(("/api", "/login", "/tecnico", "/central")):
        resposta.headers.setdefault("Cache-Control", "no-store")
    return resposta


@app.exception_handler(ErroNegocio)
async def tratar_erro_negocio(request: Request, exc: ErroNegocio):
    return JSONResponse({"erro": exc.mensagem}, status_code=exc.codigo)


@app.exception_handler(Exception)
async def tratar_erro_inesperado(request: Request, exc: Exception):
    print(f"[ERRO] {request.method} {request.url.path}: {exc!r}")
    return JSONResponse({"erro": "Erro interno. Tente novamente."}, status_code=500)


def _destino(perfil: str) -> str:
    return "/tecnico" if perfil == "tecnico" else "/central"


def _usuario_da_pagina(request: Request, *perfis: str):
    uid = request.session.get("uid")
    u = auth.carregar_usuario(uid) if uid else None
    if not u:
        request.session.clear()
        return None, RedirectResponse("/login", status_code=303)
    if u["perfil"] not in perfis:
        return None, RedirectResponse(_destino(u["perfil"]), status_code=303)
    return u, None


@app.get("/")
def raiz(request: Request):
    uid = request.session.get("uid")
    u = auth.carregar_usuario(uid) if uid else None
    return RedirectResponse(_destino(u["perfil"]) if u else "/login", status_code=303)


@app.get("/login")
def pagina_login(request: Request):
    return templates.TemplateResponse(request, "login.html", {"app_nome": config.APP_NAME, "erro": None})


@app.post("/login")
def entrar(request: Request, login: str = Form(""), senha: str = Form("")):
    usuario = auth.verificar_login(login, senha, ip_cliente(request)) if login and senha else None
    if not usuario:
        return templates.TemplateResponse(
            request, "login.html",
            {"app_nome": config.APP_NAME, "erro": "Usuário ou senha inválidos."}, status_code=401)
    request.session.clear()  # evita fixação de sessão
    request.session.update({"uid": usuario["id"], "perfil": usuario["perfil"]})
    return RedirectResponse(_destino(usuario["perfil"]), status_code=303)


@app.post("/logout")
def sair(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/tecnico")
def pagina_tecnico(request: Request):
    u, redir = _usuario_da_pagina(request, "tecnico")
    if redir:
        return redir
    return templates.TemplateResponse(request, "tecnico.html", {
        "app_nome": config.APP_NAME, "usuario": u, "poll_ms": config.POLL_TECNICO_MS})


@app.get("/central")
def pagina_central(request: Request):
    u, redir = _usuario_da_pagina(request, "central", "admin")
    if redir:
        return redir
    return templates.TemplateResponse(request, "central.html", {
        "app_nome": config.APP_NAME, "usuario": u, "poll_ms": config.POLL_CENTRAL_MS})
