"""Regras de negócio: painel do técnico, pedidos de conclusão e testes de rede."""
import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, insert, select, update

from app import config, rede
from app.db import (agora_utc, iso, os_base, pedidos_conclusao as P, testes_rede as T,
                    usuarios)

ABERTOS = ("aguardando", "testando", "em_analise")
TESTE_ATIVO = ("solicitado", "em_andamento")

GRUPOS = {
    "em_execucao": ("Iniciada",),
    "concluida": ("Concluída",),
    "nao_concluida": ("Não Concluída",),
    "suspensa": ("Suspensa",),
    "nao_iniciada": ("Não Iniciada", "em rota"),
    "cancelada": ("Cancelada",),
}
_STATUS_PARA_GRUPO = {s: g for g, ss in GRUPOS.items() for s in ss}


class ErroNegocio(Exception):
    def __init__(self, mensagem: str, codigo: int = 400):
        super().__init__(mensagem)
        self.mensagem, self.codigo = mensagem, codigo


def hoje_brt() -> date:
    return datetime.now(config.FUSO).date()


def _inicio_do_dia_utc() -> datetime:
    """00:00 de hoje em Brasília, convertido para UTC ingênuo (como gravamos no banco)."""
    ini = datetime.combine(hoje_brt(), datetime.min.time(), tzinfo=config.FUSO)
    return ini.astimezone(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- expiração
def expirar(conn) -> None:
    """Fecha o que ficou pendurado (celular não respondeu, pedido esquecido)."""
    agora = agora_utc()

    sem_resposta = conn.execute(select(T.c.id, T.c.pedido_id).where(
        T.c.status == "solicitado",
        T.c.solicitado_em < agora - timedelta(seconds=config.TESTE_TIMEOUT_INICIO_S))).all()
    travados = conn.execute(select(T.c.id, T.c.pedido_id).where(
        T.c.status == "em_andamento",
        T.c.iniciado_em < agora - timedelta(seconds=config.TESTE_TIMEOUT_EXEC_S))).all()

    for linhas, novo in ((sem_resposta, "sem_resposta"), (travados, "falhou")):
        for teste_id, pedido_id in linhas:
            conn.execute(update(T).where(T.c.id == teste_id).values(
                status=novo, finalizado_em=agora, resultado="reprovado",
                detalhes=json.dumps({"niveis": {}, "alertas": [
                    "O celular do técnico não respondeu ao teste." if novo == "sem_resposta"
                    else "O teste não terminou a tempo."]})))
            conn.execute(update(P).where(P.c.id == pedido_id, P.c.status == "testando")
                         .values(status="em_analise"))

    conn.execute(update(P).where(
        P.c.status.in_(ABERTOS),
        P.c.criado_em < agora - timedelta(minutes=config.PEDIDO_VALIDADE_MIN)
    ).values(status="expirado", decidido_em=agora, motivo="Sem decisão dentro do prazo."))


# --------------------------------------------------------------------------- técnico
def _periodo(periodo: str) -> tuple[str, str]:
    hoje = hoje_brt()
    if periodo == "7d":
        ini = hoje - timedelta(days=6)
    elif periodo == "mes":
        ini = hoje.replace(day=1)
    else:
        ini = hoje
    return ini.isoformat(), hoje.isoformat()


def painel_tecnico(conn, usuario: dict, periodo: str) -> dict:
    expirar(conn)
    ini, fim = _periodo(periodo)
    hoje = hoje_brt().isoformat()
    matricula = usuario.get("matricula")
    kpis = {g: 0 for g in GRUPOS}

    linhas = []
    if matricula:
        linhas = conn.execute(
            select(os_base).where(os_base.c.login_tecnico == matricula,
                                  os_base.c.data >= ini, os_base.c.data <= fim)
            .order_by(os_base.c.data.desc(), os_base.c.janela, os_base.c.inicio)
        ).mappings().all()

    ids = [l["numero_atividade"] for l in linhas]
    pedido_por_os: dict[str, dict] = {}
    if ids:
        for p in conn.execute(select(P).where(P.c.tecnico_id == usuario["id"],
                                              P.c.numero_atividade.in_(ids))
                              .order_by(P.c.id)).mappings():
            pedido_por_os[p["numero_atividade"]] = dict(p)  # o último sobrescreve

    atividades = []
    for l in linhas:
        grupo = _STATUS_PARA_GRUPO.get(l["status"])
        if grupo:
            kpis[grupo] += 1
        p = pedido_por_os.get(l["numero_atividade"])
        aberto = bool(p and p["status"] in ABERTOS)
        aprovado = bool(p and p["status"] == "aprovado")
        atividades.append({
            "numero_atividade": l["numero_atividade"], "ordem_servico": l["ordem_servico"],
            "data": l["data"], "janela": l["janela"], "inicio": l["inicio"],
            "status": l["status"], "tipo_atividade": l["tipo_atividade"],
            "cidade": l["cidade"], "bairro": l["bairro"],
            "pedido": ({"id": p["id"], "status": p["status"], "motivo": p["motivo"]} if p else None),
            "pode_concluir": (l["data"] == hoje and l["status"] in config.STATUS_ELEGIVEIS
                              and not aberto and not aprovado),
        })

    kpis["total"] = sum(v for g, v in kpis.items() if g != "cancelada")
    return {"periodo": periodo, "de": ini, "ate": fim, "kpis": kpis, "atividades": atividades}


def criar_pedido(conn, usuario: dict, numero_atividade: str) -> int:
    expirar(conn)
    os_ = conn.execute(select(os_base).where(os_base.c.numero_atividade == numero_atividade)
                       ).mappings().first()
    if not os_ or os_["login_tecnico"] != usuario.get("matricula"):
        raise ErroNegocio("Atividade não encontrada para este técnico.", 404)
    if os_["data"] != hoje_brt().isoformat():
        raise ErroNegocio("Só é possível concluir atividades de hoje.", 409)
    if os_["status"] not in config.STATUS_ELEGIVEIS:
        raise ErroNegocio(f"Atividade com status '{os_['status']}' não pode ser concluída por aqui.", 409)

    existente = conn.execute(select(P.c.status).where(
        P.c.numero_atividade == numero_atividade,
        P.c.status.in_(ABERTOS + ("aprovado",)))).first()
    if existente:
        msg = ("Esta atividade já foi aprovada pela central." if existente[0] == "aprovado"
               else "Já existe um pedido em andamento para esta atividade.")
        raise ErroNegocio(msg, 409)

    r = conn.execute(insert(P).values(
        numero_atividade=numero_atividade, ordem_servico=os_["ordem_servico"],
        tecnico_id=usuario["id"], tecnico_nome=usuario["nome"], cidade=os_["cidade"],
        bairro=os_["bairro"], janela=os_["janela"], tipo_atividade=os_["tipo_atividade"],
        status="aguardando", criado_em=agora_utc()))
    return r.inserted_primary_key[0]


def _ultimo_teste(conn, pedido_id: int):
    return conn.execute(select(T).where(T.c.pedido_id == pedido_id)
                        .order_by(T.c.id.desc()).limit(1)).mappings().first()


def _teste_para_tecnico(t) -> dict | None:
    """O técnico só vê o andamento — os números e o veredito ficam com a central."""
    if not t:
        return None
    return {"id": t["id"], "status": t["status"], "modo": t["modo"],
            "config": config.TESTE_MODOS[t["modo"]] if t["status"] == "solicitado" else None}


def pedido_do_tecnico(conn, usuario: dict, pedido_id: int) -> dict:
    expirar(conn)
    p = conn.execute(select(P).where(P.c.id == pedido_id, P.c.tecnico_id == usuario["id"])
                     ).mappings().first()
    if not p:
        raise ErroNegocio("Pedido não encontrado.", 404)
    return {"id": p["id"], "status": p["status"], "numero_atividade": p["numero_atividade"],
            "ordem_servico": p["ordem_servico"], "motivo": p["motivo"],
            "criado_em": iso(p["criado_em"]), "teste": _teste_para_tecnico(_ultimo_teste(conn, pedido_id))}


def cancelar_pedido(conn, usuario: dict, pedido_id: int) -> None:
    p = conn.execute(select(P).where(P.c.id == pedido_id, P.c.tecnico_id == usuario["id"])
                     ).mappings().first()
    if not p:
        raise ErroNegocio("Pedido não encontrado.", 404)
    if p["status"] not in ABERTOS:
        raise ErroNegocio("Este pedido já foi encerrado.", 409)
    agora = agora_utc()
    conn.execute(update(T).where(T.c.pedido_id == pedido_id, T.c.status.in_(TESTE_ATIVO))
                 .values(status="falhou", finalizado_em=agora))
    conn.execute(update(P).where(P.c.id == pedido_id).values(
        status="cancelado", decidido_em=agora, motivo="Cancelado pelo técnico."))


# --------------------------------------------------------------------------- teste (lado do celular)
def _teste_do_tecnico(conn, usuario: dict, teste_id: int):
    t = conn.execute(select(T).join(P, P.c.id == T.c.pedido_id)
                     .where(T.c.id == teste_id, P.c.tecnico_id == usuario["id"])
                     ).mappings().first()
    if not t:
        raise ErroNegocio("Teste não encontrado.", 404)
    return t


def iniciar_teste(conn, usuario: dict, teste_id: int, ip, user_agent, tipo_conexao) -> dict:
    expirar(conn)
    t = _teste_do_tecnico(conn, usuario, teste_id)
    if t["status"] != "solicitado":
        raise ErroNegocio("Este teste não está mais disponível.", 409)
    conn.execute(update(T).where(T.c.id == teste_id).values(
        status="em_andamento", iniciado_em=agora_utc(), fase="latencia", ip_publico=ip,
        user_agent=(user_agent or "")[:300], tipo_conexao=(tipo_conexao or "")[:30] or None))
    conn.execute(update(P).where(P.c.id == t["pedido_id"]).values(status="testando"))
    cfg = dict(config.TESTE_MODOS[t["modo"]])
    if config.DOWN_URL_EXTERNA:
        cfg["down_url"] = config.DOWN_URL_EXTERNA
        cfg["down_bytes"] = config.DOWN_BYTES_EXTERNO
    return cfg


def progresso_teste(conn, usuario: dict, teste_id: int, valores: dict) -> None:
    t = _teste_do_tecnico(conn, usuario, teste_id)
    if t["status"] != "em_andamento":
        raise ErroNegocio("Teste não está em andamento.", 409)
    conn.execute(update(T).where(T.c.id == teste_id).values(**valores))


def resultado_teste(conn, usuario: dict, teste_id: int, metricas: dict,
                    bytes_down: int | None, bytes_up: int | None) -> str:
    t = _teste_do_tecnico(conn, usuario, teste_id)
    if t["status"] != "em_andamento":
        raise ErroNegocio("Teste não está em andamento.", 409)

    # Download vindo de endpoint externo: o servidor não tem como conferir os bytes (servidos = 0).
    if config.DOWN_URL_EXTERNA and not t["bytes_down_servidos"]:
        bytes_down_conferir = None
    else:
        bytes_down_conferir = bytes_down
    alertas = rede.checar_consistencia(bytes_down_conferir, bytes_up,
                                       t["bytes_down_servidos"], t["bytes_up_recebidos"])
    if t["tipo_conexao"] == "cellular":
        alertas.append("O aparelho informou rede móvel (não está no Wi-Fi do cliente).")
    resultado, detalhes = rede.avaliar(metricas, alertas)
    conn.execute(update(T).where(T.c.id == teste_id).values(
        status="concluido", finalizado_em=agora_utc(), fase=None, resultado=resultado,
        bytes_down_cliente=bytes_down, bytes_up_cliente=bytes_up,
        detalhes=json.dumps(detalhes, ensure_ascii=False), **metricas))
    conn.execute(update(P).where(P.c.id == t["pedido_id"]).values(status="em_analise"))
    return resultado


def falha_teste(conn, usuario: dict, teste_id: int, motivo: str) -> None:
    t = _teste_do_tecnico(conn, usuario, teste_id)
    if t["status"] not in TESTE_ATIVO:
        return
    conn.execute(update(T).where(T.c.id == teste_id).values(
        status="falhou", finalizado_em=agora_utc(), fase=None, resultado="reprovado",
        detalhes=json.dumps({"niveis": {}, "alertas": [motivo[:200]]}, ensure_ascii=False)))
    conn.execute(update(P).where(P.c.id == t["pedido_id"]).values(status="em_analise"))


def teste_autorizado_para_trafego(conn, usuario_id: int, teste_id: int) -> bool:
    """Down/up só funcionam durante um teste pedido pela central (evita uso do servidor como CDN)."""
    return conn.execute(select(T.c.id).join(P, P.c.id == T.c.pedido_id).where(
        T.c.id == teste_id, T.c.status == "em_andamento", P.c.tecnico_id == usuario_id)).first() is not None


def somar_bytes(conn, teste_id: int, coluna: str, quantidade: int) -> None:
    c = T.c[coluna]
    conn.execute(update(T).where(T.c.id == teste_id).values({coluna: c + quantidade}))


# --------------------------------------------------------------------------- central
def _teste_para_central(t) -> dict | None:
    if not t:
        return None
    detalhes = json.loads(t["detalhes"]) if t["detalhes"] else {"niveis": {}, "alertas": []}
    return {
        "id": t["id"], "modo": t["modo"], "status": t["status"], "fase": t["fase"],
        "solicitado_em": iso(t["solicitado_em"]), "iniciado_em": iso(t["iniciado_em"]),
        "finalizado_em": iso(t["finalizado_em"]), "resultado": t["resultado"],
        "metricas": {k: t[k] for k in ("latencia_ms", "jitter_ms", "perda_pct",
                                       "download_mbps", "upload_mbps")},
        "niveis": detalhes.get("niveis", {}), "alertas": detalhes.get("alertas", []),
        "ip_publico": t["ip_publico"], "tipo_conexao": t["tipo_conexao"],
    }


def fila_central(conn) -> dict:
    expirar(conn)
    abertos = conn.execute(select(P).where(P.c.status.in_(ABERTOS)).order_by(P.c.criado_em)).mappings().all()
    ini_dia = _inicio_do_dia_utc()
    decididos = conn.execute(select(P).where(
        P.c.status.in_(("aprovado", "recusado")), P.c.decidido_em >= ini_dia)
        .order_by(P.c.decidido_em.desc()).limit(30)).mappings().all()

    ids = [p["id"] for p in abertos + decididos]
    ultimo: dict[int, dict] = {}
    if ids:
        for t in conn.execute(select(T).where(T.c.pedido_id.in_(ids)).order_by(T.c.id)).mappings():
            ultimo[t["pedido_id"]] = t

    def linha(p):
        t = ultimo.get(p["id"])
        return {
            "id": p["id"], "status": p["status"], "numero_atividade": p["numero_atividade"],
            "ordem_servico": p["ordem_servico"], "tecnico_nome": p["tecnico_nome"],
            "cidade": p["cidade"], "janela": p["janela"], "criado_em": iso(p["criado_em"]),
            "decidido_em": iso(p["decidido_em"]), "decidido_por_nome": p["decidido_por_nome"],
            "teste": ({"status": t["status"], "resultado": t["resultado"]} if t else None),
        }

    aprovados = conn.execute(select(func.count()).select_from(P).where(
        P.c.status == "aprovado", P.c.decidido_em >= ini_dia)).scalar()
    recusados = conn.execute(select(func.count()).select_from(P).where(
        P.c.status == "recusado", P.c.decidido_em >= ini_dia)).scalar()
    return {"pendentes": [linha(p) for p in abertos], "decididos": [linha(p) for p in decididos],
            "contagem": {"pendentes": len(abertos), "aprovados_hoje": aprovados, "recusados_hoje": recusados}}


def detalhe_pedido(conn, pedido_id: int) -> dict:
    expirar(conn)
    p = conn.execute(select(P).where(P.c.id == pedido_id)).mappings().first()
    if not p:
        raise ErroNegocio("Pedido não encontrado.", 404)
    testes = conn.execute(select(T).where(T.c.pedido_id == pedido_id).order_by(T.c.id.desc())).mappings().all()
    tec = conn.execute(select(usuarios.c.nome, usuarios.c.matricula)
                       .where(usuarios.c.id == p["tecnico_id"])).mappings().first()

    desde = agora_utc() - timedelta(days=30)
    historico = dict(conn.execute(
        select(P.c.status, func.count()).where(
            P.c.tecnico_id == p["tecnico_id"], P.c.criado_em >= desde,
            P.c.status.in_(("aprovado", "recusado"))).group_by(P.c.status)).all())

    return {
        "pedido": {"id": p["id"], "status": p["status"], "numero_atividade": p["numero_atividade"],
                   "ordem_servico": p["ordem_servico"], "tecnico_nome": p["tecnico_nome"],
                   "cidade": p["cidade"], "bairro": p["bairro"], "janela": p["janela"],
                   "tipo_atividade": p["tipo_atividade"], "criado_em": iso(p["criado_em"]),
                   "decidido_em": iso(p["decidido_em"]), "decidido_por_nome": p["decidido_por_nome"],
                   "motivo": p["motivo"]},
        "tecnico": {"nome": tec["nome"] if tec else p["tecnico_nome"],
                    "matricula": tec["matricula"] if tec else None,
                    "aprovados_30d": historico.get("aprovado", 0),
                    "recusados_30d": historico.get("recusado", 0)},
        "testes": [_teste_para_central(t) for t in testes],
        "criterios": config.CRITERIOS,
        "teste_validade_min": config.TESTE_VALIDADE_MIN,
    }


def solicitar_teste(conn, central: dict, pedido_id: int, modo: str) -> int:
    expirar(conn)
    if modo not in config.TESTE_MODOS:
        raise ErroNegocio("Modo de teste inválido.", 422)
    p = conn.execute(select(P).where(P.c.id == pedido_id)).mappings().first()
    if not p:
        raise ErroNegocio("Pedido não encontrado.", 404)
    if p["status"] not in ABERTOS:
        raise ErroNegocio("Este pedido já foi encerrado.", 409)
    if conn.execute(select(T.c.id).where(T.c.pedido_id == pedido_id, T.c.status.in_(TESTE_ATIVO))).first():
        raise ErroNegocio("Já existe um teste em andamento para este pedido.", 409)
    r = conn.execute(insert(T).values(
        pedido_id=pedido_id, modo=modo, solicitado_por=central["id"],
        solicitado_em=agora_utc(), status="solicitado"))
    conn.execute(update(P).where(P.c.id == pedido_id).values(status="testando"))
    return r.inserted_primary_key[0]


def decidir(conn, central: dict, pedido_id: int, decisao: str, motivo: str | None) -> str:
    expirar(conn)
    motivo = (motivo or "").strip() or None
    p = conn.execute(select(P).where(P.c.id == pedido_id)).mappings().first()
    if not p:
        raise ErroNegocio("Pedido não encontrado.", 404)
    if p["status"] not in ABERTOS:
        raise ErroNegocio("Este pedido já foi encerrado.", 409)
    if conn.execute(select(T.c.id).where(T.c.pedido_id == pedido_id, T.c.status.in_(TESTE_ATIVO))).first():
        raise ErroNegocio("Espere o teste de rede terminar.", 409)

    if decisao == "aprovar":
        t = conn.execute(select(T).where(T.c.pedido_id == pedido_id, T.c.status == "concluido")
                         .order_by(T.c.id.desc()).limit(1)).mappings().first()
        if not t:
            raise ErroNegocio("Rode o teste de Wi-Fi antes de aprovar.", 409)
        if t["finalizado_em"] < agora_utc() - timedelta(minutes=config.TESTE_VALIDADE_MIN):
            raise ErroNegocio(f"O último teste tem mais de {config.TESTE_VALIDADE_MIN} min. Teste de novo.", 409)
        if t["resultado"] == "reprovado":
            raise ErroNegocio("A rede foi reprovada no teste. Teste de novo ou recuse.", 409)
        if t["resultado"] == "atencao" and not motivo:
            raise ErroNegocio("Rede em atenção: informe a justificativa para aprovar.", 422)
        novo = "aprovado"
    elif decisao == "recusar":
        if not motivo:
            raise ErroNegocio("Informe o motivo da recusa.", 422)
        novo = "recusado"
    else:
        raise ErroNegocio("Decisão inválida.", 422)

    conn.execute(update(P).where(P.c.id == pedido_id).values(
        status=novo, decidido_por=central["id"], decidido_por_nome=central["nome"],
        decidido_em=agora_utc(), motivo=motivo))
    return novo
