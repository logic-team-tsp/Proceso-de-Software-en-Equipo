// Pantalla 2 de Personalizar Partida (CU02): elegir los temas y comenzar la aventura.
//  - Paso 4: se marcan los temas que se quieran, de cualquier materia (mínimo 1).
//  - Special Requirement: la hoja de personaje se actualiza en tiempo real.
//  - RN02: no se puede comenzar sin al menos un tema; se muestra un mensaje.
//  - La hoja dice cuántos eventos y cuántos minutos durará la partida con los temas marcados
//    (solo se juegan eventos de esos temas; el servidor manda la tabla de largos).
(function () {
  const form = document.getElementById("form-modulo");
  if (!form) return;

  const grupo = document.getElementById("modulos");
  const temas = Array.from(form.querySelectorAll('input[name="tema"]'));
  const error = document.getElementById("error-modulo");
  const resumen = document.getElementById("prev-modulo");
  const cuenta = document.getElementById("prev-cuenta");
  const MENSAJE_MIN = "Debes seleccionar al menos un tema para continuar.";
  const todos = document.getElementById("todos-temas");

  const marcados = () => temas.filter((t) => t.checked);
  const prevLargo = document.getElementById("prev-largo");
  const datosLargo = document.getElementById("largo-partida");
  const largos = datosLargo ? JSON.parse(datosLargo.textContent) : null;

  // Eventos que durará la partida: la tabla del servidor para la suma de eventos de los temas
  function eventosDe(sel) {
    let normales = 0;
    let probabilidad = 0;
    sel.forEach((t) => {
      const [n, p] = largos.subtemas[t.value] || [0, 0];
      normales += n;
      probabilidad += p;
    });
    return largos.largos[normales + "," + probabilidad] || 0;
  }

  function textoLargo(sel) {
    if (!largos || !sel.length) return "Elige al menos un tema";
    const eventos = eventosDe(sel);
    const [min, max] = largos.minutos;
    const desde = Math.max(1, Math.round(eventos * min));
    const hasta = Math.max(desde, Math.round(eventos * max));
    const tipo = eventos <= 20 ? "corta" : eventos <= 40 ? "media" : "larga";
    return "≈ " + eventos + " eventos · unos " + desde + "–" + hasta + " min (partida " + tipo + ")";
  }

  function ocultarError() {
    error.hidden = true;
    grupo.classList.remove("invalid");
  }

  function mostrarError(texto) {
    error.textContent = texto;
    error.hidden = false;
    grupo.classList.remove("invalid");
    void grupo.offsetWidth; // reinicia la animación
    grupo.classList.add("invalid");
    grupo.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function actualizar() {
    const sel = marcados();
    resumen.textContent = sel.length
      ? sel.map((t) => t.dataset.titulo).join("\n")
      : "Aún no has elegido ninguno";
    cuenta.textContent = String(sel.length);
    if (prevLargo) prevLargo.textContent = textoLargo(sel);
    // Botón "Seleccionar todos": si ya están todos marcados, sirve para quitarlos
    if (todos) {
      const completos = sel.length === temas.length;
      todos.textContent = completos ? "Quitar todos" : "Marcar todos";
      todos.setAttribute("aria-pressed", String(completos));
    }
    // contador por módulo y borde de las tarjetas que tienen algo marcado
    form.querySelectorAll(".modulo-card").forEach((card) => {
      const n = card.querySelectorAll('input[name="tema"]:checked').length;
      card.classList.toggle("con-seleccion", n > 0);
      const total = card.querySelectorAll('input[name="tema"]').length;
      card.querySelector(".contador-modulo").textContent = n ? n + " de " + total : "";
    });
  }

  temas.forEach((t) =>
    t.addEventListener("change", () => {
      ocultarError();
      actualizar();
    })
  );

  if (todos) {
    todos.addEventListener("click", () => {
      const marcar = marcados().length !== temas.length;
      temas.forEach((t) => { t.checked = marcar; });
      ocultarError();
      actualizar();
    });
  }

  form.addEventListener("submit", (e) => {
    if (marcados().length < 1) {
      e.preventDefault();
      mostrarError(MENSAJE_MIN);
      return;
    }
    // Con temas elegidos el formulario se envía normal: el libro ya se abrió en la portada y la
    // partida empieza con su pantalla de carga (frase de ingeniería de software, 2 s).
  });

  // CU07 paso B1: la hoja de personaje muestra la temática elegida
  const prevTematica = document.getElementById("prev-tematica");
  form.querySelectorAll('input[name="tematica"]').forEach((r) =>
    r.addEventListener("change", () => {
      if (!prevTematica || !r.checked) return;
      const card = r.closest(".c7-op-tematica");
      prevTematica.textContent = card.querySelector(".c7-op-nombre").textContent;
    })
  );

  actualizar(); // por si el servidor devolvió temas ya elegidos
})();
