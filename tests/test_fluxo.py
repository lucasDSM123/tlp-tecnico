import json
from datetime import timedelta

from sqlalchemy import select, update

from app import config
from app.db import agora_utc, engine, testes_rede as T, pedidos_conclusao as P, usuarios
from tests.conftest import H, logar

BOM = dict(latencia_ms=25.0, jitter_ms=4.0, perda_pct=0.0, download_mbps=80.0, upload_mbps=30.0)


def pedir(tec, os="A1"):
    r = tec.post("/api/tecnico/pedidos", json={"numero_atividade": os}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def rodar_teste(tec, cl, pedido, metricas=BOM, bytes_down=40_000_000, bytes_up=15_000_000, servidos=True):
    """Central pede o teste; o 'celular' recebe, inicia e devolve o resultado."""
    r = cl.post(f"/api/central/pedidos/{pedido}/testar", json={"modo": "completo"}, headers=H)
    assert r.status_code == 200, r.text
    teste = tec.get(f"/api/tecnico/pedidos/{pedido}").json()["teste"]
    assert teste["status"] == "solicitado" and teste["config"]["ping_n"] == 20
    assert tec.post(f"/api/tecnico/testes/{teste['id']}/iniciar", json={}, headers=H).status_code == 200
    if servidos:
        with engine.begin() as conn:
            conn.execute(update(T).where(T.c.id == teste["id"]).values(
                bytes_down_servidos=bytes_down, bytes_up_recebidos=bytes_up))
    r = tec.post(f"/api/tecnico/testes/{teste['id']}/resultado",
                 json={**metricas, "bytes_down": bytes_down, "bytes_up": bytes_up}, headers=H)
    assert r.status_code == 200, r.text
    return teste["id"]


# ---------------------------------------------------------------- login
def test_login_valido_e_redirecionamento(base):
    c, r = logar("tec1", "senha-forte-1")
    assert r.status_code == 303 and r.headers["location"] == "/tecnico"
    c, r = logar("cl1", "senha-forte-3")
    assert r.headers["location"] == "/central"


def test_login_invalido_mensagem_generica(base):
    _, r1 = logar("tec1", "errada")
    _, r2 = logar("naoexiste", "qualquer")
    assert r1.status_code == r2.status_code == 401
    assert "inválidos" in r1.text and "inválidos" in r2.text


def test_bloqueio_apos_varias_senhas_erradas(base):
    for _ in range(config.MAX_FALHAS_LOGIN):
        logar("tec1", "errada")
    _, r = logar("tec1", "senha-forte-1")  # mesmo certa, está bloqueado
    assert r.status_code == 401
    with engine.begin() as conn:
        conn.execute(update(usuarios).where(usuarios.c.login == "tec1").values(bloqueado_ate=agora_utc() - timedelta(seconds=1)))
    _, r = logar("tec1", "senha-forte-1")
    assert r.status_code == 303


def test_senha_guardada_com_bcrypt(base):
    with engine.connect() as conn:
        h = conn.execute(select(usuarios.c.senha_hash).where(usuarios.c.login == "tec1")).scalar()
    assert h.startswith("$2") and "senha-forte-1" not in h


def test_matricula_nao_loga(base):
    _, r = logar("111", "senha-forte-1")
    assert r.status_code == 401


def test_perfis_e_sessao(base, tec, cl):
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)
    assert anon.get("/api/tecnico/painel").status_code == 401
    assert anon.get("/tecnico", follow_redirects=False).headers["location"] == "/login"
    assert tec.get("/api/central/fila").status_code == 403
    assert cl.get("/api/tecnico/painel").status_code == 403
    assert tec.get("/central", follow_redirects=False).headers["location"] == "/tecnico"
    assert cl.get("/tecnico", follow_redirects=False).headers["location"] == "/central"


def test_csrf_exige_cabecalho(tec):
    r = tec.post("/api/tecnico/pedidos", json={"numero_atividade": "A1"})
    assert r.status_code == 403


