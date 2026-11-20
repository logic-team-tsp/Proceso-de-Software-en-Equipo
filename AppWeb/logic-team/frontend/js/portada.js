// Portada: encuadre del paisaje y animación de entrada. Al dar «Iniciar juego» (o «Continuar»),
// el libro de la cima vuela al centro, se abre brillando y da paso a la siguiente pantalla
// (js/transicion-libro.js, unos 2 s, siempre). Sin JavaScript los enlaces funcionan igual.
(function () {
  const fondo = document.getElementById("fondo-svg");
  if (!fondo) return;

  // En pantallas verticales se centra el paisaje en el libro
  const LIBRO_X = 480;
  function encuadrar() {
    const aspecto = window.innerWidth / window.innerHeight;
    if (aspecto < 1.2) {
      const ancho = Math.min(1280, 800 * aspecto);
      const x = Math.max(0, Math.min(1280 - ancho, LIBRO_X - ancho / 2));
      fondo.setAttribute("viewBox", `${x.toFixed(1)} 0 ${ancho.toFixed(1)} 800`);
    } else {
      fondo.setAttribute("viewBox", "0 0 1280 800");
    }
  }
  window.addEventListener("resize", encuadrar);
  encuadrar();

  const libro = document.getElementById("libro-cima");
  const escena = document.getElementById("escena");
  document.querySelectorAll("#btn-iniciar, .btn-continuar").forEach((enlace) => {
    enlace.addEventListener("click", (e) => {
      if (!window.TransicionLibro || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      window.TransicionLibro.abrir({ origen: libro, destino: enlace.href, atenuar: escena, ocultar: libro });
    });
  });
})();
