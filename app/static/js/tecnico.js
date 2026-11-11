/* Tela do técnico: painel de atividades + fluxo "Concluir com sucesso". */
(function () {
  "use strict";
  const { api, el, fmtData, toast } = TLP;
  const POLL = parseInt(document.body.dataset.pollMs, 10) || 2000;
  const ABERTOS = ["aguardando", "testando", "em_analise"];
  const FINAIS = ["aprovado", "recusado", "cancelado", "expirado"];

  const KPIS = [
    ["em_execucao", "Em execução"], ["concluida", "Concluídas"], ["nao_concluida", "Não concluídas"],
    ["suspensa", "Suspensas"], ["nao_iniciada", "A iniciar"], ["total", "Total"],
  ];
  const CLASSE_STATUS = { "Iniciada": "info", "Concluída": "ok", "Não Concluída": "reprovado", "Suspensa": "atencao" };

  let periodo = "hoje";
  let fluxo = null;          // estado do pedido que está sendo acompanhado
  let autoAbriu = false;

  const $ = (id) => document.getElementById(id);

  /* ------------------------------------------------------------------ painel */
  async function carregar() {
    try {
      const p = await api("/api/tecnico/painel?periodo=" + periodo);
      desenharKpis(p.kpis);
      desenharLista(p.atividades);
      if (!autoAbriu && !fluxo) {  // recarregou a página no meio de um pedido: retoma
        autoAbriu = true;
        const aberta = p.atividades.find((a) => a.pedido && ABERTOS.includes(a.pedido.status));
        if (aberta) abrirFluxo(aberta.pedido.id);
      }
    } catch (e) { toast(e.message); }
  }

  function desenharKpis(k) {
    $("kpis").replaceChildren(...KPIS.map(([chave, rotulo]) =>
      el("div", { classe: "kpi k-" + chave }, el("div", { classe: "n", texto: k[chave] ?? 0 }),
         el("div", { classe: "r", texto: rotulo }))));
  }

  function chipPedido(p) {
    if (!p) return null;
    if (ABERTOS.includes(p.status)) return el("span", { classe: "chip info", texto: "Aguardando central" });
    if (p.status === "aprovado") return el("span", { classe: "chip ok", texto: "Aprovada pela central" });
    if (p.status === "recusado") return el("span", { classe: "chip reprovado", texto: "Recusada pela central" });
    return null;
  }

  function desenharLista(atividades) {
    if (!atividades.length) {
      $("lista").replaceChildren(el("div", { classe: "card vazio", texto: "Nenhuma atividade neste período." }));
      return;
    }
    $("lista").replaceChildren(...atividades.map((a) => {
      const aberto = a.pedido && ABERTOS.includes(a.pedido.status);
      return el("article", { classe: "card os" },
        el("div", { classe: "linha1" },
          el("div", {}, el("div", { classe: "nome", texto: a.tipo_atividade || "Atividade" }),
             el("div", { classe: "mudo pequeno", texto: [a.cidade, a.bairro].filter(Boolean).join(" · ") })),
          el("span", { classe: "chip " + (CLASSE_STATUS[a.status] || ""), texto: a.status })),
        el("div", { classe: "meta" },
          a.janela ? el("span", { classe: "chip", texto: "Janela " + a.janela }) : null,
          periodo !== "hoje" ? el("span", { classe: "chip", texto: fmtData(a.data) }) : null,
          chipPedido(a.pedido),
          el("span", { classe: "mudo pequeno", texto: "OS " + (a.ordem_servico || a.numero_atividade) })),
        a.pedido && a.pedido.status === "recusado" && a.pedido.motivo
          ? el("div", { classe: "aviso", texto: "Motivo da recusa: " + a.pedido.motivo }) : null,
        a.pode_concluir
          ? el("button", { classe: "btn btn-ok btn-bloco", texto: "Concluir com sucesso",
                           onclick: () => confirmarConclusao(a) }) : null,
        aberto
          ? el("button", { classe: "btn btn-cinza btn-bloco", texto: "Ver andamento",
                           onclick: () => abrirFluxo(a.pedido.id) }) : null);
    }));
  }

  $("barra-periodo").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-p]"); if (!b) return;
    periodo = b.dataset.p;
    document.querySelectorAll("#barra-periodo button").forEach((x) => x.classList.toggle("ativo", x === b));
    carregar();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !fluxo) carregar(); });

  /* ------------------------------------------------------------------ folha (overlay) */
  function mostrarFolha(...filhos) {
    $("folha").replaceChildren(...filhos.filter(Boolean));  // avisos opcionais vêm null
    $("overlay").classList.remove("oculto");
  }
  function fecharFolha() { $("overlay").classList.add("oculto"); $("folha").replaceChildren(); }

  function confirmarConclusao(a) {
    mostrarFolha(
      el("h2", { texto: "Concluir com sucesso?" }),
      el("p", { classe: "sub", texto: "A central vai testar o Wi‑Fi do local antes de aprovar. Confirme que você está no endereço do cliente e conectado à rede dele (não use o 4G)." }),
      el("div", { classe: "card" }, el("b", { texto: a.tipo_atividade || "Atividade" }),
         el("div", { classe: "mudo pequeno", texto: [a.cidade, a.bairro].filter(Boolean).join(" · ") + " — OS " + (a.ordem_servico || a.numero_atividade) })),
      el("div", { classe: "acoes" },
        el("button", { classe: "btn btn-cinza", texto: "Voltar", onclick: fecharFolha }),
        el("button", { classe: "btn btn-ok", texto: "Enviar para a central", onclick: async (ev) => {
          ev.target.disabled = true;
          try {
            const r = await api("/api/tecnico/pedidos", { method: "POST", corpo: { numero_atividade: a.numero_atividade } });
            abrirFluxo(r.id);
          } catch (e) { toast(e.message); fecharFolha(); carregar(); }
        } })));
  }

  /* ------------------------------------------------------------------ acompanhamento do pedido */
  async function travarTela() {
    try { if ("wakeLock" in navigator) fluxo.wake = await navigator.wakeLock.request("screen"); } catch (e) { /* sem suporte */ }
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && fluxo && !fluxo.wake) travarTela();
  });

  function abrirFluxo(pedidoId) {
    if (fluxo) { clearTimeout(fluxo.timer); }
    fluxo = { pedidoId, pedido: null, executados: new Set(), testando: false, fase: null, pct: 0,
              parcial: {}, cfg: null, ultimoEnvio: 0, ultimaFase: null, semRede: false, timer: null, wake: null };
    travarTela();
    desenharFluxo();
    ciclo();
  }

  async function ciclo() {
    if (!fluxo) return;
    if (!fluxo.testando) {  // durante o teste não competimos pela banda com o polling
      try {
        const p = await api("/api/tecnico/pedidos/" + fluxo.pedidoId);
        fluxo.semRede = false; fluxo.pedido = p;
        if (p.teste && p.teste.status === "solicitado" && !fluxo.executados.has(p.teste.id)) {
          fluxo.executados.add(p.teste.id);
          executarTeste(p.teste);
        }
        desenharFluxo();
        if (FINAIS.includes(p.status)) { encerrarFluxo(); return; }
      } catch (e) {
        if (e.rede) { fluxo.semRede = true; desenharFluxo(); }
        else if (e.status === 404) { encerrarFluxo(); fecharFolha(); return; }
      }
    }
    fluxo.timer = setTimeout(ciclo, POLL);
  }

  function encerrarFluxo() {
    if (!fluxo) return;
    clearTimeout(fluxo.timer);
    try { fluxo.wake && fluxo.wake.release(); } catch (e) { /* ok */ }
    fluxo.wake = null; fluxo.finalizado = true;
  }

  function sairDoFluxo() { encerrarFluxo(); fluxo = null; fecharFolha(); carregar(); }

  async function executarTeste(teste) {
    const f = fluxo;
    f.testando = true; f.fase = "latencia"; f.pct = 0; f.parcial = {}; desenharFluxo();
    try {
      // 'type' (wifi/cellular/ethernet) só existe em alguns navegadores Android. O 'effectiveType'
      // ("4g") é uma classe de velocidade, não o tipo de rede, então não é enviado.
      const conexao = (navigator.connection && navigator.connection.type) || null;
      f.cfg = await api("/api/tecnico/testes/" + teste.id + "/iniciar", { method: "POST", corpo: { tipo_conexao: conexao } });
      const r = await TLPRede.executar({
        cfg: f.cfg, testeId: teste.id,
        onProgresso: (ev) => {
          f.fase = ev.fase; f.pct = ev.pct; Object.assign(f.parcial, ev.parcial); desenharFluxo();
          const agora = Date.now();
          if (ev.fase !== f.ultimaFase || ev.pct >= 1 || agora - f.ultimoEnvio > 1200) {
            f.ultimaFase = ev.fase; f.ultimoEnvio = agora;
            const corpo = { fase: ev.fase };
            Object.entries(ev.parcial).forEach(([k, v]) => { if (v !== null && v !== undefined) corpo[k] = v; });
            api("/api/tecnico/testes/" + teste.id + "/progresso", { method: "POST", corpo }).catch(() => {});
          }
        },
      });
      const corpo = {};
      Object.entries(r).forEach(([k, v]) => { if (v !== null && v !== undefined) corpo[k] = v; });
      await api("/api/tecnico/testes/" + teste.id + "/resultado", { method: "POST", corpo });
    } catch (e) {
      try { await api("/api/tecnico/testes/" + teste.id + "/falha", { method: "POST", corpo: { motivo: e.message } }); } catch (_) { /* ok */ }
    } finally {
      f.testando = false; if (fluxo === f) desenharFluxo();
    }
  }

  async function cancelarPedido() {
    try { await api("/api/tecnico/pedidos/" + fluxo.pedidoId + "/cancelar", { method: "POST", corpo: {} }); }
    catch (e) { toast(e.message); }
    sairDoFluxo();
  }

  /* ------------------------------------------------------------------ desenho da folha */
  const ETAPAS = [["latencia", "Latência e estabilidade"], ["download", "Velocidade de download"], ["upload", "Velocidade de upload"]];

  function listaEtapas() {
    const usaUpload = !fluxo.cfg || fluxo.cfg.up_ms > 0;
    const etapas = ETAPAS.filter(([k]) => k !== "upload" || usaUpload);
    const atual = etapas.findIndex(([k]) => k === fluxo.fase);
    return el("ul", { classe: "etapas" }, etapas.map(([k, nome], i) =>
      el("li", { classe: i < atual ? "feito" : i === atual ? "atual" : "" },
         el("span", { classe: "bolinha", texto: i < atual ? "✓" : i === atual ? "●" : "○" }), nome)));
  }

  function desenharFluxo() {
    if (!fluxo) return;
    const p = fluxo.pedido;
    // Só reconstrói a folha quando algo visível muda (evita piscar e perder cliques).
    const sig = [fluxo.testando, fluxo.fase, p && p.status, p && p.teste && p.teste.status,
                 fluxo.semRede, p && p.motivo].join("|");
    if (sig === fluxo.sig && !$("overlay").classList.contains("oculto")) return;
    fluxo.sig = sig;
    const aviso = fluxo.semRede ? el("div", { classe: "aviso", texto: "Sem conexão com o servidor. Tentando de novo…" }) : null;
    const sair = (texto, classe) => el("div", { classe: "acoes" }, el("button", { classe: "btn " + (classe || "btn-cinza"), texto, onclick: sairDoFluxo }));
    const cancelar = el("div", { classe: "acoes" },
      el("button", { classe: "btn btn-cinza", texto: "Cancelar pedido", onclick: cancelarPedido }),
      el("button", { classe: "btn btn-cinza", texto: "Minimizar", onclick: () => { encerrarFluxo(); fluxo = null; fecharFolha(); carregar(); } }));

    if (fluxo.testando) {
      return mostrarFolha(
        el("h2", {}, el("span", { classe: "girando" }), "Testando o Wi‑Fi…"),
        el("p", { classe: "sub", texto: "Não feche esta tela nem troque de rede. Leva cerca de 15 segundos." }),
        listaEtapas(),
        el("div", { classe: "barra" }, el("i", { id: "barra-i" })), aviso);
    }
    if (!p) {
      return mostrarFolha(el("h2", {}, el("span", { classe: "girando" }), "Carregando…"));
    }
    const st = p.status, testeSt = p.teste && p.teste.status;
    if (st === "aprovado") {
      return mostrarFolha(
        el("div", { classe: "resultado-grande ok" }, el("div", { classe: "icone", texto: "✓" }),
           el("h2", { texto: "Atividade aprovada" }), el("p", { classe: "mudo", texto: "A central confirmou a conclusão." })),
        sair("Fechar", "btn-ok"));
    }
    if (st === "recusado") {
      return mostrarFolha(
        el("div", { classe: "resultado-grande erro" }, el("div", { classe: "icone", texto: "✕" }),
           el("h2", { texto: "Atividade recusada" }),
           p.motivo ? el("p", { texto: "Motivo: " + p.motivo }) : null,
           el("p", { classe: "mudo", texto: "Resolva o ponto indicado e envie de novo." })),
        sair("Entendi"));
    }
    if (st === "cancelado" || st === "expirado") {
      return mostrarFolha(
        el("div", { classe: "resultado-grande" }, el("h2", { texto: st === "cancelado" ? "Pedido cancelado" : "Pedido expirado" }),
           el("p", { classe: "mudo", texto: st === "expirado" ? "A central não decidiu a tempo. Envie de novo." : "" })),
        sair("Fechar"));
    }
    if (st === "em_analise") {
      const falhou = testeSt === "falhou" || testeSt === "sem_resposta";
      return mostrarFolha(
        el("h2", {}, el("span", { classe: "girando" }), falhou ? "Não foi possível testar a rede" : "Teste concluído"),
        el("p", { classe: "sub", texto: falhou
          ? "Confira se está no Wi‑Fi do cliente e com esta tela aberta. A central pode pedir um novo teste."
          : "Aguardando a decisão da central. Mantenha esta tela aberta." }), aviso, cancelar);
    }
    // aguardando (ou testando, quando o comando já chegou mas o teste ainda não começou)
    return mostrarFolha(
      el("h2", {}, el("span", { classe: "girando" }), st === "testando" ? "Preparando o teste…" : "Aguardando a central"),
      el("p", { classe: "sub", texto: "Pedido enviado. A central vai testar o Wi‑Fi do local. Mantenha o celular no Wi‑Fi do cliente e esta tela aberta." }),
      aviso, cancelar);
  }

  /* barra de progresso: ajustada via JS (a política de segurança bloqueia style inline no HTML) */
  setInterval(() => {
    const barra = document.getElementById("barra-i");
    if (!barra || !fluxo || !fluxo.testando) return;
    const ordem = { latencia: 0, download: 1, upload: 2 };
    const total = (fluxo.cfg && fluxo.cfg.up_ms === 0) ? 2 : 3;
    const pos = (ordem[fluxo.fase] || 0) + Math.min(1, fluxo.pct || 0);
    barra.style.width = Math.round(pos / total * 100) + "%";
  }, 150);

  carregar();
})();