def test_cabecalhos_de_seguranca(base):
    from fastapi.testclient import TestClient
    from app.main import app
    r = TestClient(app).get("/login")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


# ---------------------------------------------------------------- painel
def test_painel_so_mostra_as_os_do_tecnico(tec):
    p = tec.get("/api/tecnico/painel?periodo=hoje").json()
    ids = {a["numero_atividade"] for a in p["atividades"]}
    assert ids == {"A1", "A2", "A3"}  # B1 é de outro técnico; OLD é de 2020
    assert p["kpis"]["em_execucao"] == 1 and p["kpis"]["concluida"] == 1 and p["kpis"]["suspensa"] == 1
    por_os = {a["numero_atividade"]: a for a in p["atividades"]}
    assert por_os["A1"]["pode_concluir"] is True
    assert por_os["A2"]["pode_concluir"] is False and por_os["A3"]["pode_concluir"] is False


# ---------------------------------------------------------------- pedido
def test_pedido_regras(tec, tec2):
    assert tec.post("/api/tecnico/pedidos", json={"numero_atividade": "B1"}, headers=H).status_code == 404  # de outro técnico
    assert tec.post("/api/tecnico/pedidos", json={"numero_atividade": "A2"}, headers=H).status_code == 409  # já concluída
    assert tec.post("/api/tecnico/pedidos", json={"numero_atividade": "OLD"}, headers=H).status_code == 409  # não é de hoje
    pid = pedir(tec)
    assert tec.post("/api/tecnico/pedidos", json={"numero_atividade": "A1"}, headers=H).status_code == 409  # duplicado
    assert tec2.get(f"/api/tecnico/pedidos/{pid}").status_code == 404  # tec2 não vê pedido do tec1
    assert tec.post("/api/tecnico/pedidos", json={"numero_atividade": "A1"}, headers=H).status_code == 409


