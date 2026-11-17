// CU09 - Ordenar algoritmos. Se abre desde el menú de modos.
// El libro tiene dos páginas: primero la explicación del algoritmo (paso 2); con «Empezar» el
// servidor genera la lista y aparece la mesa de trabajo (pasos 3 a 6). El jugador hace el
// siguiente movimiento del algoritmo: intercambiar dos tarjetas (burbuja y selección), meter una
// tarjeta en su lugar (inserción) o «Ya está en su lugar». El servidor revisa cada movimiento
// (services/ordenar.py); aquí solo se dibuja, se anima y se muestran los avisos.
// Usa los estilos del libro (libro.css) y ordenar.css (.c9-*).
(function () {
  "use strict";

  const libro = document.getElementById("main-book");
  const rutas = libro.dataset;
  const izq = document.getElementById("or-izq");
  const der = document.getElementById("or-der");
  const velo = document.getElementById("or-velo");
  const inicial = JSON.parse(document.getElementById("or-estado").textContent);
  const nivel = inicial.nivel;
  const alg = inicial.algoritmo;
  const urls = inicial.urls;
  const CON_YA = nivel.algoritmo !== "burbuja"; // selección e inserción tienen «Ya está en su lugar»
  const INSERCION = nivel.algoritmo === "insercion";
  const ARTICULO = { burbuja: "la burbuja", seleccion: "la selección", insercion: "la inserción" }[nivel.algoritmo];

  const s = {
    estado: inicial.estado,
    mesa: inicial.mesa, // lista, ordenadas, turno, indicacion, linea, contadores, paso
    juego: inicial.juego,
    resultado: inicial.resultado,
    tomada: null, // índice de la tarjeta elegida
    marcas: {}, // índice -> "mal" | "comp"
    aviso: null, // {tipo, titulo, texto}
    ocupado: false,
    foco: null, // índice de la tarjeta que tenía el foco
    arrastre: null,
  };

  function reducido() {
    return document.documentElement.dataset.movimiento === "reducido" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  // ------------------------------------------------------------ utilidades
  function el(etiqueta, clase, texto) {
    const nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined && texto !== null) nodo.textContent = texto;
    return nodo;
  }

  function con(padre, ...hijos) {
    hijos.forEach((hijo) => {
      if (hijo === null || hijo === undefined || hijo === false) return;
      padre.appendChild(typeof hijo === "string" ? document.createTextNode(hijo) : hijo);
    });
    return padre;
  }

  function vaciar(nodo) { while (nodo.firstChild) nodo.removeChild(nodo.firstChild); }

  function boton(clase, texto, alHacerClic) {
    const b = el("button", clase, texto);
    b.type = "button";
    if (alHacerClic) b.addEventListener("click", alHacerClic);
    return b;
  }

  function enlace(clase, texto, url) {
    const a = el("a", clase, texto);
    a.href = url;
    return a;
  }

  function cookie(nombre) {
    const m = document.cookie.match(new RegExp(`(?:^|; )${nombre}=([^;]*)`));
    return m ? decodeURIComponent(m[1]) : "";
  }

  async function llamar(url, cuerpo) {
    let respuesta;
    try {
      respuesta = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": cookie("csrftoken"),
        },
        body: JSON.stringify(cuerpo || {}),
      });
    } catch (e) {
      throw new Error("No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.");
    }
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(datos.error || "No se pudo completar la acción.");
    return datos.ordenar;
  }

  // Línea de pseudocódigo con **palabras clave** (vienen así de algoritmos.json)
  function lineaCodigo(texto) {
    const li = el("li");
    texto.split("**").forEach((parte, i) => con(li, i % 2 ? el("span", "kw", parte) : parte));
    return li;
  }

  function pseudocodigo(actual) {
    const ol = el("ol", "c9-pseudo");
    ol.setAttribute("aria-label", "Pseudocódigo");
    alg.pseudocodigo.forEach((t, i) => {
      const li = lineaCodigo(t);
      if (i === actual) {
        li.className = "actual";
        li.setAttribute("aria-current", "true");
      }
      con(ol, li);
    });
    return ol;
  }

  function estrellasTexto(n, max) {
    const caja = el("span", "c9-est");
    caja.setAttribute("aria-label", `${n} de ${max} estrellas`);
    for (let i = 0; i < max; i++) con(caja, i < n ? "★" : el("span", "off", "☆"));
    return caja;
  }

  function cabecera(pagina, etiqueta, titulo) {
    vaciar(pagina);
    con(pagina, el("div", "chapter-label", etiqueta), el("h1", "chapter-title", titulo), el("div", "ornament"));
    pagina.lastChild.setAttribute("aria-hidden", "true");
  }

  // Avance de niveles: ✔ resueltos, el que se juega y 🔒 los que faltan (RN07)
  function avance() {
    const ol = el("ol", "c9-niveles");
    ol.setAttribute("aria-label", "Avance de niveles");
    s.juego.niveles.forEach((n) => {
      const viendo = n.numero === nivel.numero && s.estado !== "resuelto";
      const clase = n.estado === "hecho" ? "hecho" : (n.estado === "actual" || viendo ? "actual" : "bloq");
      const marca = n.estado === "hecho" ? "✔" : (clase === "actual" ? String(n.numero) : "🔒");
      const li = con(el("li", clase), el("span", "m", marca), n.nombre);
      const texto = { hecho: `resuelto con ${n.estrellas} estrellas`, actual: "el que se juega", bloq: "todavía no" }[clase];
      li.setAttribute("aria-label", `Nivel ${n.numero}, ${n.nombre}: ${texto}`);
      if (clase === "actual") li.setAttribute("aria-current", "step");
      con(ol, li);
    });
    return ol;
  }

  function sello(texto, oro) { return el("span", `stamp${oro ? " c9-oro" : ""}`, texto); }

  // ------------------------------------------------------------ ventanas (¿Cómo funciona? y Salir)
  let alCerrar = null;

  function abrirVentana(contenido, ancho, cerrar) {
    vaciar(velo);
    const ventana = con(el("div", `c9-dialogo${ancho ? " ancho" : ""}`), ...contenido);
    ventana.setAttribute("role", "dialog");
    ventana.setAttribute("aria-modal", "true");
    const titulo = ventana.querySelector("h2");
    if (titulo) {
      titulo.id = "or-ventana-titulo";
      ventana.setAttribute("aria-labelledby", titulo.id);
    }
    con(velo, ventana);
    velo.hidden = false;
    alCerrar = cerrar || null;
    const principal = ventana.querySelector(".book-btn.go") || ventana.querySelector("button");
    if (principal) principal.focus();
  }

  function cerrarVentana() {
    velo.hidden = true;
    vaciar(velo);
    const fin = alCerrar;
    alCerrar = null;
    if (fin) fin();
  }

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !velo.hidden) cerrarVentana();
  });

  // Ejemplo corto: se ilumina un paso a la vez (con movimiento reducido se ven todos)
  let reloj = null;
  function ejemplo() {
    const caja = el("div", "c9-ejemplo");
    con(caja, con(el("div", "cab"), el("span", null, "Ejemplo"), el("span", null, reducido() ? "paso a paso" : "▶ animado")));
    const pasos = alg.ejemplo.map((p) => {
      const mini = el("div", "c9-mini");
      p.lista.forEach((x, i) => {
        const clase = (p.comp || []).includes(i) ? "comp" : ((p.ord || []).includes(i) ? "ord" : "");
        con(mini, el("span", clase, String(x)));
      });
      return con(caja, con(el("div", "c9-paso-ej"), mini, el("span", null, p.texto))).lastChild;
    });
    if (!reducido()) {
      let i = 0;
      caja.classList.add("animado");
      const avanzar = () => {
        pasos.forEach((p, j) => p.classList.toggle("activo", j === i));
        i = (i + 1) % pasos.length;
      };
      avanzar();
      if (reloj) clearInterval(reloj);
      reloj = setInterval(() => (caja.isConnected ? avanzar() : clearInterval(reloj)), 1600);
    }
    return caja;
  }

  // FA2: volver a ver la explicación sin perder el avance
  function comoFunciona() {
    if (!velo.hidden) return;
    const listo = boton("book-btn go", "Seguir ordenando", cerrarVentana);
    abrirVentana(
      [
        el("h2", null, `¿Cómo funciona ${ARTICULO}?`),
        el("p", null, alg.explicacion),
        ejemplo(),
        pseudocodigo(-1),
        el("p", "c9-como", alg.como_se_juega),
        con(el("div", "btn-row"), listo),
      ],
      true,
      () => document.getElementById("or-como")?.focus({ preventScroll: true })
    );
  }

  // FA4: abandonar
  function confirmarSalida() {
    if (!velo.hidden || s.estado !== "en_curso") return;
    const quedarse = boton("book-btn", "Seguir ordenando", cerrarVentana);
    const salir = boton("book-btn go", "Sí, salir", async () => {
      salir.disabled = quedarse.disabled = true;
      try {
        const datos = await llamar(rutas.salir);
        window.location.href = datos.url;
      } catch (err) {
        cerrarVentana();
        avisar("mal", "No se pudo salir", err.message);
      }
    });
    abrirVentana(
      [
        el("h2", null, "¿Salir de Ordenar algoritmos?"),
        con(el("p"), "Se perderá el avance de este nivel y ", el("b", null, "no ganarás XP"), ". Al volver empezarás el nivel con una lista nueva."),
        con(el("div", "btn-row"), quedarse, salir),
      ],
      false,
      () => document.getElementById("or-salir")?.focus({ preventScroll: true })
    );
    quedarse.focus();
  }

  // ------------------------------------------------------------ paso 2: explicación
  function pintarExplicacion() {
    cabecera(izq, `ORDENAR ALGORITMOS · NIVEL ${nivel.numero}`, nivel.nombre);
    con(izq, avance(), el("p", "story", alg.explicacion), ejemplo());

    vaciar(der);
    const empezar = boton("book-btn go", "Empezar ➔", empezarNivel);
    empezar.id = "or-empezar";
    con(
      der,
      el("h2", "choose-title", "Pseudocódigo"),
      el("p", "choose-sub", `Así piensa ${ARTICULO}`),
      pseudocodigo(-1),
      con(el("p", "c9-como"), el("b", null, "Cómo se juega: "), alg.como_se_juega),
      con(el("div", "stamps"), sello(`🃏 ${nivel.numeros} números`), sello("⬆ De menor a mayor"), sello(`⭐ ${nivel.xp_base} XP base`, true)),
      el("p", "c9-msg-lugar"),
      con(el("div", "btn-row"), enlace("book-btn", "⬅ Menú", urls.menu), empezar)
    );
    empezar.focus({ preventScroll: true });
  }

  async function empezarNivel(ev) {
    const b = ev.currentTarget;
    b.disabled = true;
    try {
      const estado = await llamar(rutas.empezar);
      s.mesa = estado.mesa;
      s.juego = estado.juego;
      pintarMesa();
      enfocarTarjeta(0);
    } catch (err) {
      b.disabled = false;
      const lugar = der.querySelector(".c9-msg-lugar");
      vaciar(lugar);
      con(lugar, mensaje({ tipo: "mal", titulo: "No se pudo empezar", texto: err.message }));
    }
  }

  // ------------------------------------------------------------ pasos 3 a 6: mesa de trabajo
  function mensaje(a) {
    const caja = el("div", `c9-msg ${a.tipo}`);
    caja.setAttribute("role", a.tipo === "mal" ? "alert" : "status");
    const ico = { mal: "✘", info: "ℹ️", ok: "✔", pista: "💡" }[a.tipo] || "ℹ️";
    con(caja, el("span", "ico", ico), con(el("div"), el("b", null, a.titulo), a.texto));
    if (a.tipo === "pista") caja.className = "c9-msg info";
    return caja;
  }

  function avisar(tipo, titulo, texto) {
    s.aviso = { tipo, titulo, texto };
    pintarMesa();
  }

  function contadores() {
    const c = s.mesa.contadores;
    const caja = el("div", "c9-contadores");
    [["Comparaciones", c.comparaciones, ""], ["Intercambios", c.intercambios, ""], ["Errores", c.errores, " err"]].forEach(([t, v, extra]) => {
      con(caja, con(el("div", `c9-cont${extra}`), el("b", null, String(v)), el("span", null, t)));
    });
    caja.setAttribute("aria-live", "polite");
    return caja;
  }

  function claseTarjeta(i) {
    const m = s.mesa;
    if (s.marcas[i]) return s.marcas[i];
    if (s.tomada === i) return "tomada";
    if (m.ordenadas.includes(i)) return "ord";
    if (m.turno === i && CON_YA) return "turno";
    return "";
  }

  const INSIGNIA = { ord: "✔", tomada: "↕", comp: "👁", mal: "✘", turno: "▼" };
  const NOMBRE_ESTADO = { ord: "ya ordenada", tomada: "elegida", comp: "comparando", mal: "movimiento incorrecto", turno: "toca acomodar" };

  function tarjeta(valor, i) {
    const clase = claseTarjeta(i);
    const b = boton(`c9-carta${clase ? " " + clase : ""}`, String(valor), () => elegir(i));
    b.dataset.i = i;
    b.dataset.lugar = i + 1;
    b.dataset.valor = valor;
    if (clase) con(b, el("span", "c9-b", INSIGNIA[clase]));
    b.lastChild.setAttribute?.("aria-hidden", "true");
    b.setAttribute("aria-label", `${valor}, lugar ${i + 1}${clase ? ", " + NOMBRE_ESTADO[clase] : ""}`);
    b.setAttribute("aria-pressed", s.tomada === i ? "true" : "false");
    b.tabIndex = (s.foco === null ? i === 0 : s.foco === i) ? 0 : -1; // ← → mueven el foco
    b.disabled = s.ocupado || s.estado !== "en_curso";
    b.draggable = !b.disabled;
    b.addEventListener("keydown", (ev) => teclado(ev, i));
    b.addEventListener("dragstart", (ev) => {
      s.arrastre = i;
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", String(i));
    });
    b.addEventListener("dragend", () => { s.arrastre = null; limpiarEncima(); });
    receptor(b, () => soltarSobre(i));
    return b;
  }

  // Inserción: con una tarjeta tomada aparecen huecos para soltarla
  function hueco(k) {
    const b = boton("c9-hueco-btn", null, () => insertarEn(k));
    b.setAttribute("aria-label", k === 0 ? "Meter al principio" : `Meter después del ${s.mesa.lista[k - 1]}`);
    con(b, el("span", null, "▼"));
    b.disabled = s.ocupado;
    receptor(b, () => insertarEn(k));
    return b;
  }

  function receptor(nodo, alSoltar) {
    nodo.addEventListener("dragover", (ev) => {
      if (s.arrastre === null) return;
      ev.preventDefault();
      nodo.classList.add("encima");
    });
    nodo.addEventListener("dragleave", () => nodo.classList.remove("encima"));
    nodo.addEventListener("drop", (ev) => {
      ev.preventDefault();
      nodo.classList.remove("encima");
      alSoltar();
    });
  }

  function limpiarEncima() { der.querySelectorAll(".encima").forEach((n) => n.classList.remove("encima")); }

  function soltarSobre(i) {
    const desde = s.arrastre;
    s.arrastre = null;
    if (desde === null || desde === i) return;
    // Inserción: soltar sobre una tarjeta la mete antes de ella
    if (INSERCION) mover({ tipo: "insertar", desde, hasta: i });
    else mover({ tipo: "intercambiar", a: desde, b: i });
  }

  function mesaTarjetas() {
    const m = s.mesa;
    const caja = el("div", `c9-mesa${INSERCION && s.tomada !== null ? " con-huecos" : ""}`);
    const fila = el("div", "c9-fila");
    fila.setAttribute("role", "group");
    fila.setAttribute("aria-label", "Tarjetas de la lista");
    const huecos = INSERCION && s.tomada !== null && s.estado === "en_curso";
    m.lista.forEach((valor, i) => {
      if (huecos) con(fila, hueco(i));
      con(fila, tarjeta(valor, i));
    });
    if (huecos) con(fila, hueco(m.lista.length));
    return con(caja, fila);
  }

  function leyenda() {
    const caja = el("div", "c9-leyenda");
    const items = [["l-tom", "↕ elegida"], ["l-comp", "👁 comparando"], ["l-ord", "✔ ya ordenada"]];
    if (CON_YA) items.push(["l-turno", "▼ toca acomodar"]);
    items.forEach(([c, t]) => con(caja, con(el("span"), el("i", c), t)));
    caja.setAttribute("aria-hidden", "true");
    return caja;
  }

  function pintarMesa() {
    const m = s.mesa;
    cabecera(izq, `ORDENAR ALGORITMOS · NIVEL ${nivel.numero}`, nivel.nombre);
    con(izq, avance(), pseudocodigo(m.linea), contadores());

    vaciar(der);
    const estado = el("p", "c9-estado");
    const [parte1, ...resto] = m.indicacion.split(" · ");
    con(estado, el("b", null, parte1), resto.length ? ` · ${resto.join(" · ")}` : "");

    const pista = boton("book-btn chico", "💡 Pista", pedirPista);
    const como = boton("book-btn chico", "¿Cómo funciona?", comoFunciona);
    como.id = "or-como";
    const grupo = con(el("div", "grupo"), pista, como);
    let ya = null;
    if (CON_YA) {
      // FA3: en selección e inserción, cuando el número ya está en su lugar
      ya = boton("book-btn go chico", "✔ Ya está en su lugar", () => mover({ tipo: "ya" }));
      ya.id = "or-ya";
    }
    const salir = boton("book-btn chico", "✕ Salir", confirmarSalida);
    salir.id = "or-salir";
    [pista, como, salir, ya].forEach((b) => { if (b) b.disabled = s.ocupado; });

    const ayuda = el("p", "c9-ayuda");
    if (INSERCION) ayuda.textContent = s.tomada === null ? "Haz clic en la tarjeta que vas a meter y luego en el hueco donde va." : "Ahora haz clic en el hueco ▼ donde va la tarjeta (o en ella otra vez para soltarla).";
    else ayuda.textContent = s.tomada === null ? "Haz clic en las dos tarjetas que vas a intercambiar, o arrastra una sobre la otra." : "Ahora haz clic en la otra tarjeta (o en la misma para soltarla).";

    con(
      der,
      el("h2", "choose-title", "Mesa de trabajo"),
      estado,
      s.aviso ? mensaje(s.aviso) : null,
      mesaTarjetas(),
      leyenda(),
      ayuda,
      ya ? con(el("div", "c9-ya"), ya) : null,
      con(el("div", "c9-acciones"), grupo, salir)
    );
  }

  function enfocarTarjeta(i) {
    if (i === null || i === undefined) return;
    const b = der.querySelector(`.c9-carta[data-i="${i}"]`);
    if (b && !b.disabled) b.focus({ preventScroll: true });
  }

  // Teclado: ← → para moverse, Espacio o Enter para elegir (el botón ya lo hace)
  function teclado(ev, i) {
    const n = s.mesa.lista.length;
    let destino = null;
    if (ev.key === "ArrowRight") destino = Math.min(n - 1, i + 1);
    else if (ev.key === "ArrowLeft") destino = Math.max(0, i - 1);
    else if (ev.key === "Home") destino = 0;
    else if (ev.key === "End") destino = n - 1;
    if (destino === null) return;
    ev.preventDefault();
    s.foco = destino;
    der.querySelectorAll(".c9-carta").forEach((b) => { b.tabIndex = Number(b.dataset.i) === destino ? 0 : -1; });
    enfocarTarjeta(destino);
  }

  function elegir(i) {
    if (s.ocupado || s.estado !== "en_curso") return;
    s.foco = i;
    s.marcas = {};
    if (s.tomada === null) {
      s.tomada = i;
      pintarMesa();
      enfocarTarjeta(i);
      return;
    }
    if (s.tomada === i) {
      s.tomada = null;
      pintarMesa();
      enfocarTarjeta(i);
      return;
    }
    const a = s.tomada;
    if (INSERCION) {
      // Clic en otra tarjeta: se mete en su lugar (antes de esa tarjeta)
      mover({ tipo: "insertar", desde: a, hasta: i });
      return;
    }
    mover({ tipo: "intercambiar", a, b: i });
  }

  // Hueco k: entre la tarjeta k-1 y la k. Si se mueve a la derecha, el destino corre uno.
  function insertarEn(k) {
    const desde = s.tomada !== null ? s.tomada : s.arrastre;
    s.arrastre = null;
    if (desde === null) return;
    const hasta = k > desde ? k - 1 : k;
    if (hasta === desde) {
      s.tomada = null;
      pintarMesa();
      return;
    }
    mover({ tipo: "insertar", desde, hasta });
  }

  // Animación: cada tarjeta se desliza de donde estaba a donde quedó (las tarjetas no se repiten)
  function posiciones() {
    const mapa = {};
    der.querySelectorAll(".c9-carta").forEach((b) => { mapa[b.dataset.valor] = b.getBoundingClientRect(); });
    return mapa;
  }

  function animar(antes) {
    if (reducido()) return Promise.resolve();
    const movidas = [];
    der.querySelectorAll(".c9-carta").forEach((b) => {
      const previa = antes[b.dataset.valor];
      if (!previa) return;
      const ahora = b.getBoundingClientRect();
      const dx = previa.left - ahora.left;
      const dy = previa.top - ahora.top;
      if (!dx && !dy) return;
      b.style.transition = "none";
      b.style.transform = `translate(${dx}px, ${dy}px)`;
      movidas.push(b);
    });
    if (!movidas.length) return Promise.resolve();
    return new Promise((listo) => {
      requestAnimationFrame(() => requestAnimationFrame(() => {
        movidas.forEach((b) => {
          b.style.transition = "transform 420ms cubic-bezier(.3,.7,.3,1)";
          b.style.transform = "";
        });
        setTimeout(listo, 440);
      }));
    });
  }

  async function mover(movimiento) {
    if (s.ocupado || s.estado !== "en_curso") return;
    s.ocupado = true;
    const tocadas = movimiento.tipo === "intercambiar" ? [movimiento.a, movimiento.b]
      : movimiento.tipo === "insertar" ? [movimiento.desde] : (s.mesa.turno !== null ? [s.mesa.turno] : []);
    let r;
    try {
      r = await llamar(rutas.mover, { paso: s.mesa.paso, ...movimiento });
    } catch (err) {
      s.ocupado = false;
      s.tomada = null;
      avisar("mal", "No se pudo revisar el movimiento", err.message);
      return;
    }
    s.ocupado = false;
    s.tomada = null;
    s.marcas = {};
    if (r.desfasado) {
      s.mesa = r.mesa;
      s.aviso = null;
      pintarMesa();
      return;
    }
    if (!r.permitido) {
      // FE2: no se aplica y no cuenta como error
      s.aviso = { tipo: "info", titulo: "Movimiento no permitido", texto: r.aviso };
      s.mesa = r.mesa;
      pintarMesa();
      enfocarTarjeta(s.foco);
      return;
    }
    if (!r.aplicado) {
      // FE1: las tarjetas regresan, se marcan en rojo y se explica
      tocadas.forEach((i) => { s.marcas[i] = "mal"; });
      s.mesa = r.mesa;
      s.aviso = {
        tipo: "mal",
        titulo: `Ese no es el movimiento · error ${r.errores_paso} de ${inicial.errores_por_paso} en este paso`,
        texto: r.explicacion,
      };
      pintarMesa();
      enfocarTarjeta(s.foco);
      return;
    }
    const antes = posiciones();
    s.mesa = r.mesa;
    s.aviso = r.mostrado
      ? { tipo: "mal", titulo: `Error ${inicial.errores_por_paso} de ${inicial.errores_por_paso} en este paso: así lo haría el algoritmo`, texto: `${r.explicacion} Este nivel ya solo puede darte 1 estrella.` }
      : null;
    if (r.mostrado) {
      const m = r.movimiento;
      const nuevas = m.tipo === "intercambiar" ? [m.a, m.b] : m.tipo === "insertar" ? [m.hasta] : [m.i];
      nuevas.forEach((i) => { s.marcas[i] = "comp"; });
    }
    pintarMesa();
    await animar(antes);
    if (r.terminado) {
      s.estado = "resuelto";
      s.resultado = r.resultado;
      s.juego = r.juego;
      setTimeout(pintarResultado, reducido() ? 0 : 450);
      return;
    }
    enfocarTarjeta(s.foco);
  }

  // FA1: pista
  async function pedirPista() {
    if (s.ocupado) return;
    s.ocupado = true;
    let r;
    try {
      r = await llamar(rutas.pista);
    } catch (err) {
      s.ocupado = false;
      avisar("mal", "No se pudo dar la pista", err.message);
      return;
    }
    s.ocupado = false;
    s.tomada = null;
    s.mesa = r.mesa;
    s.marcas = {};
    r.comparando.forEach((i) => { s.marcas[i] = "comp"; });
    s.aviso = { tipo: "pista", titulo: "Pista", texto: `${r.texto} (Cuenta como un error.)` };
    pintarMesa();
  }

  // ------------------------------------------------------------ pasos 7 a 9: resumen del nivel
  function fila(k, v, clase) {
    return con(el("div", `sheet-row${clase ? " " + clase : ""}`), el("span", "k", k), el("span", "v", v));
  }

  function pintarResultado() {
    const r = s.resultado;
    const j = s.juego;
    const textoEstrellas = r.mostrado
      ? "El sistema tuvo que mostrarte un paso, así que el nivel da 1 estrella."
      : r.errores === 0 ? "¡Sin errores! Ordenaste la lista como lo haría el algoritmo." : `Ordenaste la lista con ${r.errores} ${r.errores === 1 ? "error" : "errores"}.`;

    cabecera(izq, `ORDENAR ALGORITMOS · NIVEL ${nivel.numero}`, "¡Lista ordenada!");
    const estrellas = el("p", "c9-estrellas");
    estrellas.setAttribute("aria-label", `${r.estrellas} de ${r.estrellas_max} estrellas`);
    for (let i = 0; i < r.estrellas_max; i++) con(estrellas, i < r.estrellas ? "★" : el("span", "off", "★"));
    const mini = el("div", "c9-mini final");
    (r.lista || s.mesa.lista).forEach((x) => con(mini, el("span", "ord", String(x))));
    const errores = r.pistas ? `${r.errores} (${r.errores - r.pistas} ${r.errores - r.pistas === 1 ? "movimiento" : "movimientos"} · ${r.pistas} ${r.pistas === 1 ? "pista" : "pistas"})` : String(r.errores);
    con(
      izq,
      estrellas,
      el("p", "c9-estrellas-txt", textoEstrellas),
      mini,
      con(el("div", "sheet"),
        fila(`Comparaciones de ${ARTICULO}`, String(r.comparaciones)),
        fila(`Intercambios de ${ARTICULO}`, String(r.intercambios)),
        fila("Tus errores", errores))
    );

    vaciar(der);
    const descuento = r.xp_base - r.xp;
    const botones = el("div", "btn-row");
    con(botones, enlace("book-btn", "⬅ Volver al menú", urls.menu));
    if (j.completo) con(botones, boton("book-btn go", "Ver resumen del juego ➔", pintarFin));
    else con(botones, enlace("book-btn go", "Siguiente nivel ➔", urls.niveles[j.siguiente]));
    con(
      der,
      el("h2", "choose-title", "Experiencia ganada"),
      el("p", "choose-sub", "Cómo se calculó tu XP"),
      con(el("div", "sheet"),
        fila(`XP base del nivel ${nivel.numero}`, `${r.xp_nivel} XP`),
        fila(`${r.estrellas} ${r.estrellas === 1 ? "estrella" : "estrellas"} (${r.porcentaje_xp}%)`, `${r.xp_base} XP`),
        r.errores ? fila(`${r.errores} ${r.errores === 1 ? "error" : "errores"} × ${inicial.penalizacion_por_error}%`, `−${r.penalizacion}% (−${descuento} XP)`) : null,
        fila("XP ganada", `+${r.xp} XP`, "total")),
      el("p", "c9-xp", `+${r.xp} XP`),
      avance(),
      con(el("div", "stamps"), sello("✔ Guardado en tu historial", true)),
      botones
    );
    der.querySelector(".book-btn.go")?.focus({ preventScroll: true });
  }

  // FA5: terminar los 3 niveles
  function pintarFin() {
    const j = s.juego;
    document.getElementById("or-ribbon").innerHTML = "FIN<b>✔</b>";
    cabecera(izq, "ORDENAR ALGORITMOS", "¡Terminaste Ordenar algoritmos!");
    const tabla = el("div", "sheet c9-tabla-niv");
    j.niveles.forEach((n) => {
      const v = con(el("span", "v"), estrellasTexto(n.estrellas, 3), ` · ${n.xp} XP`);
      con(tabla, con(el("div", "sheet-row"), el("span", "k", `${n.numero} · ${n.nombre}`), v));
    });
    con(tabla, fila("Total", `${j.estrellas} de ${j.estrellas_max} ★ · ${j.xp} XP`, "total"));
    con(izq, tabla, con(el("div", "stamps"), sello("✔ Guardado en tu historial", true)));

    vaciar(der);
    const g = j.grafica;
    const mayor = Math.max(1, ...g.algoritmos.flatMap((a) => [a.comparaciones, a.intercambios]));
    const mini = el("div", "c9-mini final");
    g.lista.forEach((x) => con(mini, el("span", null, String(x))));
    const graf = el("div", "c9-graf");
    graf.setAttribute("role", "img");
    graf.setAttribute("aria-label", g.algoritmos.map((a) => `${a.nombre}: ${a.comparaciones} comparaciones y ${a.intercambios} intercambios`).join("; "));
    g.algoritmos.forEach((a) => {
      const barra = (clase, valor) => {
        const i = el("i");
        i.style.width = `${Math.round((valor / mayor) * 100)}%`;
        return con(el("div", `c9-bar ${clase}`), con(el("span", "pista"), i), el("em", null, String(valor)));
      };
      con(graf, con(el("div", "c9-alg"), el("b", null, a.nombre), barra("c", a.comparaciones), barra("s", a.intercambios)));
    });
    const menosComp = g.algoritmos.reduce((x, y) => (y.comparaciones < x.comparaciones ? y : x));
    const menosInt = g.algoritmos.reduce((x, y) => (y.intercambios < x.intercambios ? y : x));
    con(
      der,
      el("h2", "choose-title", "¿Cuál trabajó menos?"),
      el("p", "choose-sub", `Los ${g.algoritmos.length} algoritmos con la lista del nivel ${j.niveles.length}`),
      mini,
      con(el("div", "c9-graf-ley"), con(el("span"), el("i", "c"), "Comparaciones"), con(el("span"), el("i", "s"), "Intercambios")),
      graf,
      el("p", "c9-ayuda centrada", `${menosComp.nombre} hizo menos comparaciones; ${menosInt.nombre}, menos intercambios.`),
      con(el("div", "btn-row"), enlace("book-btn", "⬅ Volver al menú", urls.menu), enlace("book-btn go", "↻ Volver a jugar", urls.inicio))
    );
    der.querySelector(".book-btn.go")?.focus({ preventScroll: true });
  }

  // ------------------------------------------------------------ inicio
  if (s.estado === "resuelto" && s.resultado) pintarResultado();
  else if (s.mesa) pintarMesa(); // FA6: al recargar sigue en el mismo paso
  else pintarExplicacion();
})();
