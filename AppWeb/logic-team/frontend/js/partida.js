// CU01 - Realizar partida. Dibuja el libro con el estado que manda el servidor.
// El servidor decide todo (resultado, vidas, probabilidades); aquí solo se pinta y se envía la
// opción elegida. Usa las clases de libro.css (.page, .choice, .medallion, .stamp, .book-btn).
(function () {
  "use strict";

  const spread = document.getElementById("pt-spread");
  const izq = document.getElementById("pt-izq");
  const der = document.getElementById("pt-der");
  const aviso = document.getElementById("pt-aviso");
  const listonCap = document.getElementById("ribbon-cap");
  const base = `/partida/${spread.dataset.partida}/`;
  const claveRespaldo = `logicteam.partida.${spread.dataset.partida}`;
  const LETRAS = "ABCD";

  // ------------------------------------------------------------ utilidades
  // Efectos de sonido (js/sonidos.js); se apagan desde el panel de ajustes
  const sonar = (nombre) => { if (window.LTSonidos) window.LTSonidos.tocar(nombre); };

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

  function cookie(nombre) {
    const m = document.cookie.match(new RegExp(`(?:^|; )${nombre}=([^;]*)`));
    return m ? decodeURIComponent(m[1]) : "";
  }

  function mostrarAviso(mensaje) {
    aviso.textContent = mensaje;
    aviso.hidden = false;
    clearTimeout(mostrarAviso.t);
    mostrarAviso.t = setTimeout(() => { aviso.hidden = true; }, 7000);
  }

  async function llamar(ruta, cuerpo) {
    const opciones = { headers: { Accept: "application/json" }, credentials: "same-origin" };
    if (cuerpo !== undefined) {
      opciones.method = "POST";
      opciones.headers["Content-Type"] = "application/json";
      opciones.headers["X-CSRFToken"] = cookie("csrftoken");
      opciones.body = JSON.stringify(cuerpo);
    }
    let respuesta;
    try {
      respuesta = await fetch(base + ruta, opciones);
    } catch (e) {
      throw new Error("No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.");
    }
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(datos.error || "No se pudo completar la acción.");
    return datos;
  }

  // Autoguardado local del avance (RNF-CON-06); el progreso real vive en el servidor.
  function respaldar(e) {
    try {
      localStorage.setItem(claveRespaldo, JSON.stringify({
        guardado: new Date().toISOString(), hp: e.hp, hp_max: e.hp_max,
        xp: e.xp, progreso: e.progreso, puntuacion: e.puntuacion,
      }));
    } catch (err) { /* el navegador puede bloquear el almacenamiento */ }
  }

  function leerRespaldo() {
    try { return JSON.parse(localStorage.getItem(claveRespaldo)); } catch (err) { return null; }
  }

  // CU06 - Conseguir vidas (js/vidas.js): botón permanente y minijuego sobre el libro.
  // Al volver del minijuego el libro se repinta sin pasar la página.
  const vidas = window.CU06Vidas
    ? window.CU06Vidas.conectar({ llamar, alActualizar: (e) => pintar(e, false) })
    : null;

  // CU05 (cambios a CU01, RF-39 y RF-40): resalta y explica los tecnicismos (js/tecnicismos.js).
  const tec = window.CU01Tecnicismos || null;
  function resaltar(nodos, e, interactivo = true) {
    if (tec && e.tecnicismos && e.tecnicismos.length) tec.resaltar(nodos, e.tecnicismos, { interactivo, nuevos: e.tecnicismos_nuevos });
  }

  // ------------------------------------------------------------ piezas del libro
  const ornamento = () => { const o = el("div", "ornament"); o.setAttribute("aria-hidden", "true"); return o; };
  const numeroPagina = (n) => el("span", "page-num", `— ${n} —`);
  const sello = (texto, extra) => el("span", `stamp${extra ? " " + extra : ""}`, texto);

  const porcentaje = (valor, maximo) => (maximo ? Math.min(100, (valor / maximo) * 100) : 0);

  // Último estado pintado: sirve para animar lo que cambió (vidas, XP, avance).
  let previo = null;

  // Número que sale flotando de una barra («−1», «+30 XP») y se desvanece
  function flotante(fila, texto, clase) {
    if (sinMovimiento()) return;
    const f = el("span", `pt-flota ${clase}`, texto);
    f.setAttribute("aria-hidden", "true");
    fila.appendChild(f);
    setTimeout(() => f.remove(), 1100);
  }

  // Cuenta del número de XP de la etiqueta de la barra, de «desde» a «hasta»
  function contar(nodo, desde, hasta, plantilla) {
    if (sinMovimiento() || desde === hasta) return;
    const t0 = performance.now(), dura = 650;
    (function paso(t) {
      const k = Math.min(1, (t - t0) / dura);
      nodo.textContent = plantilla(Math.round(desde + (hasta - desde) * (1 - Math.pow(1 - k, 3))));
      if (k < 1) requestAnimationFrame(paso);
    })(t0);
  }

  // HUD fuera del libro (sistema visual): capítulo y avance al centro; vidas, nivel y XP a la
  // derecha; «Conseguir vidas» (CU06) a su lado. Anima lo que cambió respecto al estado anterior.
  const hudCap = document.getElementById("hud-cap");
  const hudSeg = document.getElementById("hud-seg");
  const hudEvento = document.getElementById("hud-evento");
  const hudVidas = document.getElementById("hud-vidas");
  const hudXp = document.getElementById("hud-xp");
  const hudCv = document.getElementById("hud-cv");

  function hud(e) {
    const p = previo;
    hudCap.textContent = `Capítulo ${e.bloque.capitulo} · ${e.bloque.nombre}`;

    // Avance: un segmento por evento (si son muchos, se agrupan para que quepan)
    const total = Math.max(1, e.evento_total);
    const tramos = Math.min(total, 20);
    const hechos = Math.round((Math.max(0, e.evento_numero - (e.fase === "evento" ? 1 : 0)) / total) * tramos);
    const actual = Math.min(tramos - 1, Math.floor(((e.evento_numero - 1) / total) * tramos));
    vaciar(hudSeg);
    for (let i = 0; i < tramos; i++) {
      con(hudSeg, el("i", i < hechos ? "on" : (i === actual ? "actual" : "")));
    }
    // Texto largo en computadora y corto («1/60») en celular; el CSS elige cuál se ve
    vaciar(hudEvento);
    con(hudEvento,
      el("span", "pt-ev-largo", `Evento ${e.evento_numero} de ${e.evento_total}`),
      el("span", "pt-ev-corto", `${e.evento_numero}/${e.evento_total}`));
    hudSeg.parentNode.setAttribute("aria-label", `Historia: ${e.progreso}% · evento ${e.evento_numero} de ${e.evento_total}`);

    // Vidas: corazones llenos y vacíos
    const corazones = el("span", "k pt-hud-corazones");
    for (let i = 0; i < e.hp_max; i++) con(corazones, el("span", i < e.hp ? "lleno" : "vacio", i < e.hp ? "❤" : "♡"));
    vaciar(hudVidas);
    con(hudVidas, corazones);
    hudVidas.setAttribute("aria-label", `Vidas: ${e.hp} de ${e.hp_max}`);
    hudVidas.classList.remove("pt-pierde", "pt-gana");

    // Nivel y XP
    const mismoNivel = p && p.nivel === e.nivel;
    const maximo = e.nivel >= e.nivel_maximo;
    const textoXp = (x) => (maximo ? "nivel máximo" : `${x} / ${e.xp_por_nivel} XP`);
    const meta = maximo ? 100 : porcentaje(e.xp_en_nivel, e.xp_por_nivel);
    const desde = p ? (mismoNivel ? porcentaje(p.xp_en_nivel, p.xp_por_nivel) : 0) : meta;
    const relleno = el("i");
    const anima = p && !sinMovimiento() && desde !== meta;
    relleno.style.width = `${anima ? desde : meta}%`;
    if (anima) requestAnimationFrame(() => requestAnimationFrame(() => { relleno.style.width = `${meta}%`; }));
    const valorXp = el("span", "v", textoXp(e.xp_en_nivel));
    vaciar(hudXp);
    con(hudXp,
      con(el("div", "pt-hud-xp-cab"), con(el("span", "k"), document.createTextNode(`⭐ Nivel ${e.nivel}`)), valorXp),
      con(el("span", "pt-pista"), relleno));
    hudXp.classList.remove("pt-pierde", "pt-gana");

    if (p && !sinMovimiento()) {
      void hudVidas.offsetWidth;
      // Vidas: los corazones se sacuden al perder y rebotan al recuperar
      if (e.hp < p.hp) { hudVidas.classList.add("pt-pierde"); flotante(hudVidas, `−${p.hp - e.hp}`, "mal"); setTimeout(() => sonar("vida-menos"), 250); }
      if (e.hp > p.hp) { hudVidas.classList.add("pt-gana"); flotante(hudVidas, `+${e.hp - p.hp}`, "bien"); setTimeout(() => sonar("vida-mas"), 150); }
      // XP: sube un «+N XP» y el número cuenta hasta el valor nuevo
      if (e.xp > p.xp) {
        flotante(hudXp, `+${e.xp - p.xp} XP`, "oro");
        if (mismoNivel) contar(valorXp, p.xp_en_nivel, e.xp_en_nivel, textoXp);
        else hudXp.classList.add("pt-gana");
      }
    }

    // CU06: botón permanente de «Conseguir vidas», siempre a la vista junto a las vidas
    vaciar(hudCv);
    if (vidas && e.vidas) con(hudCv, vidas.boton(e));

    // Celular: atributos resumidos (icono + valor). Al tocarlos se abre la hoja de personaje.
    estadoHoja = e;
    vaciar(hudStats);
    e.atributos.forEach((a) => con(hudStats,
      con(el("span", "pt-chip"), document.createTextNode(`${a.icono} `), el("b", null, String(a.valor)))));
    if (e.puntos_atributo > 0) con(hudStats, el("span", "pt-chip pt-chip-oro", `✨ ${e.puntos_atributo}`));
    hudStats.setAttribute("aria-label",
      `Ver atributos: ${e.atributos.map((a) => `${a.nombre} ${a.valor}`).join(", ")}`);
    if (hojaVelo && !hojaVelo.hidden) llenarHoja(e);
  }

  // ------------------------------------------------------------ hoja de personaje (celular)
  // Bottom sheet al estilo Life in Adventure: todos los atributos, qué significan, nivel y vidas.
  const hudStats = document.getElementById("hud-stats");
  const hojaVelo = document.getElementById("pt-hoja-velo");
  const hojaCuerpo = document.getElementById("pt-hoja-cuerpo");
  let estadoHoja = null;
  let focoAntesHoja = null;

  function llenarHoja(e) {
    vaciar(hojaCuerpo);
    const lista = el("ul", "pt-hoja-attrs");
    e.atributos.forEach((a) => {
      const pista = el("span", "pt-pista");
      const relleno = el("i");
      relleno.style.width = `${porcentaje(a.valor, a.maximo || 1)}%`;
      con(pista, relleno);
      con(lista, con(el("li"),
        con(el("div", "pt-hoja-fila"),
          el("span", "pt-hoja-nombre", `${a.icono} ${a.nombre}`),
          el("b", null, `${a.valor}${a.maximo ? ` / ${a.maximo}` : ""}`)),
        pista,
        a.descripcion ? el("p", null, a.descripcion) : null));
    });
    const bonus = e.atributos[0] && e.atributos[0].bonus_por_punto;
    con(hojaCuerpo,
      lista,
      el("p", "pt-hoja-nota", bonus
        ? `🎲 Cada punto suma +${bonus} % a la probabilidad de éxito de las opciones que usan ese atributo.`
        : "🎲 Cada punto sube la probabilidad de éxito de las opciones que usan ese atributo."));
    if (e.puntos_atributo > 0) {
      con(hojaCuerpo, el("p", "pt-hoja-nota pt-hoja-oro",
        `✨ Tienes ${e.puntos_atributo} punto${e.puntos_atributo === 1 ? "" : "s"} por asignar al terminar el evento.`));
    }
    const maximo = e.nivel >= e.nivel_maximo;
    con(hojaCuerpo, con(el("dl", "pt-hoja-resumen"),
      con(el("div"), el("dt", null, "❤ Vidas"), el("dd", null, `${e.hp} / ${e.hp_max}`)),
      con(el("div"), el("dt", null, "⭐ Nivel"), el("dd", null,
        maximo ? `${e.nivel} · máximo` : `${e.nivel} · ${e.xp_en_nivel} / ${e.xp_por_nivel} XP`)),
      con(el("div"), el("dt", null, "📖 Historia"), el("dd", null,
        `${e.evento_numero}/${e.evento_total} · ${e.progreso} %`))));
  }

  function abrirHoja() {
    if (!estadoHoja || !hojaVelo) return;
    llenarHoja(estadoHoja);
    focoAntesHoja = document.activeElement;
    hojaVelo.hidden = false;
    hudStats.setAttribute("aria-expanded", "true");
    document.documentElement.classList.add("pt-hoja-abierta");
    requestAnimationFrame(() => hojaVelo.classList.add("abierta"));
    hojaVelo.querySelector(".pt-hoja").focus();
  }

  function cerrarHoja() {
    if (!hojaVelo || hojaVelo.hidden) return;
    hojaVelo.classList.remove("abierta");
    hudStats.setAttribute("aria-expanded", "false");
    document.documentElement.classList.remove("pt-hoja-abierta");
    setTimeout(() => { hojaVelo.hidden = true; }, sinMovimiento() ? 0 : 220);
    if (focoAntesHoja && focoAntesHoja.focus) focoAntesHoja.focus();
  }

  if (hudStats && hojaVelo) {
    hudStats.setAttribute("aria-expanded", "false");
    hudStats.addEventListener("click", abrirHoja);
    // En celular, tocar las vidas o el nivel también abre la hoja
    [hudVidas, hudXp].forEach((n) => n.addEventListener("click", () => {
      if (window.matchMedia("(max-width: 820px)").matches) abrirHoja();
    }));
    document.getElementById("pt-hoja-cerrar").addEventListener("click", cerrarHoja);
    hojaVelo.addEventListener("click", (ev) => { if (ev.target === hojaVelo) cerrarHoja(); });
    document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") cerrarHoja(); });
  }

  // Pie de página del libro: atributos (RF-05) a la izquierda y número de página
  function pie(n, izquierda) {
    return con(el("div", "pt-pie"), izquierda || el("span"), numeroPagina(n));
  }

  function atributosPie(e) {
    const fila = el("span", "pt-pie-attr");
    e.atributos.forEach((a) => con(fila, con(el("span"), document.createTextNode(`${a.icono} ${a.nombre} `), el("b", null, String(a.valor)))));
    if (e.puntos_atributo > 0) con(fila, sello(`✨ ${e.puntos_atributo} por asignar`, "pt-stamp-oro"));
    return fila;
  }

  function atajos(n) {
    const fila = el("span", "pt-atajos");
    con(fila, document.createTextNode("Elige con "));
    LETRAS.slice(0, n).split("").forEach((l) => con(fila, el("kbd", null, l)));
    return fila;
  }

  function tarjeta(medallon, texto, sellos) {
    const boton = el("button", "choice");
    boton.type = "button";
    const cuerpo = con(el("div"), el("p", "pt-opcion", texto));
    if (sellos && sellos.length) {
      const fila = el("div");
      sellos.forEach((s) => con(fila, s));
      con(cuerpo, fila);
    }
    return con(boton, el("span", "pt-letra" + (medallon.length > 1 ? " pt-icono" : ""), medallon), cuerpo);
  }

  // Al reactivar, las tarjetas de atributos que ya están al máximo siguen bloqueadas
  function desactivar(botones, si) { botones.forEach((b) => { b.disabled = si || b.dataset.lleno === "1"; }); }

  // Sello de goma entintado (como los de oficina): doble anillo, texto en curva y una
  // palomita o tache al centro. La textura de tinta sale de un filtro SVG.
  function selloDeTinta(ok) {
    const caja = document.createElement("div");
    caja.className = "pt-sello " + (ok ? "ok" : "mal");
    caja.setAttribute("aria-hidden", "true");
    const centro = ok
      ? '<path d="M38 61 L53 76 L83 44" fill="none" stroke="currentColor" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>'
      : '<path d="M43 43 L77 77 M77 43 L43 77" fill="none" stroke="currentColor" stroke-width="10" stroke-linecap="round"/>';
    caja.innerHTML = `
      <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <filter id="pt-tinta" x="-10%" y="-10%" width="120%" height="120%">
            <feTurbulence type="fractalNoise" baseFrequency="0.32" numOctaves="3" seed="${ok ? 3 : 8}" result="ruido"/>
            <feColorMatrix in="ruido" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -1.7 1.62" result="motas"/>
            <feComposite in="SourceGraphic" in2="motas" operator="in" result="entintado"/>
            <feTurbulence type="fractalNoise" baseFrequency="0.05" numOctaves="1" seed="2" result="onda"/>
            <feDisplacementMap in="entintado" in2="onda" scale="1.6"/>
          </filter>
          <path id="pt-arco-sup" d="M 20 60 A 40 40 0 0 1 100 60"/>
          <path id="pt-arco-inf" d="M 11 60 A 49 49 0 0 0 109 60"/>
        </defs>
        <g filter="url(#pt-tinta)" fill="currentColor">
          <circle cx="60" cy="60" r="56" fill="none" stroke="currentColor" stroke-width="4.5"/>
          <circle cx="60" cy="60" r="50.5" fill="none" stroke="currentColor" stroke-width="1.8"/>
          <circle cx="60" cy="60" r="35" fill="none" stroke="currentColor" stroke-width="3"/>
          <text font-family="Cinzel, Georgia, serif" font-weight="900" font-size="12.5" letter-spacing="2" text-anchor="middle" stroke="currentColor" stroke-width="0.5">
            <textPath href="#pt-arco-sup" startOffset="50%">DECISIÓN</textPath>
          </text>
          <text font-family="Cinzel, Georgia, serif" font-weight="900" font-size="12.5" letter-spacing="2" text-anchor="middle" stroke="currentColor" stroke-width="0.5">
            <textPath href="#pt-arco-inf" startOffset="50%">${ok ? "CORRECTA" : "ERRÓNEA"}</textPath>
          </text>
          <text x="14.5" y="64.5" font-size="11" text-anchor="middle">★</text>
          <text x="105.5" y="64.5" font-size="11" text-anchor="middle">★</text>
          ${centro}
        </g>
      </svg>`;
    return caja;
  }

  // El libro se cierra (FE1): la página izquierda gira sobre el lomo y queda la portada.
  const PORTADA = `
    <svg viewBox="0 0 120 80" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g fill="none" stroke="#e8b94f" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="34,14 8,40 34,66"/><line x1="72" y1="6" x2="48" y2="74"/><polyline points="86,14 112,40 86,66"/>
      </g>
    </svg>`;

  function copiaDePagina(pagina) {
    const copia = pagina.cloneNode(true);
    copia.removeAttribute("id");
    copia.querySelectorAll("[id]").forEach((n) => n.removeAttribute("id"));
    const hoja = el("div", "pt-cl-hoja");
    hoja.appendChild(copia);
    return hoja;
  }

  async function cerrarLibro() {
    const libroReal = document.getElementById("main-book");
    if (!libroReal || sinMovimiento() || !libroReal.animate) return;
    const r = libroReal.getBoundingClientRect();
    const capa = el("div", "pt-cierre");
    const velo = el("div", "pt-cierre-velo");

    if (window.innerWidth <= 820) {
      // En celular las páginas van una sobre otra: el libro solo se apaga
      con(document.body, con(capa, velo));
      libroReal.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "scale(.92)" }],
        { duration: 700, easing: "ease-in", fill: "forwards" });
      await velo.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 800, fill: "forwards" }).finished;
      return;
    }

    const libro = el("div", "pt-cl-libro");
    Object.assign(libro.style, { left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px" });
    const derecha = con(el("div", "pt-cl-mitad"), copiaDePagina(der));
    const sombra = el("div", "pt-cl-sombra");
    con(derecha, sombra);
    const frente = con(el("div", "pt-cl-cara frente"), copiaDePagina(izq));
    const dorso = el("div", "pt-cl-cara dorso");
    dorso.innerHTML = PORTADA;
    const tapa = con(el("div", "pt-cl-tapa"), frente, dorso);
    con(document.body, con(capa, velo, con(libro, derecha, tapa)));
    libroReal.style.visibility = "hidden";

    // 1) La mitad izquierda gira sobre el lomo y cae encima de la derecha
    const giro = { duration: 1300, easing: "cubic-bezier(.55,.05,.3,1)", fill: "forwards" };
    tapa.animate([{ transform: "rotateY(0deg)" }, { transform: "rotateY(180deg)" }], giro);
    await sombra.animate([{ opacity: 0 }, { opacity: 1, offset: 0.85 }, { opacity: 0.2 }], giro).finished;
    // 2) El libro cerrado se centra, se encoge un poco y la escena se apaga
    libro.animate([{ transform: "none" }, { transform: `translateX(${-r.width / 4}px) scale(.9)` }],
      { duration: 800, easing: "ease-in-out", fill: "forwards" });
    await new Promise((res) => setTimeout(res, 650));
    await velo.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 650, easing: "ease-in", fill: "forwards" }).finished;
  }

  function sinMovimiento() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
      document.documentElement.dataset.movimiento === "reducido";
  }

  // ------------------------------------------------------------ fases
  // Flujo normal paso 1 (y FA2.1): situación, estado del jugador y opciones.
  // CU07: la temática de la partida (RN04). La cubierta del libro toma su color y el evento
  // lleva un sello con su nombre; con la Clásica no cambia nada.
  function aplicarTematica(e) {
    const libro = document.getElementById("main-book");
    const t = e.tematica;
    if (!libro || !t) return;
    libro.dataset.tematica = t.id;
    if (t.color) libro.style.setProperty("--c7-portada", t.color);
  }

  function marcaTematica(e) {
    const t = e.tematica;
    if (!t || t.id === "clasica") return null;
    return con(el("div", "c7-tematica-tag"), sello(`${t.icono} Temática ${t.nombre}`, "pt-stamp-oro"));
  }

  function pintarEvento(e) {
    const ev = e.evento;
    const probabilidad = ev.tipo === "probabilidad";
    const historia = el("p", "story", ev.contexto);
    resaltar(historia, e); // RF-39
    con(
      izq,
      el("div", "chapter-label", `${ev.tema} · ${ev.subtema}`),
      el("h1", "chapter-title", ev.titulo),
      ornamento(),
      marcaTematica(e), // CU07
      historia,
      tec ? tec.tira(e.tecnicismos, e.tecnicismos_nuevos, e.bitacora) : null, // RF-40, aviso de RF-41 y bitácora
      pie(e.evento_numero * 2 - 1, atributosPie(e))
    );

    const lista = el("div", "choices");
    const botones = [];
    ev.opciones.forEach((op, i) => {
      const sellos = probabilidad
        ? [sello(`🎲 ${op.probabilidad}%`), sello(`${op.atributo_icono} ${op.atributo_nombre} ${op.valor_atributo}`, "pt-stamp-oro")]
        : [];
      const boton = tarjeta(LETRAS[i], op.texto, sellos);
      resaltar(boton.querySelector(".pt-opcion"), e, false); // dentro de un botón: solo color
      boton.setAttribute("aria-label", `Opción ${LETRAS[i]}: ${op.texto}` + (probabilidad ? `, probabilidad ${op.probabilidad}%` : ""));
      boton.addEventListener("click", () => { letraElegida = LETRAS[i]; elegir(op.id, boton, botones); });
      botones.push(boton);
      con(lista, boton);
    });
    opcionesActuales = botones;

    con(
      der,
      el("div", "chapter-label", "Tu decisión"),
      con(el("div", "pt-decide-cab"),
        el("h2", "choose-title", "¿Qué decides?"),
        con(el("div", "pt-tipo"), sello(probabilidad ? "🎲 Prueba de atributos" : "🔎 Decisión de análisis"))),
      el("p", "choose-sub", probabilidad ? "Tu probabilidad depende de tus atributos." : "Analiza la situación y elige con criterio."),
      lista,
      pie(e.evento_numero * 2, atajos(botones.length))
    );
  }

  // Flujo normal paso 2: el usuario elige; el servidor resuelve y se estampa el sello
  // verde (correcta) o rojo (errónea) sobre la opción antes de pasar la página.
  async function elegir(opcionId, boton, botones) {
    desactivar(botones, true);
    boton.classList.add("selected");
    try {
      const estado = await llamar("decision/", { opcion_id: opcionId });
      const acierto = estado.resultado && estado.resultado.acierto;
      boton.classList.add(acierto ? "sello-ok" : "sello-mal", "golpe");
      if (boton.parentNode) boton.parentNode.classList.add("pt-decidido"); // las demás se apagan
      boton.appendChild(selloDeTinta(acierto));
      sonar(acierto ? "sello" : "sello-mal");
      boton.setAttribute("aria-label", (acierto ? "Correcta: " : "Errónea: ") + boton.getAttribute("aria-label"));
      await new Promise((res) => setTimeout(res, sinMovimiento() ? 400 : 1000));
      pintar(estado);
    } catch (err) {
      mostrarAviso(err.message);
      boton.classList.remove("selected");
      desactivar(botones, false);
    }
  }

  // Flujo normal pasos 3-6 (y FA2.2-2.3): retroalimentación, indicadores, desenlace y botón.
  function pintarResultado(e) {
    const r = e.resultado;
    const desenlace = el("p", "story", r.desenlace);
    resaltar(desenlace, e);

    const cambios = el("div", "pt-cambios");
    if (r.cambios.hp) con(cambios, sello(`❤️ ${r.cambios.hp} vida`, "pt-stamp-mal"));
    if (r.cambios.xp) con(cambios, sello(`⭐ +${r.cambios.xp} XP`, "pt-stamp-oro"));
    if (r.cambios.puntos) con(cambios, sello(`🏆 +${r.cambios.puntos}`, "pt-stamp-oro"));
    if (r.cambios.puntos_atributo) con(cambios, sello(`✨ +${r.cambios.puntos_atributo} punto de atributo`, "pt-stamp-oro"));

    con(
      izq,
      el("div", "chapter-label", "Lo que pasó"),
      el("h1", "chapter-title", r.evento_titulo),
      el("p", "pt-tema", `${r.tema} · ${r.subtema}`),
      desenlace,
      pie(e.evento_numero * 2 - 1, cambios.childNodes.length ? cambios : null)
    );

    const eleccion = con(el("div", "pt-eleccion"),
      el("span", "pt-eleccion-tit", letraElegida ? `Elegiste ${letraElegida}` : "Elegiste"),
      el("span", "pt-eleccion-txt", r.opcion.texto));
    const retro = el("p", "pt-retro", r.retroalimentacion);
    resaltar([eleccion.lastChild, retro], e); // RF-39 también en la retroalimentación

    const termino = r.estado_final !== "en_curso";
    const boton = el("button", "book-btn go", termino ? "Ver el final ➔" : "Pasar la página ➔");
    boton.type = "button";
    boton.addEventListener("click", async () => {
      boton.disabled = true;
      try {
        pintar(await llamar("continuar/", {}));
      } catch (err) {
        mostrarAviso(err.message);
        boton.disabled = false;
      }
    });

    con(
      der,
      el("div", "chapter-label", "Retroalimentación técnica"),
      el("p", `pt-veredicto ${r.acierto ? "ok" : "mal"}`, r.acierto ? "✔ Decisión acertada" : "✘ Decisión errónea"),
      eleccion,
      retro
    );
    if (r.riesgo) {
      con(
        der,
        con(
          el("div", "pt-riesgo"),
          el("b", null, `🎲 ${r.riesgo.atributo} · probabilidad ${r.riesgo.probabilidad}% · riesgo ${r.riesgo.nivel}`),
          el("span", null, `Salió ${r.riesgo.tirada} de 100: ${r.acierto ? "éxito" : "fallo"}. ${r.riesgo.mensaje}`)
        )
      );
    }
    con(der, con(el("div", "pt-pie"), numeroPagina(e.evento_numero * 2), boton));
    boton.focus({ preventScroll: true });
  }

  // Mejora de atributos: la XP acumulada se convierte en puntos (estilo Life in Adventure).
  function pintarMejora(e) {
    con(
      izq,
      el("div", "chapter-label", `Capítulo ${e.bloque.capitulo} · ${e.bloque.nombre}`),
      el("h1", "chapter-title", `¡Subes al nivel ${e.nivel}!`),
      ornamento(),
      el("p", "story", "Cada acierto te dio experiencia, y la experiencia se convierte en talento. Antes de seguir, elige qué atributo quieres fortalecer (máximo 10): las pruebas de probabilidad que vienen dependen de él."),
      pie(e.evento_numero * 2 - 1, atributosPie(e))
    );
    const lista = el("div", "choices");
    const botones = [];
    e.atributos.forEach((a) => {
      const lleno = a.valor >= a.maximo;
      const boton = tarjeta(a.icono, a.nombre, [
        sello(lleno ? `${a.valor}/${a.maximo} · al máximo` : `${a.valor} ➔ ${a.valor + 1}`, "pt-stamp-oro"),
      ]);
      boton.dataset.lleno = lleno ? "1" : "";
      boton.addEventListener("click", async () => {
        desactivar(botones, true);
        boton.classList.add("selected");
        try {
          pintar(await llamar("mejorar/", { atributo: a.id }));
        } catch (err) {
          mostrarAviso(err.message);
          boton.classList.remove("selected");
          desactivar(botones, false);
        }
      });
      botones.push(boton);
      con(lista, boton);
    });
    desactivar(botones, false);
    opcionesActuales = botones;
    con(
      der,
      el("div", "chapter-label", "Subes de nivel"),
      el("h2", "choose-title", "Elige tu atributo"),
      el("p", "choose-sub", `Puntos disponibles: ${e.puntos_atributo}`),
      lista,
      pie(e.evento_numero * 2)
    );
  }

  // ------------------------------------------------------------ dibujo general
  // En celular (páginas una sobre otra) se usa la entrada suave de libro.css
  function pasarPagina() {
    spread.classList.remove("active");
    void spread.offsetWidth; // reinicia la animación turnPage de libro.css
    spread.classList.add("active");
  }

  // En pantalla ancha la hoja derecha gira de verdad sobre el lomo: por delante lleva la
  // página que se va y por detrás la nueva página izquierda, donde cae al terminar el giro.
  function prepararHoja() {
    if (sinMovimiento() || window.innerWidth <= 820 || !document.body.animate) return null;
    const r = der.getBoundingClientRect();
    if (!r.width) return null;
    const capa = el("div", "pt-hoja");
    capa.setAttribute("aria-hidden", "true");
    Object.assign(capa.style, {
      left: `${r.left + window.scrollX}px`, top: `${r.top + window.scrollY}px`,
      width: `${r.width}px`, height: `${r.height}px`,
    });
    const giro = el("div", "pt-hoja-giro");
    const frente = con(el("div", "pt-hoja-cara frente"), copiaDePagina(der));
    const dorso = el("div", "pt-hoja-cara dorso");
    const sombra = el("div", "pt-hoja-sombra");
    con(document.body, con(capa, con(giro, frente, dorso), sombra));
    return { capa, giro, dorso, sombra };
  }

  function voltearHoja(h) {
    // El libro puede cambiar de alto con la página nueva: la hoja se acomoda donde quedó
    const r = der.getBoundingClientRect();
    Object.assign(h.capa.style, {
      left: `${r.left + window.scrollX}px`, top: `${r.top + window.scrollY}px`,
      width: `${r.width}px`, height: `${r.height}px`,
    });
    h.dorso.appendChild(copiaDePagina(izq));
    izq.style.visibility = "hidden"; // aparece cuando la hoja cae encima
    sonar("pagina");
    const ritmo = { duration: 650, easing: "cubic-bezier(.45,.05,.25,1)", fill: "forwards" };
    h.sombra.animate([{ opacity: 0 }, { opacity: 0.55, offset: 0.5 }, { opacity: 0 }], ritmo);
    h.giro.animate([{ transform: "rotateY(0deg)" }, { transform: "rotateY(-180deg)" }], ritmo).finished
      .catch(() => {})
      .then(() => { izq.style.visibility = ""; h.capa.remove(); });
  }

  function pintar(e, animar = true) {
    respaldar(e);
    if (tec) tec.cerrar(false); // un globo abierto no sobrevive a pasar la página
    if (e.fase === "fin") {
      terminar(e); // FA1 / FE1: pantalla Post Game
      return;
    }
    const hoja = animar ? prepararHoja() : null;
    opcionesActuales = [];
    vaciar(izq);
    vaciar(der);
    aplicarTematica(e); // CU07
    listonCap.textContent = e.bloque.capitulo;
    hud(e);
    if (e.fase === "resultado") pintarResultado(e);
    else if (e.fase === "mejora") pintarMejora(e);
    else pintarEvento(e);
    if (hoja) voltearHoja(hoja);
    else if (animar) { pasarPagina(); sonar("pagina"); }
    if (animar) window.scrollTo({ top: 0, behavior: sinMovimiento() ? "auto" : "smooth" });
    if (vidas) vidas.sincronizar(e); // CU06: retoma la ronda o muestra la sugerencia (FA1)
    previo = {
      hp: e.hp, hp_max: e.hp_max, xp: e.xp, nivel: e.nivel,
      xp_en_nivel: e.xp_en_nivel, xp_por_nivel: e.xp_por_nivel, progreso: e.progreso,
    };
  }

  // Atajos de teclado: A, B, C, D (o 1-4) eligen la opción. Enter ya pasa la página porque
  // ese botón recibe el foco. No hacen nada si hay una ventana abierta encima o se está escribiendo.
  let opcionesActuales = [];
  let letraElegida = "";
  document.addEventListener("keydown", (ev) => {
    if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.repeat) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
    const abierta = [...document.querySelectorAll('[aria-modal="true"], [role="dialog"]')]
      .some((d) => !d.hidden && d.offsetParent !== null);
    if (abierta) return;
    const k = ev.key.toUpperCase();
    const i = LETRAS.indexOf(k) >= 0 ? LETRAS.indexOf(k) : "1234".indexOf(ev.key);
    const boton = i >= 0 ? opcionesActuales[i] : null;
    if (boton && !boton.disabled) { ev.preventDefault(); boton.focus({ preventScroll: true }); boton.click(); }
  });

  // Al terminar: si perdió, el libro se cierra; en ambos casos el Post Game abre sin
  // pantalla de carga (ver post_game.html).
  async function terminar(e) {
    try { sessionStorage.setItem("trCierre", "1"); } catch (err) { /* sin almacenamiento */ }
    if (e.estado === "derrota") await cerrarLibro();
    window.location.href = e.url_fin;
  }

  function pintarSinConexion(mensaje) {
    vaciar(izq);
    vaciar(der);
    const respaldo = leerRespaldo();
    con(izq, el("div", "chapter-label", "SIN CONEXIÓN"), el("h1", "chapter-title", "El libro no abre"), ornamento(), el("p", "story", mensaje));
    if (respaldo) {
      con(izq, el("p", "final-note", `Último avance guardado en este dispositivo: ❤️ ${respaldo.hp}/${respaldo.hp_max} · ⭐ ${respaldo.xp} XP · 📖 ${respaldo.progreso}% · 🏆 ${respaldo.puntuacion}`));
    }
    const boton = el("button", "book-btn go", "Reintentar ➔");
    boton.type = "button";
    boton.addEventListener("click", () => llamar("estado/").then((e) => pintar(e)).catch((err) => mostrarAviso(err.message)));
    con(der, con(el("div", "btn-row"), el("span"), boton));
  }

  // Estado inicial: viene incrustado en la página; si falta, se pide al servidor.
  const inicial = document.getElementById("pt-estado");
  try {
    pintar(JSON.parse(inicial.textContent), false);
  } catch (err) {
    llamar("estado/").then((e) => pintar(e, false)).catch((e) => pintarSinConexion(e.message));
  }
})();