# ---------------------------------------------------------------- fluxo completo
def test_fluxo_aprovacao(tec, cl):
    pid = pedir(tec)
    fila = cl.get("/api/central/fila").json()
    assert fila["contagem"]["pendentes"] == 1 and fila["pendentes"][0]["tecnico_nome"] == "Técnico Um"

    # não aprova sem teste
    r = cl.post(f"/api/central/pedidos/{pid}/decisao", json={"decisao": "aprovar"}, headers=H)
    assert r.status_code == 409 and "teste" in r.json()["erro"].lower()

    rodar_teste(tec, cl, pid)
    d = cl.get(f"/api/central/pedidos/{pid}").json()
    assert d["testes"][0]["resultado"] == "ok" and d["pedido"]["status"] == "em_analise"
    assert all(v == "ok" for v in d["testes"][0]["niveis"].values())

    # técnico não enxerga números nem veredito
    visto = tec.get(f"/api/tecnico/pedidos/{pid}").json()
    assert "resultado" not in json.dumps(visto) and "download" not in json.dumps(visto)

    r = cl.post(f"/api/central/pedidos/{pid}/decisao", json={"decisao": "aprovar"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "aprovado"
    assert tec.get(f"/api/tecnico/pedidos/{pid}").json()["status"] == "aprovado"
    assert cl.get("/api/central/fila").json()["contagem"]["aprovados_hoje"] == 1
    # depois de aprovada, não dá para pedir de novo nem decidir de novo
    assert tec.post("/api/tecnico/pedidos", json={"numero_atividade": "A1"}, headers=H).status_code == 409
    assert cl.post(f"/api/central/pedidos/{pid}/decisao", json={"decisao": "recusar", "motivo": "x"}, headers=H).status_code == 409


def test_rede_reprovada_bloqueia_aprovacao(tec, cl):
    pid = pedir(tec)
    rodar_teste(tec, cl, pid, metricas={**BOM, "download_mbps": 2.0, "latencia_ms": 400.0}, bytes_down=3_000_000)
    d = cl.get(f"/api/central/pedidos/{pid}").json()
    assert d["testes"][0]["resultado"] == "reprovado"
    assert d["testes"][0]["niveis"]["download_mbps"] == "reprovado"
    r = cl.post(f"/api/central/pedidos/{pid}/decisao", json={"decisao": "aprovar", "motivo": "ok mesmo assim"}, headers=H)
    assert r.status_code == 409
    r = cl.post(f"/api/central/pedidos/{pid}/decisao", json={"decisao": "recusar"}, headers=H)
    assert r.status_code == 422  # recusa exige motivo
    r = cl.post(f"/api/central/pedidos/{pid}/decisao", json={"decisao": "recusar", "motivo": "Wi-Fi instável"}, headers=H)
    assert r.status_code == 200
    v = tec.get(f"/api/tecnico/pedidos/{pid}").json()
    assert v["status"] == "recusado" and v["motivo"] == "Wi-Fi instável"


def test_atencao_exige_justificativa(tec, cl):
    pid = pedir(tec)
    rodar_teste(tec, cl, pid, metricas={**BOM, "download_mbps": 20.0})  # entre mínimo e bom
    assert cl.get(f"/api/central/pedidos/{pid}").json()["testes"][0]["resultado"] == "atencao"
    assert cl.post(f"/api/central/pedidos/{pid}/decisao", json={"decisao": "aprovar"}, headers=H).status_code == 422
    r = cl.post(f"/api/central/pedidos/{pid}/decisao", json={"decisao": "aprovar", "motivo": "Cliente com plano de 20 Mega"}, headers=H)
    assert r.status_code == 200


def test_resultado_inventado_e_reprovado(tec, cl):
    """Técnico chama a API na mão com números ótimos, sem ter transferido nada."""
    pid = pedir(tec)
    tid = rodar_teste(tec, cl, pid, servidos=False)
    d = cl.get(f"/api/central/pedidos/{pid}").json()["testes"][0]
    assert d["resultado"] == "reprovado" and len(d["alertas"]) == 2
    assert cl.post(f"/api/central/pedidos/{pid}/decisao", json={"decisao": "aprovar"}, headers=H).status_code == 409


def test_trafego_so_com_teste_autorizado(tec, cl):
    pid = pedir(tec)
    assert tec.get("/api/rede/down?teste=1").status_code == 403           # nenhum teste ainda
    assert tec.post("/api/rede/up?teste=1", content=b"x" * 10, headers=H).status_code == 403
    assert tec.get("/api/rede/ping").status_code == 204                    # ping é leve e livre para técnico logado
    assert cl.get("/api/rede/ping").status_code == 401                     # central não usa
    cl.post(f"/api/central/pedidos/{pid}/testar", json={"modo": "rapido"}, headers=H)
    t = tec.get(f"/api/tecnico/pedidos/{pid}").json()["teste"]
    assert tec.get(f"/api/rede/down?teste={t['id']}").status_code == 403   # ainda não iniciou
    tec.post(f"/api/tecnico/testes/{t['id']}/iniciar", json={"tipo_conexao": "wifi"}, headers=H)
    r = tec.get(f"/api/rede/down?teste={t['id']}&bytes=3000000")
    assert r.status_code == 200 and len(r.content) == 3_000_000
    assert tec.post(f"/api/rede/up?teste={t['id']}", content=b"x" * 500_000, headers=H).status_code == 204
    with engine.connect() as conn:
        row = conn.execute(select(T.c.bytes_down_servidos, T.c.bytes_up_recebidos, T.c.tipo_conexao).where(T.c.id == t["id"])).first()
    assert row == (3_000_000, 500_000, "wifi")
    assert tec.post(f"/api/rede/up?teste={t['id']}", content=b"x" * 9_000_000, headers=H).status_code == 413


def test_teste_duplicado_e_modo_invalido(tec, cl):
    pid = pedir(tec)
    assert cl.post(f"/api/central/pedidos/{pid}/testar", json={"modo": "turbo"}, headers=H).status_code == 422
    assert cl.post(f"/api/central/pedidos/{pid}/testar", json={"modo": "rapido"}, headers=H).status_code == 200
    assert cl.post(f"/api/central/pedidos/{pid}/testar", json={"modo": "rapido"}, headers=H).status_code == 409
    assert cl.post(f"/api/central/pedidos/{pid}/decisao", json={"decisao": "recusar", "motivo": "x"}, headers=H).status_code == 409


def test_celular_nao_respondeu_vira_sem_resposta(tec, cl):
    pid = pedir(tec)
    cl.post(f"/api/central/pedidos/{pid}/testar", json={"modo": "completo"}, headers=H)
    with engine.begin() as conn:
        conn.execute(update(T).values(solicitado_em=agora_utc() - timedelta(seconds=config.TESTE_TIMEOUT_INICIO_S + 5)))
    d = cl.get(f"/api/central/pedidos/{pid}").json()
    assert d["testes"][0]["status"] == "sem_resposta" and d["pedido"]["status"] == "em_analise"
    assert cl.post(f"/api/central/pedidos/{pid}/testar", json={"modo": "completo"}, headers=H).status_code == 200  # pode repetir


def test_teste_antigo_nao_vale(tec, cl):
    pid = pedir(tec)
    rodar_teste(tec, cl, pid)
    with engine.begin() as conn:
        conn.execute(update(T).values(finalizado_em=agora_utc() - timedelta(minutes=config.TESTE_VALIDADE_MIN + 1)))
    assert cl.post(f"/api/central/pedidos/{pid}/decisao", json={"decisao": "aprovar"}, headers=H).status_code == 409


def test_cancelar_e_expirar(tec, cl):
    pid = pedir(tec)
    assert tec.post(f"/api/tecnico/pedidos/{pid}/cancelar", json={}, headers=H).status_code == 200
    assert tec.get(f"/api/tecnico/pedidos/{pid}").json()["status"] == "cancelado"
    pid2 = pedir(tec)  # pode pedir de novo
    with engine.begin() as conn:
        conn.execute(update(P).where(P.c.id == pid2).values(criado_em=agora_utc() - timedelta(minutes=config.PEDIDO_VALIDADE_MIN + 1)))
    assert tec.get(f"/api/tecnico/pedidos/{pid2}").json()["status"] == "expirado"


def test_validacao_das_metricas(tec, cl):
    pid = pedir(tec)
    cl.post(f"/api/central/pedidos/{pid}/testar", json={"modo": "rapido"}, headers=H)
    t = tec.get(f"/api/tecnico/pedidos/{pid}").json()["teste"]
    tec.post(f"/api/tecnico/testes/{t['id']}/iniciar", json={}, headers=H)
    assert tec.post(f"/api/tecnico/testes/{t['id']}/resultado", json={"perda_pct": 250}, headers=H).status_code == 422
    assert tec.post(f"/api/tecnico/testes/{t['id']}/resultado", json={"download_mbps": -5}, headers=H).status_code == 422
    assert tec.post(f"/api/tecnico/testes/{t['id']}/progresso", json={"fase": "hacker"}, headers=H).status_code == 422


def test_rede_movel_reprova(tec, cl):
    pid = pedir(tec)
    cl.post(f"/api/central/pedidos/{pid}/testar", json={"modo": "rapido"}, headers=H)
    t = tec.get(f"/api/tecnico/pedidos/{pid}").json()["teste"]
    tec.post(f"/api/tecnico/testes/{t['id']}/iniciar", json={"tipo_conexao": "cellular"}, headers=H)
    tec.post(f"/api/tecnico/testes/{t['id']}/resultado", json=BOM, headers=H)
    d = cl.get(f"/api/central/pedidos/{pid}").json()["testes"][0]
    assert d["resultado"] == "reprovado" and any("rede móvel" in a for a in d["alertas"])
