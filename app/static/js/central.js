/* Tela da central de contorno: fila de pedidos, teste de Wi-Fi sob demanda e decisão. */
(function () {
  "use strict";
  const { api, el, fmtHora, fmtEspera, toast } = TLP;
  const POLL = parseInt(document.body.dataset.pollMs, 10) || 3000;
  const TITULO = document.body.dataset.titulo || "Central";
  const $ = (id) => document.getElementById(id);

  const ORDEM_METRICAS = ["latencia_ms", "jitter_ms", "perda_pct", "download_mbps", "upload_mbps"];
  const ROT_STATUS = { aguardando: "Aguardando teste", testando: "Testando", em_analise: "Em análise",
                       aprovado: "Aprovado", recusado: "Recusado", cancelado: "Cancelado", expirado: "Expirado" };
  const ROT_RES = { ok: "Rede OK", atencao: "Atenção", reprovado: "Reprovada" };
  const ROT_FASE = { latencia: "medindo latência", download: "medindo download", upload: "medindo upload" };

  let selecionado = null;      // id do pedido aberto no painel
  let detalhe = null;          // último detalhe recebido
  let vistos = null;           // ids de pendentes já conhecidos (para avisar de novos)
  let temTesteAtivo = false;
  let audio = null;
  let timer = null;

  document.addEventListener("click", () => {  // navegadores só liberam áudio após um gesto
    if (!audio) { try { audio = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { /* sem áudio */ } }
  }, { once: true });

  function bip() {
    if (!audio) return;
    try {
      const o = audio.createOscillator(), g = audio.createGain();
      o.frequency.value = 880; g.gain.value = 0.08; o.connect(g); g.connect(audio.destination);
      o.start(); o.stop(audio.currentTime + 0.18);
    } catch (e) { /* ok */ }
  }

  function nivel(regra, v) {
    if (v === null || v === undefined) return "";
    if (regra.tipo === "max") return v <= regra.bom ? "ok" : v <= regra.minimo ? "atencao" : "reprovado";
    return v >= regra.bom ? "ok" : v >= regra.minimo ? "atencao" : "reprovado";
  }

  /* ------------------------------------------------------------------ ciclo de atualização */
  async function ciclo() {
    clearTimeout(timer);
    let proximo = POLL;
    if (!document.hidden) {
      try {
        const fila = await api("/api/central/fila");
        desenharFila(fila);
        if (selecionado) { detalhe = await api("/api/central/pedidos/" + selecionado); atualizarDetalhe(detalhe); }
        proximo = temTesteAtivo ? 1500 : (fila.contagem.pendentes ? POLL : 8000);
      } catch (e) { if (!e.rede) toast(e.message); proximo = 5000; }
    }
    timer = setTimeout(ciclo, proximo);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) ciclo(); });

  /* ------------------------------------------------------------------ fila */
  function chipTeste(t) {
    if (!t) return null;
    if (t.resultado) return el("span", { classe: "chip " + t.resultado, texto: ROT_RES[t.resultado] });
    return el("span", { classe: "chip info", texto: "Teste em curso" });
  }

  function itemFila(p, decidido) {
    return el("button", { classe: "item-fila" + (p.id === selecionado ? " sel" : ""), onclick: () => abrirPedido(p.id) },
      el("div", { classe: "l1" }, el("span", { texto: p.tecnico_nome }),
         el("span", { classe: "pequeno mudo", texto: decidido ? fmtHora(p.decidido_em) : fmtEspera(p.criado_em) })),
      el("div", { classe: "l2" },
         el("span", { texto: [p.cidade, p.janela].filter(Boolean).join(" · ") }),
         decidido
           ? el("span", { classe: "chip " + (p.status === "aprovado" ? "ok" : "reprovado"), texto: ROT_STATUS[p.status] })
           : [el("span", { classe: "chip", texto: ROT_STATUS[p.status] }), chipTeste(p.teste)]));
  }

  function desenharFila(f) {
    const novos = f.pendentes.map((p) => p.id);
    if (vistos === null) vistos = new Set(novos);
    else if (novos.some((id) => !vistos.has(id))) { bip(); toast("Novo pedido de conclusão na fila."); }
    vistos = new Set(novos);

    document.title = (f.contagem.pendentes ? "(" + f.contagem.pendentes + ") " : "") + TITULO;
    $("resumo").replaceChildren(
      kpi(f.contagem.pendentes, "Pendentes", "k-em_execucao"),
      kpi(f.contagem.aprovados_hoje, "Aprovados hoje", "k-concluida"),
      kpi(f.contagem.recusados_hoje, "Recusados hoje", "k-nao_concluida"));

    $("fila").replaceChildren(
      el("h3", { texto: "Pendentes (" + f.pendentes.length + ")" }),
      ...(f.pendentes.length ? f.pendentes.map((p) => itemFila(p, false)) : [el("div", { classe: "card vazio", texto: "Nenhum pedido aguardando." })]),
      el("h3", { texto: "Decididos hoje" }),
      ...(f.decididos.length ? f.decididos.map((p) => itemFila(p, true)) : [el("div", { classe: "mudo pequeno", texto: "Ainda não há decisões hoje." })]));
  }

  const kpi = (n, r, c) => el("div", { classe: "kpi " + c }, el("div", { classe: "n", texto: n }), el("div", { classe: "r", texto: r }));

  /* ------------------------------------------------------------------ detalhe */
  function abrirPedido(id) {
    selecionado = id; detalhe = null;
    $("detalhe").replaceChildren(
      el("div", { classe: "card", id: "d-info" }),
      el("div", { classe: "card", id: "d-teste" }),
      el("div", { classe: "card" }, el("h3", { texto: "Histórico de testes" }), el("div", { classe: "hist-wrap", id: "d-hist" })),
      el("div", { classe: "card decisao", id: "d-decisao" },
        el("h3", { texto: "Decisão" }),
        el("p", { classe: "pequeno mudo", id: "d-dica" }),
        el("textarea", { id: "d-motivo", placeholder: "Motivo / justificativa (obrigatório para recusar ou aprovar com atenção)", maxLength: 500 }),
        el("div", { classe: "acoes" },
          el("button", { classe: "btn btn-erro", id: "btn-recusar", texto: "Recusar", onclick: () => decidir("recusar") }),
          el("button", { classe: "btn btn-ok", id: "btn-aprovar", texto: "Aprovar conclusão", onclick: () => decidir("aprovar") }))));
    api("/api/central/pedidos/" + id).then((d) => { detalhe = d; atualizarDetalhe(d); }).catch((e) => toast(e.message));
    ciclo();
  }

  function tile(chave, regra, valor, nv) {
    const casas = chave === "perda_pct" || chave === "latencia_ms" || chave === "jitter_ms" ? 1 : 1;
    const ref = (regra.tipo === "max" ? "bom ≤ " + regra.bom + " · mín ≤ " + regra.minimo
                                      : "bom ≥ " + regra.bom + " · mín ≥ " + regra.minimo) + " " + regra.unidade;
    return el("div", { classe: "metrica " + (nv || "") },
      el("div", { classe: "rot", texto: regra.rotulo }),
      el("div", { classe: "val" }, valor === null || valor === undefined ? "—" : Number(valor).toFixed(casas), " ",
         el("small", { texto: regra.unidade })),
      el("div", { classe: "ref", texto: ref }));
  }

  function blocoMetricas(t, criterios) {
    const concluido = t.status === "concluido";
    return el("div", { classe: "metricas" }, ORDEM_METRICAS.map((k) => {
      const v = t.metricas[k];
      const nv = concluido ? (t.niveis[k] || "") : nivel(criterios[k], v);
      return tile(k, criterios[k], v, nv);
    }));
  }

  function atualizarDetalhe(d) {
    if (!d || d.pedido.id !== selecionado || !$("d-info")) return;
    const p = d.pedido, aberto = ["aguardando", "testando", "em_analise"].includes(p.status);
    const t0 = d.testes[0] || null;
    const ativo = !!t0 && ["solicitado", "em_andamento"].includes(t0.status);
    temTesteAtivo = ativo;

    $("d-info").replaceChildren(
      el("div", { classe: "cab-detalhe" },
        el("div", {}, el("h2", { texto: p.tecnico_nome }),
           el("div", { classe: "mudo pequeno", texto: "Matrícula " + (d.tecnico.matricula || "—") + " · 30 dias: " +
             d.tecnico.aprovados_30d + " aprovadas / " + d.tecnico.recusados_30d + " recusadas" })),
        el("span", { classe: "chip " + (p.status === "aprovado" ? "ok" : p.status === "recusado" ? "reprovado" : "info"), texto: ROT_STATUS[p.status] })),
      el("div", { classe: "dl" },
        info("Atividade", p.tipo_atividade), info("OS", p.ordem_servico || p.numero_atividade),
        info("Local", [p.cidade, p.bairro].filter(Boolean).join(" · ")), info("Janela", p.janela),
        info("Pedido enviado", fmtHora(p.criado_em) + " (" + fmtEspera(p.criado_em) + ")")));

    // --- teste
    const modoBtn = (modo, texto, classe) => el("button", { classe: "btn " + classe, texto, disabled: !aberto || ativo,
      onclick: () => testar(modo) });
    const partes = [
      el("div", { classe: "acoes" }, modoBtn("completo", "Testar Wi‑Fi (completo ~12 s)", ""),
         modoBtn("rapido", "Teste rápido (~6 s)", "btn-cinza"))];
    if (t0) {
      if (ativo) {
        partes.push(el("div", { classe: "faixa info" },
          el("span", { texto: t0.status === "solicitado" ? "Aguardando o celular do técnico iniciar o teste…" : "Testando: " + (ROT_FASE[t0.fase] || "em andamento") + "…" })));
        if (t0.status === "em_andamento") partes.push(blocoMetricas(t0, d.criterios));
      } else if (t0.status === "concluido") {
        partes.push(el("div", { classe: "faixa " + t0.resultado },
          el("span", { texto: ROT_RES[t0.resultado] }), el("span", { classe: "pequeno", texto: "teste das " + fmtHora(t0.finalizado_em) })));
        partes.push(blocoMetricas(t0, d.criterios));
      } else {
        partes.push(el("div", { classe: "faixa reprovado" },
          el("span", { texto: t0.status === "sem_resposta" ? "O celular não respondeu ao teste" : "O teste falhou" })));
      }
      t0.alertas.forEach((a) => partes.push(el("div", { classe: "aviso", texto: a })));
    }
    $("d-teste").replaceChildren(el("h3", { texto: "Teste de Wi‑Fi" }), ...partes);

    // --- histórico
    const f = (v) => (v === null || v === undefined ? "—" : Number(v).toFixed(1));
    $("d-hist").replaceChildren(d.testes.length
      ? el("table", { classe: "hist" },
          el("thead", {}, el("tr", {}, ["Hora", "Modo", "Resultado", "Lat. ms", "Jitter", "Perda %", "Down", "Up", "IP", "Tipo de rede"].map((h) => el("th", { texto: h })))),
          el("tbody", {}, d.testes.map((t) => el("tr", {},
            el("td", { texto: fmtHora(t.solicitado_em) }), el("td", { texto: t.modo }),
            el("td", {}, t.resultado ? el("span", { classe: "chip " + t.resultado, texto: ROT_RES[t.resultado] }) : t.status),
            el("td", { texto: f(t.metricas.latencia_ms) }), el("td", { texto: f(t.metricas.jitter_ms) }),
            el("td", { texto: f(t.metricas.perda_pct) }), el("td", { texto: f(t.metricas.download_mbps) }),
            el("td", { texto: f(t.metricas.upload_mbps) }), el("td", { texto: t.ip_publico || "—" }),
            el("td", { texto: t.tipo_conexao || "—" })))))
      : el("div", { classe: "mudo pequeno", texto: "Nenhum teste ainda." }));

    // --- decisão (a caixa de texto não é recriada: o que você digita fica)
    const ultimo = d.testes.find((t) => t.status === "concluido");
    let dica = "Rode o teste de Wi‑Fi antes de aprovar.";
    if (!aberto) dica = p.status === "aprovado" || p.status === "recusado"
      ? ROT_STATUS[p.status] + " por " + (p.decidido_por_nome || "—") + " às " + fmtHora(p.decidido_em) + (p.motivo ? " — " + p.motivo : "")
      : "Pedido encerrado (" + ROT_STATUS[p.status].toLowerCase() + ").";
    else if (ativo) dica = "Espere o teste terminar.";
    else if (ultimo) dica = ultimo.resultado === "reprovado" ? "Rede reprovada: teste de novo ou recuse."
      : ultimo.resultado === "atencao" ? "Rede em atenção: aprove só com justificativa." : "Rede OK: pode aprovar.";
    $("d-dica").textContent = dica;
    $("btn-aprovar").disabled = !aberto || ativo || !ultimo || ultimo.resultado === "reprovado";
    $("btn-recusar").disabled = !aberto || ativo;
    $("d-motivo").disabled = !aberto;
  }

  const info = (rot, val) => el("div", {}, el("b", { texto: rot }), el("span", { texto: val || "—" }));

  /* ------------------------------------------------------------------ ações */
  async function testar(modo) {
    try {
      await api("/api/central/pedidos/" + selecionado + "/testar", { method: "POST", corpo: { modo } });
      toast("Teste enviado ao celular do técnico.");
      ciclo();
    } catch (e) { toast(e.message); ciclo(); }
  }

  async function decidir(decisao) {
    const motivo = $("d-motivo").value.trim();
    if (decisao === "recusar" && !motivo) { toast("Informe o motivo da recusa."); $("d-motivo").focus(); return; }
    if (!window.confirm(decisao === "aprovar" ? "Aprovar a conclusão desta atividade?" : "Recusar esta atividade?")) return;
    try {
      await api("/api/central/pedidos/" + selecionado + "/decisao", { method: "POST", corpo: { decisao, motivo: motivo || null } });
      toast(decisao === "aprovar" ? "Atividade aprovada." : "Atividade recusada.");
      $("d-motivo").value = "";
    } catch (e) { toast(e.message); }
    ciclo();
  }

  ciclo();
})();
