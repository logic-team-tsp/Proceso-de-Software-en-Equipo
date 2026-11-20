// Sistema visual (mockups): cambia los emojis del texto por iconos de línea (css/iconos.css).
// El HTML del servidor no cambia (las pruebas y los lectores de pantalla siguen viendo el texto);
// aquí solo se sustituye lo que se pinta. Las flechas de texto (← → ↑ ↓) se quedan como están.
//
// Para pintar un icono a mano: <span class="ic ic-libro" aria-hidden="true"></span>
// Para que un trozo no se toque: data-sin-iconos en el elemento o un ancestro.
(function () {
  "use strict";

  const MAPA = {
    "❤️": "corazon",
    "⚠️": "alerta",
    "⚔️": "espadas",
    "🛡️": "escudo",
    "⛩️": "torii",
    "★": "estrella",
    "⭐": "estrella",
    "☆": "estrella-vacia",
    "➔": "flecha",
    "⬅": "flecha-izq",
    "✔": "palomita",
    "✓": "palomita",
    "✘": "cruz",
    "✕": "cruz",
    "☠": "cruz",
    "❤": "corazon",
    "💗": "corazon",
    "♡": "corazon-vacio",
    "💔": "corazon-roto",
    "🩹": "corazon-mas",
    "🔒": "candado",
    "🏆": "trofeo",
    "🎲": "dado",
    "📖": "libro",
    "📕": "libro",
    "📘": "libro",
    "🔎": "lupa",
    "📜": "pergamino",
    "⚠": "alerta",
    "🧩": "codigo",
    "🐍": "codigo",
    "🏅": "medalla",
    "🎖": "medalla",
    "💯": "medalla",
    "💡": "idea",
    "🧠": "idea",
    "📚": "teoria",
    "⚡": "rayo",
    "🎯": "diana",
    "🧭": "brujula",
    "🗝": "llave",
    "✨": "chispa",
    "🐾": "chispa",
    "🔢": "barras",
    "📶": "barras",
    "🏰": "castillo",
    "🔁": "repetir",
    "⚔": "espadas",
    "☑": "casilla",
    "☐": "casilla-vacia",
    "🏁": "bandera",
    "👁": "ojo",
    "🏪": "tienda",
    "🎭": "persona",
    "📝": "pluma",
    "🪶": "pluma",
    "✍": "pluma",
    "❓": "pregunta",
    "🤝": "equipo",
    "💰": "moneda",
    "🪙": "moneda",
    "👑": "corona",
    "📈": "grafica",
    "🛡": "escudo",
    "🌱": "brote",
    "🏛": "columnas",
    "⛩": "torii",
    "🎴": "carta",
    "🔮": "esfera"
  };
  const NO_TOCAR = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, OPTION: 1, CODE: 1, PRE: 1, TITLE: 1, INPUT: 1, SELECT: 1 };
  // Selector de variación (FE0F) que a veces acompaña al emoji
  const VS = "\uFE0F";
  const claves = Object.keys(MAPA).map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const PATRON = new RegExp("(" + claves.join("|") + ")" + VS + "?", "gu");
  const PRUEBA = new RegExp(PATRON.source, "u");

  function icono(nombre, emoji) {
    const s = document.createElement("span");
    s.className = "ic ic-" + nombre;
    s.setAttribute("aria-hidden", "true");
    s.dataset.emoji = emoji;
    return s;
  }

  function saltar(nodo) {
    for (let el = nodo.parentElement; el; el = el.parentElement) {
      if (NO_TOCAR[el.tagName] || el.isContentEditable) return true;
      if (el.hasAttribute && el.hasAttribute("data-sin-iconos")) return true;
      if (el.classList && el.classList.contains("ic")) return true;
    }
    return false;
  }

  function cambiarTexto(nodo) {
    const texto = nodo.nodeValue;
    if (!texto || !PRUEBA.test(texto) || saltar(nodo)) return;
    const frag = document.createDocumentFragment();
    let ultimo = 0;
    PATRON.lastIndex = 0;
    let m;
    while ((m = PATRON.exec(texto))) {
      if (m.index > ultimo) frag.appendChild(document.createTextNode(texto.slice(ultimo, m.index)));
      frag.appendChild(icono(MAPA[m[1]], m[1]));
      ultimo = m.index + m[0].length;
    }
    if (ultimo < texto.length) frag.appendChild(document.createTextNode(texto.slice(ultimo)));
    nodo.parentNode.replaceChild(frag, nodo);
  }

  function recorrer(raiz) {
    if (!raiz) return;
    if (raiz.nodeType === 3) { cambiarTexto(raiz); return; }
    if (raiz.nodeType !== 1 && raiz.nodeType !== 11) return;
    if (raiz.nodeType === 1 && NO_TOCAR[raiz.tagName]) return;
    const w = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
    const nodos = [];
    while (w.nextNode()) nodos.push(w.currentNode);
    nodos.forEach(cambiarTexto);
  }

  // Texto que JS pinta después (eventos de la partida, toasts, paneles): se cambia al llegar
  function vigilar() {
    if (!window.MutationObserver) return;
    new MutationObserver((cambios) => {
      cambios.forEach((c) => {
        if (c.type === "characterData") cambiarTexto(c.target);
        else c.addedNodes.forEach(recorrer);
      });
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function iniciar() {
    recorrer(document.body);
    vigilar();
  }

  window.LTIconos = { aplicar: recorrer, icono: (nombre) => icono(nombre, "") };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
