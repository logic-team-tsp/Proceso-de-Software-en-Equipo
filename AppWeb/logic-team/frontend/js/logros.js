// CU08 - Obtener logros. Botón de Logros, notificaciones y panel (logros_panel.html).
// El servidor decide qué logros se desbloquean (app/services/logros.py): las respuestas JSON
// de la partida y de los minijuegos traen el bloque {"cu08": {"nuevos": [...], "pendiente"}}.
// Este archivo envuelve window.fetch para leer ese bloque sin tocar el código de cada
// minijuego, y muestra las notificaciones una tras otra (paso 6, FA1).
//   FA3  si hay un minijuego abierto encima del libro (CU06), las notificaciones esperan.
//   FE1  si no se pudo guardar, guarda el progreso pendiente en el navegador y lo reintenta.
//   Pasos 10-16, FA6, FA7, FE2: el panel con Ranking personal, Logros y Finales.
// Nivel del jugador: la XP se acumula entre partidas y minijuegos; el número va en el botón
// del trofeo, el título y su avance en el panel, y al subir de nivel sale una notificación.
// API pública: window.CU08Logros = { abrir(pestaña), cerrar(), notificar(logros), recibir(cu08) }
(function () {
  "use strict";

  const root = document.getElementById("logros-root");
  if (!root) return;

  const api = {
    resumen: root.dataset.apiResumen,
    ranking: root.dataset.apiRanking,
    informe: root.dataset.apiInforme,
    reintentar: root.dataset.apiReintentar,
    nivel: root.dataset.apiNivel,
    jugar: root.dataset.urlJugar,
  };
  const boton = document.getElementById("logros-btn");
  const toasts = document.getElementById("logros-toasts");
  const aviso = document.getElementById("logros-aviso");
  const avisoTxt = document.getElementById("logros-aviso-txt");
  const velo = document.getElementById("logros-velo");
  const panel = velo.querySelector(".lg-panel");
  const cuerpo = document.getElementById("logros-cuerpo");
  const pausa = document.getElementById("logros-pausa");
  const cerrarBtn = document.getElementById("logros-cerrar");
  const pestanas = [...velo.querySelectorAll(".lg-tab")];
  const pctLogros = document.getElementById("lg-pct-logros");
  const pctFinales = document.getElementById("lg-pct-finales");
  const nivelBadge = document.getElementById("logros-nivel-badge");
  const nivelCaja = document.getElementById("logros-nivel");

  const DURACION = 3600;          // la notificación se va sola en 3-4 s
  const REINTENTO = 5;            // FE1: segundos entre reintentos
  const CLAVE_PENDIENTES = "logicteam.logros.pendientes";

  // ------------------------------------------------------------ utilidades
  function el(etiqueta, clase, texto) {
    const nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined && texto !== null) nodo.textContent = texto;
    return nodo;
  }

  function con(padre, ...hijos) {
    hijos.forEach((hijo) => { if (hijo) padre.appendChild(hijo); });
    return padre;
  }

  function vaciar(nodo) { while (nodo.firstChild) nodo.removeChild(nodo.firstChild); }

  function boton_(clase, texto, alHacerClic) {
    const b = el("button", clase, texto);
    b.type = "button";
    if (alHacerClic) b.addEventListener("click", alHacerClic);
    return b;
  }

  function oculto(nodo) { nodo.setAttribute("aria-hidden", "true"); return nodo; }

  // 13425 -> «13 425» (como en el mockup)
  const miles = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " ");

  function cookie(nombre) {
    const m = document.cookie.match(new RegExp(`(?:^|; )${nombre}=([^;]*)`));
    return m ? decodeURIComponent(m[1]) : "";
  }

  function leer(clave, porDefecto) {
    try { return JSON.parse(localStorage.getItem(clave)) || porDefecto; } catch (e) { return porDefecto; }
  }

  function escribir(clave, valor) {
    try { localStorage.setItem(clave, JSON.stringify(valor)); } catch (e) { /* sin almacenamiento */ }
  }

  // ------------------------------------------------------------ notificaciones (pasos 6, FA1, FA3)
  const cola = [];
  let mostrando = false;

  // FA3: mientras el minijuego de vidas (CU06) está abierto sobre el libro, se espera
  const enMinijuego = () => !!document.querySelector(".cv-capa");

  function tarjetaAviso(logro) {
    const t = el("div", "lg-toast" + (logro.tipo === "nivel" ? " nivel" : ""));
    t.style.setProperty("--lg-dura", `${DURACION}ms`);
    return con(
      t,
      oculto(el("div", "sello", logro.icono)),
      con(el("div"), el("small", null, logro.tipo === "nivel" ? "¡SUBISTE DE NIVEL!" : "¡LOGRO DESBLOQUEADO!"),
        el("b", null, logro.nombre),
        el("span", "d", logro.descripcion)),
      oculto(el("span", "tiempo"))
    );
  }

  function siguiente() {
    if (mostrando || !cola.length) return;
    if (enMinijuego()) { setTimeout(siguiente, 700); return; }
    mostrando = true;
    const logro = cola.shift();
    vaciar(toasts);
    if (cola.length) {
      con(toasts, el("span", "lg-cola", `+${cola.length} en cola`));
    }
    const tarjeta = tarjetaAviso(logro);
    con(toasts, tarjeta);
    if (cola.length) con(toasts, oculto(el("div", "lg-toast atras")));
    setTimeout(() => {
      tarjeta.classList.add("sale");
      setTimeout(() => {
        vaciar(toasts);
        mostrando = false;
        siguiente();
      }, 300);
    }, DURACION);
  }

  function notificar(lista) {
    (lista || []).forEach((logro) => cola.push(logro));
    siguiente();
  }

  // ------------------------------------------------------------ FE1: progreso sin guardar
  let temporizador = null;

  function mostrarAviso(segundos) {
    aviso.hidden = false;
    avisoTxt.textContent = segundos > 0 ? `Reintentando en ${segundos} s…` : "Reintentando…";
  }

  function programarReintento() {
    clearInterval(temporizador);
    let faltan = REINTENTO;
    mostrarAviso(faltan);
    temporizador = setInterval(() => {
      faltan -= 1;
      mostrarAviso(faltan);
      if (faltan <= 0) {
        clearInterval(temporizador);
        reintentar();
      }
    }, 1000);
  }

  async function reintentar() {
    const pendientes = leer(CLAVE_PENDIENTES, []);
    if (!pendientes.length) { aviso.hidden = true; return; }
    const quedan = [];
    for (const token of pendientes) {
      try {
        const r = await fetch(api.reintentar, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": cookie("csrftoken"), Accept: "application/json" },
          body: JSON.stringify({ pendiente: token }),
        });
        if (r.status >= 500) quedan.push(token); // 400: el token ya no sirve, se descarta
      } catch (e) {
        quedan.push(token);
      }
    }
    // la respuesta (con su bloque cu08) ya la procesó la envoltura de fetch
    const nuevos = leer(CLAVE_PENDIENTES, []).filter((t) => !pendientes.includes(t));
    escribir(CLAVE_PENDIENTES, [...quedan, ...nuevos]);
    if (quedan.length || nuevos.length) programarReintento();
    else aviso.hidden = true;
  }

  // ------------------------------------------------------------ nivel del jugador
  function pintarNivel(n) {
    if (!n) return;
    nivelBadge.textContent = String(n.nivel);
    nivelBadge.hidden = false;
    const texto = `Logros y ranking personal · Nivel ${n.nivel}, ${n.titulo}`;
    boton.setAttribute("aria-label", texto);
    boton.title = texto;
    vaciar(nivelCaja);
    const num = el("div", "num", String(n.nivel));
    num.prepend(el("small", null, "NIV."));
    const titulo = el("div", "tit", n.titulo);
    if (n.siguiente_titulo) {
      con(titulo, el("span", null, ` · «${n.siguiente_titulo.titulo}» en el nivel ${n.siguiente_titulo.desde}`));
    }
    const pista = el("span", "pista");
    const i = el("i");
    i.style.width = `${n.porcentaje}%`;
    const avance = n.es_maximo ? "Nivel máximo" : `${miles(n.xp_en_nivel)}/${miles(n.xp_necesaria)} XP para el nivel ${n.nivel + 1}`;
    const barra = con(el("div", "lg-xp"), con(pista, i), el("span", "txt", avance));
    barra.setAttribute("role", "progressbar");
    barra.setAttribute("aria-valuemin", "0");
    barra.setAttribute("aria-valuemax", "100");
    barra.setAttribute("aria-valuenow", String(n.porcentaje));
    barra.setAttribute("aria-label", avance);
    con(nivelCaja, num, titulo, barra);
    nivelCaja.hidden = false;
  }

  function avisoNivel(n) {
    return {
      tipo: "nivel",
      icono: "⭐",
      nombre: `Nivel ${n.nivel} · ${n.titulo}`,
      descripcion: n.titulo_nuevo ? `¡Nuevo título: ${n.titulo}!` : `Tu experiencia total: ${miles(n.xp_total)} XP.`,
    };
  }

  function recibir(cu08) {
    if (!cu08 || typeof cu08 !== "object") return;
    if (cu08.nivel) {
      pintarNivel(cu08.nivel);
      if (cu08.nivel.subio) notificar([avisoNivel(cu08.nivel)]);
    }
    if (Array.isArray(cu08.nuevos) && cu08.nuevos.length) notificar(cu08.nuevos);
    if (cu08.pendiente) {
      const pendientes = leer(CLAVE_PENDIENTES, []);
      if (!pendientes.includes(cu08.pendiente)) pendientes.push(cu08.pendiente);
      escribir(CLAVE_PENDIENTES, pendientes);
      programarReintento();
    }
    if (abierto) cargar(); // el panel abierto se actualiza
  }

  // Envoltura de fetch: cualquier respuesta JSON con "cu08" pasa por recibir()
  if (typeof window.fetch === "function") {
    const fetchOriginal = window.fetch.bind(window);
    window.fetch = function (...args) {
      return fetchOriginal(...args).then((respuesta) => {
        try {
          const tipo = respuesta.headers.get("content-type") || "";
          if (tipo.includes("application/json")) {
            respuesta.clone().json().then((datos) => {
              if (datos && typeof datos === "object" && datos.cu08) recibir(datos.cu08);
            }).catch(() => {});
          }
        } catch (e) { /* nunca rompe la petición original */ }
        return respuesta;
      });
    };
  }

  // ------------------------------------------------------------ panel (pasos 10-16)
  let abierto = false;
  let pestana = "logros";
  let resumen = null;       // GET /api/logros/
  let rankingDatos = null;  // GET /api/logros/ranking/
  let historia = "";        // FA7: filtro del ranking
  let informeId = null;     // paso 14
  const filtros = { categoria: "todas", estado: "todos" }; // FA7
  let enfoqueAntes = null;

  async function pedir(url) {
    const r = await fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    const datos = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(datos.error || "No se pudieron cargar tus logros.");
    return datos;
  }

  // Pausa (paso 11): hay partida o minijuego en esta pantalla
  const hayPartida = () => !!document.querySelector("#pt-spread, .tl-mesa, .pagina-mesa");

  function abrir(tab) {
    if (tab) pestana = tab;
    informeId = null;
    if (!abierto) {
      enfoqueAntes = document.activeElement;
      abierto = true;
      velo.hidden = false;
      boton.setAttribute("aria-expanded", "true");
      pausa.hidden = !hayPartida();
      document.documentElement.classList.add("lg-abierto");
      panel.focus({ preventScroll: true });
    }
    cargar();
  }

  function cerrar() {
    if (!abierto) return;
    abierto = false;
    velo.hidden = true;
    boton.setAttribute("aria-expanded", "false");
    document.documentElement.classList.remove("lg-abierto");
    // Paso 16: regresa a donde estaba (el foco vuelve al control que abrió el panel)
    const destino = enfoqueAntes && document.contains(enfoqueAntes) ? enfoqueAntes : boton;
    destino.focus({ preventScroll: true });
  }

  function marcarPestana() {
    pestanas.forEach((t) => {
      const activa = t.dataset.tab === pestana;
      t.setAttribute("aria-selected", activa ? "true" : "false");
      t.tabIndex = activa ? 0 : -1;
    });
  }

  function cargando() {
    vaciar(cuerpo);
    con(cuerpo, el("p", "lg-cargando", "Abriendo tu libro de logros…"));
  }

  async function cargar() {
    marcarPestana();
    if (!resumen) cargando();
    try {
      const peticiones = [pedir(api.resumen)];
      if (pestana === "ranking") {
        const url = historia ? `${api.ranking}?historia=${encodeURIComponent(historia)}` : api.ranking;
        peticiones.push(pedir(url));
      }
      const [r, rk] = await Promise.all(peticiones);
      resumen = r;
      if (rk) rankingDatos = rk;
      pctLogros.textContent = ` · ${resumen.logros.porcentaje}%`;
      pctFinales.textContent = ` · ${resumen.finales.porcentaje}%`;
      pintarNivel(resumen.nivel);
      if (informeId) await pintarInforme(informeId);
      else pintar();
    } catch (err) {
      pintarError(err.message); // FE2
    }
  }

  function pintar() {
    vaciar(cuerpo);
    if (pestana === "ranking") pintarRanking();
    else if (pestana === "finales") pintarFinales();
    else pintarLogros();
  }

  // ------------------------------------------------------------ FE2
  function pintarError() {
    pctLogros.textContent = " · —";
    pctFinales.textContent = " · —";
    vaciar(cuerpo);
    const reintentarBtn = boton_("lg-btn go", "↻ Reintentar", () => cargar());
    con(
      cuerpo,
      con(
        el("div", "lg-vacio error"),
        oculto(el("div", "emblema", "⚠️")),
        el("h3", null, "No se pudieron cargar tus logros"),
        el("p", null, hayPartida()
          ? "Tu partida sigue en pausa y no se ha perdido nada. Intenta de nuevo en un momento."
          : "No se ha perdido nada. Intenta de nuevo en un momento."),
        con(el("div", "botones"), boton_("lg-btn", "Cerrar", cerrar), reintentarBtn)
      )
    );
    reintentarBtn.focus({ preventScroll: true });
  }

  // ------------------------------------------------------------ tarjetas
  function barraProgreso(porcentaje, texto) {
    const barra = el("div", "lg-barra");
    barra.setAttribute("role", "progressbar");
    barra.setAttribute("aria-valuenow", String(porcentaje));
    barra.setAttribute("aria-valuemin", "0");
    barra.setAttribute("aria-valuemax", "100");
    barra.setAttribute("aria-label", texto);
    const relleno = el("i");
    relleno.style.width = `${porcentaje}%`;
    return con(
      el("div", "lg-progreso"),
      el("span", "big", `${porcentaje}%`),
      el("span", "k", texto),
      con(barra, relleno)
    );
  }

  function tarjetaLogro(logro) {
    let clase = "lg-logro " + (logro.obtenido ? "obtenido" : "bloqueado");
    if (!logro.obtenido && logro.oculto) clase += " oculto";
    const enProgreso = !logro.obtenido && logro.progresivo && logro.valor > 0;
    if (enProgreso) clase += " progreso";
    const texto = con(el("div"), el("h4", null, logro.nombre), el("p", null, logro.descripcion));
    const estado = el("div", "lg-estado");
    if (logro.obtenido) {
      con(estado, oculto(el("span", "lg-sello", "✔")), el("span", "t", "OBTENIDO"), el("span", "f", logro.fecha));
    } else if (enProgreso) {
      // FA2: avance actual / meta
      const pista = el("span", "pista");
      const i = el("i");
      i.style.width = `${logro.porcentaje}%`;
      con(texto, con(el("div", "lg-avance"), con(pista, i), el("span", null, `${logro.porcentaje}%`)));
      con(estado, el("b", null, `${miles(logro.valor)}/${miles(logro.meta)}`), el("span", "t", "EN PROGRESO"));
    } else {
      con(estado, oculto(el("span", "lg-candado", "🔒")), el("span", "t", logro.oculto ? "OCULTO" : "BLOQUEADO"));
    }
    return con(el("div", clase), oculto(el("div", "ico", logro.icono)), texto, estado);
  }

  function chip(texto, activo, alHacerClic) {
    const b = boton_("lg-chip", texto, alHacerClic);
    b.setAttribute("aria-pressed", activo ? "true" : "false");
    return b;
  }

  // ------------------------------------------------------------ pestaña Logros (paso 12, FA2, FA7)
  function pintarLogros() {
    const r = resumen;
    con(cuerpo, barraProgreso(r.logros.porcentaje, `Logros: ${r.logros.porcentaje}% (${r.logros.obtenidos}/${r.logros.total})`));

    const grupoCat = con(el("div", "grupo"), el("span", "k", "Categoría:"));
    con(grupoCat, chip("Todas", filtros.categoria === "todas", () => { filtros.categoria = "todas"; pintar(); }));
    r.categorias.forEach((c) => con(grupoCat, chip(c.nombre, filtros.categoria === c.id, () => { filtros.categoria = c.id; pintar(); })));
    const grupoEst = con(el("div", "grupo"), el("span", "k", "Estado:"));
    [["todos", "Todos"], ["obtenidos", "Obtenidos"], ["bloqueados", "Bloqueados"]].forEach(([id, texto]) => {
      con(grupoEst, chip(texto, filtros.estado === id, () => { filtros.estado = id; pintar(); }));
    });
    con(cuerpo, con(el("div", "lg-filtros"), grupoCat, grupoEst));

    let mostrados = 0;
    r.categorias.forEach((c) => {
      if (filtros.categoria !== "todas" && filtros.categoria !== c.id) return;
      const lista = c.logros.filter((lg) =>
        filtros.estado === "todos" || (filtros.estado === "obtenidos" ? lg.obtenido : !lg.obtenido));
      if (!lista.length) return;
      mostrados += lista.length;
      const titulo = el("h3", null, `${c.icono} ${c.nombre}${filtros.estado === "todos" ? "" : " · " + filtros.estado} `);
      con(titulo, el("span", null, `· ${c.obtenidos}/${c.total}`));
      const contadores = el("span", "cont");
      c.contadores.forEach((k, n) => {
        if (n) contadores.appendChild(document.createTextNode(" · "));
        contadores.appendChild(document.createTextNode(`${k.nombre}: `));
        con(contadores, el("b", null, miles(k.valor)));
      });
      const grid = el("div", "lg-grid");
      lista.forEach((lg) => con(grid, tarjetaLogro(lg)));
      con(cuerpo, con(el("section", "lg-cat"), con(el("div", "lg-cat-cab"), titulo, contadores), grid));
    });
    if (!mostrados) con(cuerpo, el("p", "lg-pie-rank", "No hay logros con estos filtros."));
    else if (filtros.categoria !== "todas" || filtros.estado !== "todos") {
      con(cuerpo, el("p", "lg-pie-rank", `Mostrando ${mostrados} de ${r.logros.total} logros`));
    }
  }

  // ------------------------------------------------------------ pestaña Finales (paso 12, RN08)
  function pintarFinales() {
    const f = resumen.finales;
    const resumenFin = el("p", "lg-resumen-fin", "Finales desbloqueados: ");
    con(resumenFin, el("b", null, `${f.porcentaje}% (${f.desbloqueados}/${f.total})`));
    const lista = el("div", "lg-historias");
    f.historias.forEach((h) => {
      const anillo = el("div", "lg-anillo");
      anillo.style.setProperty("--p", `${h.porcentaje}%`);
      con(anillo, el("b", null, `${h.porcentaje}%`));
      const finales = el("div", "lg-finales");
      h.finales.forEach((fin) => {
        if (fin.descubierto) con(finales, el("span", "lg-fin" + (fin.nuevo ? " nuevo" : ""), `«${fin.titulo}»`));
        else {
          const no = el("span", "lg-fin no", "?");
          no.setAttribute("aria-label", "Final no descubierto");
          con(finales, no);
        }
      });
      con(lista, con(el("div", "lg-historia"), anillo,
        con(el("div"), el("h3", null, `Historia · ${h.nombre}`),
          el("span", "cnt", `${h.desbloqueados} de ${h.total} finales desbloqueados`), finales)));
    });
    con(cuerpo, resumenFin, lista, el("p", "lg-pie-rank", "Los finales que aún no descubres aparecen como «?»."));
  }

  // ------------------------------------------------------------ pestaña Ranking (paso 13, FA6, FA7)
  function pintarRanking() {
    const rk = rankingDatos;
    if (!rk) { cargando(); return; }
    if (!rk.registradas) { // FA6
      const jugar = el("a", "lg-btn go", "Iniciar juego ➔");
      jugar.href = api.jugar;
      const r = resumen;
      con(
        cuerpo,
        con(el("div", "lg-vacio"), oculto(el("div", "emblema", "📜")), el("h3", null, "Tu ranking está en blanco"),
          el("p", null, "Aún no tienes puntuaciones. ¡Termina tu primera historia!"), jugar),
        con(el("div", "lg-ceros"),
          barraProgreso(r.logros.porcentaje, `Logros: ${r.logros.porcentaje}% (${r.logros.obtenidos}/${r.logros.total})`),
          barraProgreso(r.finales.porcentaje, `Finales: ${r.finales.porcentaje}% (${r.finales.desbloqueados}/${r.finales.total})`))
      );
      return;
    }
    // FA7: clasificación general o de una historia
    const general = chip("Clasificación general", !rk.historia, () => { historia = ""; cargar(); });
    const selector = el("select", "lg-sel");
    selector.setAttribute("aria-label", "Ranking por historia");
    con(selector, el("option", null, "Por historia…"));
    selector.firstChild.value = "";
    rk.historias.forEach((h) => {
      const op = el("option", null, h.nombre);
      op.value = h.id;
      if (rk.historia === h.id) op.selected = true;
      con(selector, op);
    });
    selector.addEventListener("change", () => { historia = selector.value; cargar(); });
    con(cuerpo, con(el("div", "lg-filtros"), con(el("div", "grupo"), el("span", "k", "Ver:"), general, selector)));

    if (!rk.top.length) {
      con(cuerpo, el("p", "lg-pie-rank", "Todavía no tienes puntuaciones en esta historia."));
      return;
    }
    const tabla = el("table", "lg-rank");
    const cab = el("thead");
    const filaCab = el("tr");
    ["#", "Historia", "Puntuación", "Fecha"].forEach((t, i) => {
      const th = el("th", null, t);
      th.scope = "col";
      if (i === 2) th.style.textAlign = "right";
      con(filaCab, th);
    });
    con(tabla, con(cab, filaCab));
    const cuerpoTabla = el("tbody");
    rk.top.forEach((p) => {
      const tr = el("tr", [p.posicion === 1 ? "top1" : "", p.reciente ? "reciente" : ""].join(" ").trim());
      tr.tabIndex = 0;
      tr.setAttribute("aria-label", `Posición ${p.posicion}: ${miles(p.total)} puntos. Ver informe`);
      const hist = el("td", "hist", p.historia);
      if (p.reciente) con(hist, el("span", "lg-marca", "★ Última partida"));
      con(hist, el("small", null, `Final «${p.final}»`));
      con(tr, con(el("td"), el("div", "lg-med", String(p.posicion))), hist,
        el("td", "pts", `${miles(p.total)} pts`), el("td", "fecha", p.fecha));
      const ver = () => { informeId = p.id; cargar(); };
      tr.addEventListener("click", ver);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ver(); } });
      con(cuerpoTabla, tr);
    });
    con(cuerpo, con(tabla, cuerpoTabla),
      el("p", "lg-pie-rank", `Tus ${rk.tamano_top} mejores puntuaciones · toca una para ver su informe`));
  }

  // ------------------------------------------------------------ informe (paso 14)
  function tablaDesglose(desglose, total) {
    const tabla = el("table", "lg-desglose");
    const cab = el("tr");
    [["Componente", ""], ["Cantidad", "n"], ["Puntos", "p"]].forEach(([t, c]) => {
      const th = el("th", c, t);
      th.scope = "col";
      con(cab, th);
    });
    const cuerpoT = el("tbody");
    desglose.forEach((f) => {
      const cantidad = f.valor === null || f.valor === undefined ? String(f.cantidad) : `${f.cantidad} × ${f.valor}`;
      con(cuerpoT, con(el("tr"), el("td", null, f.nombre), el("td", "n", cantidad), el("td", "p", miles(f.puntos))));
    });
    const totalTd = el("td", null, "Total");
    totalTd.colSpan = 2;
    return con(tabla, con(el("thead"), cab), cuerpoT,
      con(el("tfoot"), con(el("tr"), totalTd, el("td", "p", miles(total)))));
  }

  async function pintarInforme(id) {
    const d = await pedir(`${api.informe}${id}/`);
    vaciar(cuerpo);
    const volver = boton_("lg-btn chico", "⬅ Volver al ranking", () => { informeId = null; pintar(); });
    const total = el("div", "total", miles(d.total));
    con(total, el("small", null, "puntos"));
    const logrosLista = el("div", "lg-lista");
    if (d.logros.length) d.logros.forEach((lg) => con(logrosLista, tarjetaLogro(lg)));
    else con(logrosLista, el("p", "lg-ayuda", "No obtuviste logros nuevos en esa partida."));
    const hoja = con(el("div", "sheet"),
      con(el("div", "sheet-row"), el("span", "k", "Vidas perdidas"), el("span", "v", String(d.vidas_perdidas))),
      con(el("div", "sheet-row"), el("span", "k", "Minijuegos de vidas"),
        el("span", "v", `${d.minijuegos_jugados} (${d.minijuegos_ganados} ganados)`)));
    hoja.style.marginTop = "12px";
    con(
      cuerpo,
      con(el("div", "lg-volver"), volver),
      con(el("div", "lg-ficha"), el("div", "lg-med", String(d.posicion || "–")),
        con(el("div"), el("h3", null, d.historia), el("p", null, `Final «${d.final}» · ${d.fecha}`)), total),
      con(el("div", "lg-informe"),
        con(el("div"), el("h2", "lg-subt", "Desglose de puntuación"), tablaDesglose(d.desglose, d.total)),
        con(el("div"), el("h2", "lg-subt", `Logros de esa partida${d.logros.length ? ` (${d.logros.length})` : ""}`), logrosLista, hoja))
    );
    volver.focus({ preventScroll: true });
  }

  // ------------------------------------------------------------ eventos
  boton.addEventListener("click", () => (abierto ? cerrar() : abrir()));
  cerrarBtn.addEventListener("click", cerrar);
  velo.addEventListener("click", (e) => { if (e.target === velo) cerrar(); });
  pestanas.forEach((t, i) => {
    t.addEventListener("click", () => { pestana = t.dataset.tab; informeId = null; cargar(); });
    t.addEventListener("keydown", (e) => { // flechas entre pestañas
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const otra = pestanas[(i + (e.key === "ArrowRight" ? 1 : pestanas.length - 1)) % pestanas.length];
      otra.focus();
      otra.click();
    });
  });
  document.addEventListener("keydown", (e) => {
    if (!abierto) return;
    if (e.key === "Escape") { e.preventDefault(); cerrar(); return; }
    if (e.key !== "Tab") return;
    // El foco se queda dentro del panel mientras está abierto
    const enfocables = [...panel.querySelectorAll("button, a[href], select, [tabindex='0']")]
      .filter((n) => !n.disabled && n.offsetParent !== null);
    if (!enfocables.length) return;
    const primero = enfocables[0];
    const ultimo = enfocables[enfocables.length - 1];
    if (e.shiftKey && (document.activeElement === primero || document.activeElement === panel)) {
      e.preventDefault(); ultimo.focus();
    } else if (!e.shiftKey && document.activeElement === ultimo) {
      e.preventDefault(); primero.focus();
    }
  });
  // Botones de otras pantallas (p. ej. «Ver mi ranking» en el Post Game)
  document.addEventListener("click", (e) => {
    const disparador = e.target.closest && e.target.closest("[data-lg-abrir]");
    if (disparador) { e.preventDefault(); abrir(disparador.dataset.lgAbrir || "logros"); }
  });

  if (leer(CLAVE_PENDIENTES, []).length) programarReintento(); // FE1 de una visita anterior
  // Nivel del jugador en el botón del trofeo (si falla, el botón se queda sin número)
  if (api.nivel) pedir(api.nivel).then(pintarNivel).catch(() => {});

  window.CU08Logros = { abrir, cerrar, notificar, recibir };
})();
