"""Teste de ponta a ponta com dois navegadores reais (técnico no celular, central no desktop)."""
import os, re, sys
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("BASE", "http://127.0.0.1:8765")
SHOTS = os.environ.get("SHOTS", "/tmp/shots")
os.makedirs(SHOTS, exist_ok=True)
erros = []

def vigiar(page, nome):
    page.on("pageerror", lambda e: erros.append(f"{nome} pageerror: {e}"))
    # "Failed to load resource" é coberto pelo ouvinte de respostas abaixo (que sabe a URL)
    page.on("console", lambda m: erros.append(f"{nome} console.{m.type}: {m.text}")
            if m.type == "error" and "Failed to load resource" not in m.text else None)
    def resp(r):
        esperado = r.request.method == "POST" and r.url.endswith("/login") and r.status == 401  # senha errada de propósito
        if r.status >= 400 and not esperado:
            erros.append(f"{nome} HTTP {r.status} {r.request.method} {r.url}")
    page.on("response", resp)
    page.on("dialog", lambda d: d.accept())

with sync_playwright() as p:
    nav = p.chromium.launch()
    mobile = nav.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    desk = nav.new_context(viewport={"width": 1366, "height": 820})
    t, c = mobile.new_page(), desk.new_page()
    vigiar(t, "tecnico"); vigiar(c, "central")

    # --- login com credencial errada e depois certa
    t.goto(BASE + "/login"); t.screenshot(path=f"{SHOTS}/01_login.png")
    t.fill("#login", "tec1"); t.fill("#senha", "errada"); t.click("button[type=submit]")
    expect(t.locator(".erro-login")).to_contain_text("inválidos")
    t.fill("#login", "tec1"); t.fill("#senha", "senha-forte-1"); t.click("button[type=submit]")
    t.wait_for_url("**/tecnico")

    # --- painel do técnico
    expect(t.locator(".kpi")).to_have_count(6)
    expect(t.locator(".os")).to_have_count(3)
    expect(t.get_by_role("button", name="Concluir com sucesso")).to_have_count(1)
    t.screenshot(path=f"{SHOTS}/02_tecnico_painel.png")

    # --- técnico pede conclusão
    t.get_by_role("button", name="Concluir com sucesso").click()
    expect(t.get_by_text("Concluir com sucesso?")).to_be_visible()
    t.screenshot(path=f"{SHOTS}/03_tecnico_confirma.png")
    t.get_by_role("button", name="Enviar para a central").click()
    expect(t.get_by_role("heading", name="Aguardando a central")).to_be_visible()
    t.screenshot(path=f"{SHOTS}/04_tecnico_aguardando.png")

    # --- central
    c.goto(BASE + "/login"); c.fill("#login", "cl1"); c.fill("#senha", "senha-forte-3"); c.click("button[type=submit]")
    c.wait_for_url("**/central")
    expect(c.locator(".item-fila")).to_have_count(1)
    assert "(1)" in c.title(), c.title()
    c.screenshot(path=f"{SHOTS}/05_central_fila.png")
    c.locator(".item-fila").first.click()
    expect(c.locator("#d-info h2")).to_have_text("Técnico Um")
    expect(c.locator("#btn-aprovar")).to_be_disabled()
    c.screenshot(path=f"{SHOTS}/06_central_detalhe.png")

    c.get_by_role("button", name=re.compile("Testar Wi.Fi \\(completo")).click()
    expect(c.locator("#d-teste .faixa.info")).to_be_visible()

    # --- o celular reage sozinho ao comando
    expect(t.get_by_role("heading", name=re.compile("Testando o Wi.Fi"))).to_be_visible(timeout=15000)
    t.screenshot(path=f"{SHOTS}/07_tecnico_testando.png")
    expect(c.locator(".metrica").first).to_be_visible(timeout=15000)
    c.screenshot(path=f"{SHOTS}/08_central_ao_vivo.png")

    expect(t.get_by_role("heading", name="Teste concluído")).to_be_visible(timeout=40000)
    t.screenshot(path=f"{SHOTS}/09_tecnico_aguarda_decisao.png")
    expect(c.locator(".faixa").first).to_contain_text(re.compile("Rede OK|Atenção|Reprovada"), timeout=10000)
    expect(c.locator("#d-teste .metrica")).to_have_count(5)
    c.screenshot(path=f"{SHOTS}/10_central_resultado.png")
    resultado = c.locator("#d-teste .faixa").first.inner_text()
    print("Resultado visto pela central:", resultado.replace("\n", " | "))
    valores = c.locator("#d-teste .metrica .val").all_inner_texts()
    print("Métricas:", [v.replace("\n", " ") for v in valores])

    # --- decisão
    if "Reprovada" in resultado:
        c.fill("#d-motivo", "Wi-Fi instável"); c.click("#btn-recusar")
        expect(t.get_by_role("heading", name="Atividade recusada")).to_be_visible(timeout=10000)
    else:
        if "Atenção" in resultado:
            c.fill("#d-motivo", "Plano do cliente é menor")
        c.click("#btn-aprovar")
        expect(t.get_by_role("heading", name="Atividade aprovada")).to_be_visible(timeout=10000)
        t.screenshot(path=f"{SHOTS}/11_tecnico_aprovado.png")
        c.screenshot(path=f"{SHOTS}/12_central_aprovado.png")
        expect(c.locator("#btn-aprovar")).to_be_disabled()
        t.get_by_role("button", name="Fechar").click()
        expect(t.locator(".chip", has_text="Aprovada pela central")).to_be_visible()
        expect(t.get_by_role("button", name="Concluir com sucesso")).to_have_count(0)
        t.screenshot(path=f"{SHOTS}/13_tecnico_depois.png")
    nav.close()

print("ERROS DE CONSOLE/JS:", erros if erros else "nenhum")
sys.exit(1 if erros else 0)
