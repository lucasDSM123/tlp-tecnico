/* Utilitários comuns às telas do técnico e da central. */
(function () {
  "use strict";

  async function api(caminho, opcoes) {
    const o = Object.assign({ method: "GET" }, opcoes || {});
    const cab = { Accept: "application/json", "X-TLP": "1" };
    if (o.corpo !== undefined) cab["Content-Type"] = "application/json";
    let resp;
    try {
      resp = await fetch(caminho, {
        method: o.method, headers: cab, cache: "no-store", credentials: "same-origin",
        body: o.corpo !== undefined ? JSON.stringify(o.corpo) : undefined,
      });
    } catch (e) {
      const err = new Error("Sem conexão com o servidor."); err.rede = true; throw err;
    }
    if (resp.status === 401) { window.location.href = "/login"; throw new Error("Sessão expirada."); }
    let dados = null;
    try { dados = await resp.json(); } catch (e) { /* corpo vazio */ }
    if (!resp.ok) {
      const msg = (dados && (dados.erro || dados.detail)) || "Erro " + resp.status;
      const err = new Error(typeof msg === "string" ? msg : "Requisição inválida.");
      err.status = resp.status; throw err;
    }
    return dados;
  }

  /* Cria elementos sem innerHTML (os textos vêm do banco: nada de HTML injetado). */
  function el(tag, props, ...filhos) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "classe") e.className = v;
      else if (k === "texto") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (k === "dados") Object.entries(v).forEach(([dk, dv]) => { e.dataset[dk] = dv; });
      else if (k in e) e[k] = v;
      else e.setAttribute(k, v);
    }
    for (const f of filhos.flat()) {
      if (f === null || f === undefined || f === false) continue;
      e.append(f.nodeType ? f : document.createTextNode(String(f)));
    }
    return e;
  }

  const fmtHora = (iso) => iso ? new Date(iso).toLocaleTimeString("pt-BR",
    { hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo" }) : "—";

  function fmtEspera(iso) {
    if (!iso) return "—";
    const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    return min < 1 ? "agora" : min < 60 ? min + " min" : Math.floor(min / 60) + "h" + String(min % 60).padStart(2, "0");
  }

  function fmtData(isoData) {  // AAAA-MM-DD -> DD/MM
    if (!isoData) return "";
    const [a, m, d] = isoData.split("-"); return d + "/" + m;
  }

  function toast(msg) {
    const t = el("div", { classe: "toast", texto: msg, role: "status" });
    document.body.append(t); setTimeout(() => t.remove(), 4000);
  }

  window.TLP = { api, el, fmtHora, fmtEspera, fmtData, toast };
})();
