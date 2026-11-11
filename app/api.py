"""Rotas JSON: técnico, central e endpoints do teste de rede."""
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

from app import auth, config, servico
from app.db import engine

router = APIRouter(prefix="/api")

# ------------------------------------------------------------------ dependências
def ip_cliente(request: Request) -> str | None:
    if config.CONFIAR_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def csrf(request: Request) -> None:
    """Exige um cabeçalho próprio nas requisições que alteram dados: um site de
    terceiros não consegue enviá-lo sem passar pelo CORS (que não liberamos)."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-tlp") != "1":
        raise HTTPException(403, "Requisição não autorizada.")


def exigir(*perfis: str):
    def dep(request: Request) -> dict:
        uid = request.session.get("uid")
        usuario = auth.carregar_usuario(uid) if uid else None
        if not usuario:
            raise HTTPException(401, "Sessão expirada. Entre novamente.")
        if usuario["perfil"] not in perfis:
            raise HTTPException(403, "Sem permissão.")
        return usuario
    return dep


def sessao_tecnico_leve(request: Request) -> int:
    """Só confere a assinatura do cookie (sem ir ao banco): o ping mede latência e
    não pode embutir o tempo de uma consulta ao Neon."""
    if request.session.get("perfil") != "tecnico" or not request.session.get("uid"):
        raise HTTPException(401, "Sessão expirada.")
    return request.session["uid"]


tecnico = exigir("tecnico")
central = exigir("central", "admin")


def _run(fn, *args):
    with engine.begin() as conn:
        return fn(conn, *args)


# ------------------------------------------------------------------ técnico
class NovoPedido(BaseModel):
    numero_atividade: str = Field(min_length=1, max_length=30)


@router.get("/tecnico/painel")
def painel(periodo: Literal["hoje", "7d", "mes"] = "hoje", u: dict = Depends(tecnico)):
    return _run(servico.painel_tecnico, u, periodo)


@router.post("/tecnico/pedidos", dependencies=[Depends(csrf)])
def criar_pedido(corpo: NovoPedido, u: dict = Depends(tecnico)):
    return {"id": _run(servico.criar_pedido, u, corpo.numero_atividade)}


@router.get("/tecnico/pedidos/{pedido_id}")
def ver_pedido(pedido_id: int, u: dict = Depends(tecnico)):
    return _run(servico.pedido_do_tecnico, u, pedido_id)


@router.post("/tecnico/pedidos/{pedido_id}/cancelar", dependencies=[Depends(csrf)])
def cancelar(pedido_id: int, u: dict = Depends(tecnico)):
    _run(servico.cancelar_pedido, u, pedido_id)
    return {"ok": True}


class Inicio(BaseModel):
    tipo_conexao: str | None = Field(None, max_length=30)


@router.post("/tecnico/testes/{teste_id}/iniciar", dependencies=[Depends(csrf)])
def iniciar(teste_id: int, corpo: Inicio, request: Request, u: dict = Depends(tecnico)):
    return _run(servico.iniciar_teste, u, teste_id, ip_cliente(request),
                request.headers.get("user-agent"), corpo.tipo_conexao)


class Progresso(BaseModel):
    fase: Literal["latencia", "download", "upload"]
    latencia_ms: float | None = Field(None, ge=0, le=60000)
    jitter_ms: float | None = Field(None, ge=0, le=60000)
    perda_pct: float | None = Field(None, ge=0, le=100)
    download_mbps: float | None = Field(None, ge=0, le=100000)
    upload_mbps: float | None = Field(None, ge=0, le=100000)


@router.post("/tecnico/testes/{teste_id}/progresso", dependencies=[Depends(csrf)])
def progresso(teste_id: int, corpo: Progresso, u: dict = Depends(tecnico)):
    valores = {k: v for k, v in corpo.model_dump().items() if v is not None}
    _run(servico.progresso_teste, u, teste_id, valores)
    return {"ok": True}


class Resultado(BaseModel):
    latencia_ms: float | None = Field(None, ge=0, le=60000)
    jitter_ms: float | None = Field(None, ge=0, le=60000)
    perda_pct: float | None = Field(None, ge=0, le=100)
    download_mbps: float | None = Field(None, ge=0, le=100000)
    upload_mbps: float | None = Field(None, ge=0, le=100000)
    bytes_down: int | None = Field(None, ge=0)
    bytes_up: int | None = Field(None, ge=0)


@router.post("/tecnico/testes/{teste_id}/resultado", dependencies=[Depends(csrf)])
def resultado(teste_id: int, corpo: Resultado, u: dict = Depends(tecnico)):
    d = corpo.model_dump()
    bytes_down, bytes_up = d.pop("bytes_down"), d.pop("bytes_up")
    metricas = {k: v for k, v in d.items() if v is not None}
    _run(servico.resultado_teste, u, teste_id, metricas, bytes_down, bytes_up)
    return {"ok": True}


class Falha(BaseModel):
    motivo: str = Field("Falha no teste.", max_length=200)


@router.post("/tecnico/testes/{teste_id}/falha", dependencies=[Depends(csrf)])
def falha(teste_id: int, corpo: Falha, u: dict = Depends(tecnico)):
    _run(servico.falha_teste, u, teste_id, corpo.motivo)
    return {"ok": True}


# ------------------------------------------------------------------ central
@router.get("/central/fila")
def fila(u: dict = Depends(central)):
    return _run(servico.fila_central)


@router.get("/central/pedidos/{pedido_id}")
def detalhe(pedido_id: int, u: dict = Depends(central)):
    return _run(servico.detalhe_pedido, pedido_id)


class PedidoTeste(BaseModel):
    modo: Literal["completo", "rapido"] = "completo"


@router.post("/central/pedidos/{pedido_id}/testar", dependencies=[Depends(csrf)])
def testar(pedido_id: int, corpo: PedidoTeste, u: dict = Depends(central)):
    return {"teste_id": _run(servico.solicitar_teste, u, pedido_id, corpo.modo)}


class Decisao(BaseModel):
    decisao: Literal["aprovar", "recusar"]
    motivo: str | None = Field(None, max_length=500)


@router.post("/central/pedidos/{pedido_id}/decisao", dependencies=[Depends(csrf)])
def decidir(pedido_id: int, corpo: Decisao, u: dict = Depends(central)):
    return {"status": _run(servico.decidir, u, pedido_id, corpo.decisao, corpo.motivo)}


# ------------------------------------------------------------------ teste de rede
_BLOCO = os.urandom(256 * 1024)  # incompressível; gerado uma vez só
_LOTE_GRAVACAO = 2 * 1024 * 1024
_UP_MAX_BYTES = 8 * 1024 * 1024


def _autorizado(usuario_id: int, teste_id: int) -> bool:
    with engine.connect() as conn:
        return servico.teste_autorizado_para_trafego(conn, usuario_id, teste_id)


def _somar(teste_id: int, coluna: str, quantidade: int) -> None:
    if quantidade > 0:
        with engine.begin() as conn:
            servico.somar_bytes(conn, teste_id, coluna, quantidade)


_SEM_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate"}


@router.get("/rede/ping")
def ping(uid: int = Depends(sessao_tecnico_leve)):
    return Response(status_code=204, headers=_SEM_CACHE)


@router.get("/rede/down")
def baixar(teste: int, uid: int = Depends(sessao_tecnico_leve), bytes: int = config.DOWN_MAX_BYTES):
    if not _autorizado(uid, teste):
        raise HTTPException(403, "Nenhum teste autorizado.")
    total = max(1, min(bytes, config.DOWN_MAX_BYTES))

    def gerar():
        enviado = pendente = 0
        visao = memoryview(_BLOCO)
        try:
            while enviado < total:
                n = min(len(_BLOCO), total - enviado)
                yield visao[:n]
                enviado += n
                pendente += n
                if pendente >= _LOTE_GRAVACAO:
                    _somar(teste, "bytes_down_servidos", pendente)
                    pendente = 0
        finally:
            _somar(teste, "bytes_down_servidos", pendente)

    return StreamingResponse(gerar(), media_type="application/octet-stream",
                             headers={**_SEM_CACHE, "Content-Length": str(total)})


@router.post("/rede/up", dependencies=[Depends(csrf)])
async def subir(request: Request, teste: int, uid: int = Depends(sessao_tecnico_leve)):
    if not await run_in_threadpool(_autorizado, uid, teste):
        raise HTTPException(403, "Nenhum teste autorizado.")
    total = pendente = 0
    try:
        async for pedaco in request.stream():
            total += len(pedaco)
            pendente += len(pedaco)
            if total > _UP_MAX_BYTES:
                raise HTTPException(413, "Bloco grande demais.")
            if pendente >= _LOTE_GRAVACAO:
                await run_in_threadpool(_somar, teste, "bytes_up_recebidos", pendente)
                pendente = 0
    except ClientDisconnect:
        pass
    finally:
        if pendente:
            await run_in_threadpool(_somar, teste, "bytes_up_recebidos", pendente)
    return Response(status_code=204, headers=_SEM_CACHE)
