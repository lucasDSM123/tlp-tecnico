// Roda o motor de teste de rede (teste_rede.js) contra um servidor real e confere o resultado.
const assert = require("assert");
const TLPRede = require("../app/static/js/teste_rede.js");
const BASE = process.env.BASE || "http://127.0.0.1:8765";

async function logar(login, senha) {
  const r = await fetch(BASE + "/login", { method: "POST", redirect: "manual",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ login, senha }) });
  assert.strictEqual(r.status, 303, "login falhou: " + r.status);
  return r.headers.getSetCookie().map((c) => c.split(";")[0]).join("; ");
}
const chamar = (cookie) => async (caminho, metodo = "GET", corpo) => {
  const r = await fetch(BASE + caminho, { method: metodo, headers: { Cookie: cookie, "X-TLP": "1", "Content-Type": "application/json" },
    body: corpo ? JSON.stringify(corpo) : undefined });
  const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (e) {}
  return { status: r.status, json: j };
};

(async () => {
  const tec = chamar(await logar("tec1", "senha-forte-1"));
  const cl = chamar(await logar("cl1", "senha-forte-3"));

  const ped = await tec("/api/tecnico/pedidos", "POST", { numero_atividade: "A1" });
  assert.strictEqual(ped.status, 200, JSON.stringify(ped.json));
  const pid = ped.json.id;

  for (const modo of ["completo", "rapido"]) {
    const t0 = Date.now();
    assert.strictEqual((await cl(`/api/central/pedidos/${pid}/testar`, "POST", { modo })).status, 200);
    const teste = (await tec(`/api/tecnico/pedidos/${pid}`)).json.teste;
    assert.strictEqual(teste.status, "solicitado");
    const cfg = (await tec(`/api/tecnico/testes/${teste.id}/iniciar`, "POST", { tipo_conexao: "wifi" })).json;

    const fases = new Set(); let maxDown = 0;
    const r = await TLPRede.executar({
      cfg, testeId: teste.id, base: BASE, semXHR: true,
      cabecalhos: { Cookie: (await logarCookie(tec)) },
      onProgresso: (e) => { fases.add(e.fase); if (e.parcial.download_mbps) maxDown = Math.max(maxDown, e.parcial.download_mbps); },
    });
    const seg = (Date.now() - t0) / 1000;
    console.log(`[${modo}] ${seg.toFixed(1)}s`, JSON.stringify(r));

    assert.ok(r.latencia_ms > 0 && r.latencia_ms < 200, "latência fora do esperado");
    assert.strictEqual(r.perda_pct, 0);
    assert.ok(r.download_mbps > 5, "download baixo demais: " + r.download_mbps);
    assert.ok(r.bytes_down > 1_000_000);
    if (modo === "completo") { assert.ok(r.upload_mbps > 1 && r.bytes_up > 500_000, "upload ruim"); assert.ok(fases.has("upload")); }
    else { assert.strictEqual(r.upload_mbps, null); assert.ok(!fases.has("upload")); }
    assert.ok(maxDown > 0, "sem progresso ao vivo no download");
    assert.ok(seg < (modo === "completo" ? 22 : 12), "demorou demais: " + seg);

    const corpo = {}; for (const [k, v] of Object.entries(r)) if (v !== null) corpo[k] = v;
    const fim = await tec(`/api/tecnico/testes/${teste.id}/resultado`, "POST", corpo);
    assert.strictEqual(fim.status, 200, JSON.stringify(fim.json));
    const d = (await cl(`/api/central/pedidos/${pid}`)).json.testes[0];
    assert.strictEqual(d.status, "concluido");
    assert.deepStrictEqual(d.alertas, [], "conferência de bytes acusou inconsistência: " + d.alertas);
    console.log(`   central vê: ${d.resultado}`, JSON.stringify(d.niveis));
  }
  console.log("OK");
})().catch((e) => { console.error("FALHOU:", e); process.exit(1); });

let _cookie = null;
async function logarCookie() {
  if (_cookie) return _cookie;
  const r = await fetch(BASE + "/login", { method: "POST", redirect: "manual",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ login: "tec1", senha: "senha-forte-1" }) });
  _cookie = r.headers.getSetCookie().map((c) => c.split(";")[0]).join("; ");
  return _cookie;
}
