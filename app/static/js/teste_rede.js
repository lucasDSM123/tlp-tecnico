/* Teste de rede (roda no navegador do técnico): latência, jitter, perda, download e upload.
 * Funciona no navegador e no Node (usado nos testes automáticos). */
(function (raiz, fabrica) {
  if (typeof module === "object" && module.exports) module.exports = fabrica();
  else raiz.TLPRede = fabrica();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
  const agora = () => performance.now();
  const arred = (v, c) => (v === null || v === undefined || Number.isNaN(v)) ? null : Math.round(v * 10 ** c) / 10 ** c;

  function mediana(v) {
    const s = v.slice().sort((a, b) => a - b), m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  /** Vazão (Mbps) ignorando a "subida" inicial da conexão: usa só a janela após o aquecimento. */
  function vazaoMbps(amostras, durMs) {
    const comDados = amostras.filter((a) => a.b > 0);
    if (comDados.length < 2) return null;
    const primeira = comDados[0], ultima = amostras[amostras.length - 1];
    const aquece = primeira.t + Math.min(1000, durMs * 0.25);
    const base = amostras.find((a) => a.t >= aquece && a.b > 0) || primeira;
    const dt = (ultima.t - base.t) / 1000;
    if (dt <= 0.2) {
      const dt2 = (ultima.t - primeira.t) / 1000;
      return dt2 > 0 ? (ultima.b - primeira.b) * 8 / dt2 / 1e6 : null;
    }
    return (ultima.b - base.b) * 8 / dt / 1e6;
  }

  function vazaoRecente(amostras) {  // última ~1,5 s, para o valor "ao vivo"
    if (amostras.length < 3) return null;
    const ult = amostras[amostras.length - 1];
    const ref = amostras.find((a) => a.t >= ult.t - 1500) || amostras[0];
    const dt = (ult.t - ref.t) / 1000;
    return dt > 0.3 ? (ult.b - ref.b) * 8 / dt / 1e6 : null;
  }

  async function executar(opcoes) {
    const { cfg, testeId, onProgresso } = opcoes;
    const base = opcoes.base || "";
    const f = opcoes.fetch || ((...a) => fetch(...a));
    const cabecalhos = Object.assign({ "X-TLP": "1" }, opcoes.cabecalhos || {});
    const avisar = (fase, pct, parcial) => onProgresso && onProgresso({ fase, pct, parcial: parcial || {} });
    const resultado = { latencia_ms: null, jitter_ms: null, perda_pct: null,
                        download_mbps: null, upload_mbps: null, bytes_down: 0, bytes_up: 0 };

    /* ---------------- latência / jitter / perda ---------------- */
    async function pingUnico() {
      const ctl = new AbortController();
      const limite = setTimeout(() => ctl.abort(), 3000);
      const t0 = agora();
      try {
        const r = await f(base + "/api/rede/ping?r=" + Math.random(), { cache: "no-store", signal: ctl.signal, headers: cabecalhos });
        if (r.status === 401) throw new Error("Sessão expirada.");
        return r.ok ? agora() - t0 : null;
      } catch (e) {
        if (e.message === "Sessão expirada.") throw e;
        return null;
      } finally { clearTimeout(limite); }
    }

    async function medirLatencia(n) {
      await pingUnico(); await pingUnico();  // aquecimento (abre conexão/TLS): não conta
      const rtts = []; let falhas = 0;
      for (let i = 0; i < n; i++) {
        const r = await pingUnico();
        if (r === null) falhas++; else rtts.push(r);
        avisar("latencia", (i + 1) / n);
        await dormir(40);
      }
      resultado.perda_pct = arred(falhas / n * 100, 1);
      if (rtts.length) {
        resultado.latencia_ms = arred(mediana(rtts), 1);
        let soma = 0;
        for (let i = 1; i < rtts.length; i++) soma += Math.abs(rtts[i] - rtts[i - 1]);
        resultado.jitter_ms = arred(rtts.length > 1 ? soma / (rtts.length - 1) : 0, 1);
      }
      avisar("latencia", 1, { latencia_ms: resultado.latencia_ms, jitter_ms: resultado.jitter_ms, perda_pct: resultado.perda_pct });
    }

    /* ---------------- download ---------------- */
    /* Download. Se o servidor informar cfg.down_url (ex.: speed.cloudflare.com/__down), os bytes saem de
     * um endpoint externo gratuito e não do nosso servidor (que cobra saída de dados). Se o endpoint externo
     * não entregar nada (bloqueio de rede/CORS), cai de volta para o download do próprio servidor. */
    async function baixarVia(durMs, externo) {
      const amostras = []; let bytes = 0;
      const ctls = [], limite = agora() + durMs, fluxos = 3;
      const urlLocal = base + "/api/rede/down?teste=" + testeId;
      const urlExterna = () => {
        const u = String(cfg.down_url);
        return u + (u.indexOf("?") >= 0 ? "&" : "?") + "bytes=" + (cfg.down_bytes || 25000000) +
               "&r=" + Math.random().toString(36).slice(2);
      };

      async function fluxo() {
        while (agora() < limite) {
          const ctl = new AbortController(); ctls.push(ctl);
          try {
            const r = externo
              ? await f(urlExterna(), { cache: "no-store", signal: ctl.signal, mode: "cors", credentials: "omit" })
              : await f(urlLocal, { cache: "no-store", signal: ctl.signal, headers: cabecalhos });
            if (!r.ok) throw new Error("Download recusado (" + r.status + ")");
            const leitor = r.body.getReader();
            for (;;) {
              const { done, value } = await leitor.read();
              if (done) break;
              bytes += value.length;
            }
          } catch (e) { if (e.name !== "AbortError") throw e; }
        }
      }

      const tick = setInterval(() => {
        amostras.push({ t: agora(), b: bytes });
        const t0 = amostras[0].t;
        avisar("download", Math.min(1, (agora() - t0) / durMs), { download_mbps: arred(vazaoRecente(amostras), 1) });
      }, 200);
      amostras.push({ t: agora(), b: 0 });
      let erro = null, falhas = 0, acordar;
      const todasFalharam = new Promise((res) => { acordar = res; });
      const rodando = Array.from({ length: fluxos }, () => fluxo().catch((e) => {
        erro = erro || e;
        if (++falhas === fluxos && bytes === 0) acordar();  // nada chegou: não espera o tempo todo
      }));
      await Promise.race([dormir(durMs), todasFalharam]);
      ctls.forEach((c) => c.abort());
      clearInterval(tick);
      amostras.push({ t: agora(), b: bytes });
      await Promise.allSettled(rodando);
      return { amostras, bytes, rej: erro ? { reason: erro } : undefined };
    }

    async function medirDownload(durMs) {
      let r = await baixarVia(durMs, !!cfg.down_url);
      if (cfg.down_url && r.bytes === 0) r = await baixarVia(durMs, false);  // plano B: servidor próprio
      if (r.rej && r.bytes === 0) throw r.rej.reason;
      resultado.bytes_down = r.bytes;
      resultado.download_mbps = arred(vazaoMbps(r.amostras, durMs), 1);
      avisar("download", 1, { download_mbps: resultado.download_mbps });
    }

    /* ---------------- upload ---------------- */
    function montarBloco(tam) {
      const b = new Uint8Array(tam);
      for (let i = 0; i < tam; i += 65536) crypto.getRandomValues(b.subarray(i, Math.min(i + 65536, tam)));
      return b;
    }

    function enviarBloco(url, bloco, aoProgredir, sinal) {
      return new Promise((resolve, reject) => {
        if (typeof XMLHttpRequest === "undefined" || opcoes.semXHR) {  // Node / sem XHR: sem progresso fino
          f(url, { method: "POST", body: bloco, headers: cabecalhos, signal: sinal })
            .then((r) => { if (!r.ok) reject(new Error("Upload recusado (" + r.status + ")")); else { aoProgredir(bloco.byteLength); resolve(); } })
            .catch((e) => (e.name === "AbortError" ? resolve() : reject(e)));
          return;
        }
        const x = new XMLHttpRequest();
        x.open("POST", url);
        Object.entries(cabecalhos).forEach(([k, v]) => x.setRequestHeader(k, v));
        let ultimo = 0;
        x.upload.onprogress = (e) => { aoProgredir(e.loaded - ultimo); ultimo = e.loaded; };
        x.onload = () => (x.status < 300 ? resolve() : reject(new Error("Upload recusado (" + x.status + ")")));
        x.onerror = () => reject(new Error("Falha de rede no upload."));
        x.onabort = () => resolve();
        sinal.addEventListener("abort", () => x.abort());
        x.send(bloco);
      });
    }

    async function medirUpload(durMs) {
      const amostras = []; let bytes = 0, falhou = null;
      const fino = typeof XMLHttpRequest !== "undefined" && !opcoes.semXHR;  // XHR dá progresso contínuo
      const inicio = agora(); let ultimaConclusao = inicio;
      const ctl = new AbortController(), limite = agora() + durMs, fluxos = 2;
      const bloco = montarBloco(1024 * 1024);
      const url = base + "/api/rede/up?teste=" + testeId;

      async function fluxo() {
        while (agora() < limite && !ctl.signal.aborted) {
          try { await enviarBloco(url, bloco, (n) => { bytes += n; ultimaConclusao = agora(); }, ctl.signal); }
          catch (e) { falhou = e; return; }
        }
      }
      const tick = setInterval(() => {
        amostras.push({ t: agora(), b: bytes });
        avisar("upload", Math.min(1, (agora() - amostras[0].t) / durMs), { upload_mbps: arred(vazaoRecente(amostras), 1) });
      }, 200);
      amostras.push({ t: agora(), b: 0 });
      const rodando = Array.from({ length: fluxos }, fluxo);
      await dormir(durMs);
      ctl.abort();
      clearInterval(tick);
      amostras.push({ t: agora(), b: bytes });
      await Promise.allSettled(rodando);
      if (falhou && bytes === 0) throw falhou;
      resultado.bytes_up = bytes;
      // Sem progresso contínuo (caminho alternativo) os bytes só "aparecem" quando um bloco termina:
      // a média simples até o último bloco concluído é a única medida honesta.
      const mbps = fino ? vazaoMbps(amostras, durMs)
        : (bytes > 0 ? bytes * 8 / ((ultimaConclusao - inicio) / 1000) / 1e6 : null);
      resultado.upload_mbps = arred(mbps, 1);
      avisar("upload", 1, { upload_mbps: resultado.upload_mbps });
    }

    await medirLatencia(cfg.ping_n);
    if (cfg.down_ms > 0) await medirDownload(cfg.down_ms);
    if (cfg.up_ms > 0) await medirUpload(cfg.up_ms);
    return resultado;
  }

  return { executar, _interno: { vazaoMbps, mediana } };
});
