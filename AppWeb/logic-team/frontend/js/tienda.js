// CU07 Comprar nuevos módulos temáticos de partida: pasos 5 a 9 de la vista previa.
//  - Paso 5-6: «Comprar» abre la confirmación con el precio y el saldo que quedará.
//  - FA2: «Cancelar» (o Esc) cierra la confirmación sin enviar nada.
//  - Paso 7-8: «Confirmar» se deshabilita mientras el servidor valida y registra la compra.
//  - Paso 9: «¡Temática desbloqueada!» con el saldo actualizado.
//  - FE1: si no se pudo guardar, no se descontó nada; se avisa para intentar de nuevo.
//  - FE2: un doble clic manda una sola petición; si el servidor ya la tenía, no cobra otra vez.
//  - FE3: si el saldo cambió (otra pestaña), queda como FA1 con las estrellas que faltan.
(function () {
  "use strict";

  const datosEl = document.getElementById("c7-datos");
  if (!datosEl) return;
  const datos = JSON.parse(datosEl.textContent);
  const comprar = document.getElementById("c7-comprar");
  const confirmar = document.getElementById("c7-confirmar");
  const confirmarBtn = document.getElementById("c7-confirmar-btn");
  const cancelar = document.getElementById("c7-cancelar");
  const listo = document.getElementById("c7-listo");
  const avisos = document.getElementById("c7-avisos");
  let enviando = false;
  let abiertoDesde = null;

  function cookie(nombre) {
    const par = document.cookie.split("; ").find((c) => c.startsWith(nombre + "="));
    return par ? decodeURIComponent(par.split("=")[1]) : "";
  }

  function texto(id, valor) {
    const el = document.getElementById(id);
    if (el) el.textContent = valor;
  }

  function aviso(clase, titulo, mensaje) {
    avisos.textContent = "";
    if (!titulo) return;
    const caja = document.createElement("div");
    caja.className = "c7-banner " + clase;
    const ico = document.createElement("span");
    ico.className = "ico";
    ico.setAttribute("aria-hidden", "true");
    ico.textContent = clase === "error" ? "⚠️" : "ℹ️";
    const cuerpo = document.createElement("div");
    cuerpo.className = "txt";
    const b = document.createElement("b");
    b.textContent = titulo;
    cuerpo.append(b, mensaje);
    caja.append(ico, cuerpo);
    avisos.append(caja);
  }

  // ------------------------------------------------------------ diálogos
  function enfocables(velo) {
    return [...velo.querySelectorAll("button:not([disabled]), a[href]")];
  }

  function abrir(velo) {
    abiertoDesde = document.activeElement;
    velo.hidden = false;
    const lista = enfocables(velo);
    (lista[lista.length - 1] || lista[0]).focus();
  }

  function cerrar(velo) {
    velo.hidden = true;
    if (abiertoDesde && document.body.contains(abiertoDesde)) abiertoDesde.focus();
  }

  document.addEventListener("keydown", (ev) => {
    const velo = [confirmar, listo].find((v) => v && !v.hidden);
    if (!velo) return;
    if (ev.key === "Escape" && velo === confirmar && !enviando) cerrar(confirmar); // FA2
    if (ev.key === "Tab") {
      const lista = enfocables(velo);
      if (!lista.length) return;
      const primero = lista[0];
      const ultimo = lista[lista.length - 1];
      if (ev.shiftKey && document.activeElement === primero) { ev.preventDefault(); ultimo.focus(); }
      else if (!ev.shiftKey && document.activeElement === ultimo) { ev.preventDefault(); primero.focus(); }
    }
  });

  // ------------------------------------------------------------ FA1 (también después de FE3)
  function faltanEstrellas(faltan, saldo) {
    texto("c7-saldo", "★ " + saldo);
    texto("c7-saldo-top", "★ " + saldo);
    texto("c7-faltan", String(faltan));
    const falta = document.getElementById("c7-falta");
    if (falta) falta.hidden = false;
    if (comprar) {
      comprar.disabled = true;
      comprar.textContent = "🔒 Comprar por " + datos.tematica.precio + " ★";
    }
  }

  // ------------------------------------------------------------ pasos 5 a 9
  if (comprar) {
    comprar.addEventListener("click", () => {
      if (comprar.disabled) return;
      aviso("", "");
      abrir(confirmar);
    });
  }
  if (cancelar) cancelar.addEventListener("click", () => cerrar(confirmar)); // FA2
  if (confirmar) {
    confirmar.addEventListener("click", (ev) => {
      if (ev.target === confirmar && !enviando) cerrar(confirmar);
    });
  }

  async function enviarCompra() {
    if (enviando) return; // FE2: un doble clic no manda dos compras
    enviando = true;
    confirmarBtn.disabled = true;
    cancelar.disabled = true;
    confirmarBtn.textContent = "Comprando…";
    let respuesta = null;
    let cuerpo = {};
    try {
      respuesta = await fetch(datos.urls.comprar, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": cookie("csrftoken") },
        body: JSON.stringify({ tematica: datos.tematica.id }),
      });
      cuerpo = await respuesta.json().catch(() => ({}));
    } catch (err) {
      respuesta = null;
    }
    enviando = false;
    confirmarBtn.disabled = false;
    cancelar.disabled = false;
    confirmarBtn.textContent = "Confirmar compra";

    if (respuesta && (respuesta.status === 201 || respuesta.status === 200)) {
      // Paso 9 (y FE2: si ya la tenía, el servidor no cobró otra vez)
      confirmar.hidden = true;
      texto("c7-listo-antes", "★ " + cuerpo.saldo_anterior);
      texto("c7-listo-saldo", "★ " + cuerpo.saldo);
      texto("c7-saldo-top", "★ " + cuerpo.saldo);
      texto("c7-saldo", "★ " + cuerpo.saldo);
      const sello = document.getElementById("c7-sello");
      if (sello) sello.hidden = false;
      if (comprar) {
        comprar.disabled = true;
        comprar.textContent = "✔ Adquirida";
      }
      abrir(listo);
      return;
    }
    cerrar(confirmar);
    if (respuesta && respuesta.status === 409) {
      // FE3: el saldo ya no alcanza -> FA1
      faltanEstrellas(cuerpo.faltan, cuerpo.saldo);
      aviso("error", "Tu saldo cambió", " " + (cuerpo.mensaje || "Ya no te alcanza para esta temática."));
      return;
    }
    // FE1: la compra se guarda completa o no se guarda; no se descontó nada
    aviso("error", "No se pudo completar la compra", " Inténtalo de nuevo. No se descontó ninguna estrella.");
  }

  if (confirmarBtn) confirmarBtn.addEventListener("click", enviarCompra);
})();
