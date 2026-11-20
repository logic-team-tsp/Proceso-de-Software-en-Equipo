// Comportamiento compartido del libro: luciérnagas flotando y entrada del libro.
// Lo carga base.html, así que cualquier página que extienda la base lo tiene.
(function () {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // --- Luciérnagas / polvo dorado ---
  const canvas = document.getElementById("motes");
  if (canvas && !reduceMotion) {
    const ctx = canvas.getContext("2d");
    let W, H, motes = [];

    function initMotes() {
      W = canvas.width = window.innerWidth;
      H = canvas.height = window.innerHeight;
      motes = Array.from({ length: 70 }, () => ({
        x: Math.random() * W,
        y: Math.random() * H,
        r: Math.random() * 2 + 0.6,
        vy: -(Math.random() * 0.25 + 0.05),
        vx: (Math.random() - 0.5) * 0.2,
        phase: Math.random() * Math.PI * 2,
        speed: Math.random() * 0.02 + 0.008,
      }));
    }

    function drawMotes() {
      ctx.clearRect(0, 0, W, H);
      motes.forEach((m) => {
        m.x += m.vx + Math.sin(m.phase) * 0.15;
        m.y += m.vy;
        m.phase += m.speed;
        if (m.y < -10) { m.y = H + 10; m.x = Math.random() * W; }
        const a = 0.25 + 0.45 * (0.5 + 0.5 * Math.sin(m.phase * 3));
        ctx.beginPath();
        ctx.arc(m.x, m.y, m.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 213, 120, ${a})`;
        ctx.shadowBlur = 10;
        ctx.shadowColor = "rgba(255, 190, 80, 0.9)";
        ctx.fill();
      });
      ctx.shadowBlur = 0;
      requestAnimationFrame(drawMotes);
    }

    window.addEventListener("resize", initMotes);
    initMotes();
    drawMotes();
  }

  // --- Pantalla de carga de la partida: una frase al azar de la ingeniería de software ---
  const FRASES = [
    ["La parte más difícil de construir un sistema de software es decidir con precisión qué construir.", "Fred Brooks"],
    ["Cualquier tonto puede escribir código que una computadora entienda. Los buenos programadores escriben código que las personas pueden entender.", "Martin Fowler"],
    ["La simplicidad es requisito previo de la confiabilidad.", "Edsger W. Dijkstra"],
    ["Probar un programa puede mostrar la presencia de errores, pero nunca su ausencia.", "Edsger W. Dijkstra"],
    ["Los programas deben escribirse para que las personas los lean, y solo de paso para que las máquinas los ejecuten.", "Harold Abelson y Gerald Sussman"],
    ["Hazlo funcionar, hazlo correcto, hazlo rápido.", "Kent Beck"],
    ["El código se lee muchas más veces de las que se escribe.", "Guido van Rossum"],
    ["La mejor forma de predecir el futuro es inventarlo.", "Alan Kay"],
  ];
  const frase = document.getElementById("loader-frase");
  const autor = document.getElementById("loader-autor");
  if (frase && autor) {
    const [texto, quien] = FRASES[Math.floor(Math.random() * FRASES.length)];
    frase.textContent = texto;
    autor.textContent = "— " + quien;
  }

  // --- Entrada: la pantalla de carga se queda 2 s y luego se quita ---
  window.addEventListener("load", () => {
    const loader = document.getElementById("loader-overlay");
    const book = document.getElementById("main-book");
    const reducido = reduceMotion || document.documentElement.dataset.movimiento === "reducido";
    const pausa = loader && !reducido ? 2000 : 0;
    setTimeout(() => {
      if (loader) loader.classList.add("hidden");
      if (book) book.classList.add("visible");
    }, pausa);
  });

  // --- Llegada desde la transición "el libro se abre" (ver js/transicion.js) ---
  try {
    if (sessionStorage.getItem("trLlegada")) {
      sessionStorage.removeItem("trLlegada");
      const luz = document.createElement("div");
      luz.className = "tr-llegada";
      document.body.appendChild(luz);
      requestAnimationFrame(() => requestAnimationFrame(() => luz.classList.add("fuera")));
      setTimeout(() => luz.remove(), 700);
    }
  } catch (e) { /* sin almacenamiento: no pasa nada */ }
})();
