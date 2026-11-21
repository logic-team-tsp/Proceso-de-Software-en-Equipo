// Efectos de sonido cortos (idea UX «Sonidos»): pasar página, sello, pluma, vidas y logros.
// Se sintetizan con Web Audio, así que no hace falta ningún archivo de audio.
// Se apagan con el interruptor «Efectos de sonido» del panel de ajustes (CU03) y usan su volumen.
//
// Uso:  window.LTSonidos && LTSonidos.tocar("pagina");
// Nombres: pagina, sello, sello-mal, pluma, vida-menos, vida-mas, logro, carta,
//          clic, abrir, cerrar, punto
//
// Los botones y enlaces suenan solos con «clic» (ver el final del archivo). Para que uno no
// suene: data-sin-clic en el elemento o un ancestro. Los que abren un panel (aria-haspopup)
// no hacen clic porque el panel ya suena con «abrir».
(function () {
  "use strict";

  let ctx = null;
  const ultimo = {}; // último momento en que sonó cada efecto (para no encimarlos)

  // iPhone: sin esto, el switch de silencio apaga todo el audio de la página (Safari 16.4+)
  try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch (e) {}

  function ajustes() {
    try {
      return window.LTAjustes ? window.LTAjustes.obtener() : { efectos: true, volumen: 40 };
    } catch (e) {
      return { efectos: true, volumen: 40 };
    }
  }

  // El navegador solo deja sonar audio después de que el jugador tocó la página
  function contexto() {
    if (ctx) return ctx;
    const Clase = window.AudioContext || window.webkitAudioContext;
    if (!Clase) return null;
    try { ctx = new Clase(); } catch (e) { ctx = null; }
    return ctx;
  }

  function ruido(c, segundos) {
    const largo = Math.max(1, Math.floor(c.sampleRate * segundos));
    const buffer = c.createBuffer(1, largo, c.sampleRate);
    const datos = buffer.getChannelData(0);
    for (let i = 0; i < largo; i++) datos[i] = Math.random() * 2 - 1;
    const fuente = c.createBufferSource();
    fuente.buffer = buffer;
    return fuente;
  }

  function envolvente(c, salida, pico, ataque, caida, t0) {
    const g = c.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(Math.max(0.0002, pico), t0 + ataque);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + ataque + caida);
    g.connect(salida);
    return g;
  }

  function tono(c, salida, frecuencia, t0, dura, tipo, pico, hasta) {
    const o = c.createOscillator();
    o.type = tipo || "sine";
    o.frequency.setValueAtTime(frecuencia, t0);
    if (hasta) o.frequency.exponentialRampToValueAtTime(hasta, t0 + dura);
    o.connect(envolvente(c, salida, pico, 0.008, dura, t0));
    o.start(t0);
    o.stop(t0 + dura + 0.05);
  }

  const RECETAS = {
    // Hoja de papel: ruido filtrado que barre de agudo a grave
    pagina(c, s, t) {
      const n = ruido(c, 0.32);
      const f = c.createBiquadFilter();
      f.type = "bandpass";
      f.Q.value = 0.9;
      f.frequency.setValueAtTime(4200, t);
      f.frequency.exponentialRampToValueAtTime(900, t + 0.3);
      n.connect(f);
      f.connect(envolvente(c, s, 0.35, 0.04, 0.26, t));
      n.start(t);
    },
    // Sello de goma: golpe grave y un clic seco
    sello(c, s, t) {
      tono(c, s, 150, t, 0.16, "sine", 0.7, 55);
      const n = ruido(c, 0.05);
      const f = c.createBiquadFilter();
      f.type = "highpass";
      f.frequency.value = 1800;
      n.connect(f);
      f.connect(envolvente(c, s, 0.25, 0.002, 0.04, t));
      n.start(t);
    },
    "sello-mal"(c, s, t) {
      RECETAS.sello(c, s, t);
      tono(c, s, 220, t + 0.04, 0.22, "triangle", 0.12, 160);
    },
    // Pluma que raspa el papel: tres trazos cortos de ruido agudo
    pluma(c, s, t) {
      [0, 0.09, 0.2].forEach((d, i) => {
        const n = ruido(c, 0.08);
        const f = c.createBiquadFilter();
        f.type = "highpass";
        f.frequency.value = 3500 + i * 600;
        n.connect(f);
        f.connect(envolvente(c, s, 0.12, 0.01, 0.07, t + d));
        n.start(t + d);
      });
    },
    "vida-menos"(c, s, t) {
      tono(c, s, 440, t, 0.14, "triangle", 0.22);
      tono(c, s, 330, t + 0.13, 0.22, "triangle", 0.22);
    },
    "vida-mas"(c, s, t) {
      tono(c, s, 523, t, 0.12, "triangle", 0.2);
      tono(c, s, 784, t + 0.1, 0.26, "triangle", 0.2);
    },
    // Campanita de tres notas para logros y subir de nivel
    logro(c, s, t) {
      [659, 880, 1319].forEach((f, i) => tono(c, s, f, t + i * 0.08, 0.5, "sine", 0.16));
    },
    // Tic de madera muy corto y bajito: botones, opciones y enlaces
    clic(c, s, t) {
      tono(c, s, 1650, t, 0.035, "sine", 0.09, 900);
      const n = ruido(c, 0.02);
      const f = c.createBiquadFilter();
      f.type = "bandpass";
      f.frequency.value = 3200;
      f.Q.value = 1.4;
      n.connect(f);
      f.connect(envolvente(c, s, 0.05, 0.001, 0.018, t));
      n.start(t);
    },
    // Pergamino que se desenrolla (paneles y hojas) y su versión corta al cerrar
    abrir(c, s, t) {
      const n = ruido(c, 0.2);
      const f = c.createBiquadFilter();
      f.type = "bandpass";
      f.Q.value = 1.1;
      f.frequency.setValueAtTime(900, t);
      f.frequency.exponentialRampToValueAtTime(2600, t + 0.18);
      n.connect(f);
      f.connect(envolvente(c, s, 0.14, 0.03, 0.15, t));
      n.start(t);
    },
    cerrar(c, s, t) {
      const n = ruido(c, 0.12);
      const f = c.createBiquadFilter();
      f.type = "bandpass";
      f.Q.value = 1.1;
      f.frequency.setValueAtTime(2200, t);
      f.frequency.exponentialRampToValueAtTime(800, t + 0.1);
      n.connect(f);
      f.connect(envolvente(c, s, 0.09, 0.015, 0.09, t));
      n.start(t);
    },
    // Punto de atributo: dos notas que suben y un brillo
    punto(c, s, t) {
      tono(c, s, 587, t, 0.1, "triangle", 0.14);
      tono(c, s, 880, t + 0.07, 0.16, "triangle", 0.14);
      tono(c, s, 1760, t + 0.14, 0.25, "sine", 0.05);
    },
    carta(c, s, t) {
      const n = ruido(c, 0.06);
      const f = c.createBiquadFilter();
      f.type = "bandpass";
      f.frequency.value = 2500;
      n.connect(f);
      f.connect(envolvente(c, s, 0.18, 0.005, 0.05, t));
      n.start(t);
    },
  };

  function tocar(nombre) {
    const a = ajustes();
    if (a.efectos === false || !RECETAS[nombre]) return;
    // Si se toca muy rápido, el mismo efecto no se repite encima de sí mismo
    const ahora = performance.now();
    if (ahora - (ultimo[nombre] || 0) < 70) return;
    ultimo[nombre] = ahora;
    const volumen = (Number(a.volumen) || 0) / 100;
    if (volumen <= 0) return;
    const c = contexto();
    if (!c) return;
    if (c.state === "suspended") c.resume().catch(() => {});
    try {
      const salida = c.createGain();
      salida.gain.value = 0.9 * volumen;
      salida.connect(c.destination);
      RECETAS[nombre](c, salida, c.currentTime + 0.01);
    } catch (e) {
      /* un navegador sin Web Audio completo: el juego sigue sin sonido */
    }
  }

  window.LTSonidos = { tocar };

  // Clic satisfactorio en todo lo que se toca. Se escucha en pointerdown para que suene al
  // instante (sin el retraso del click) y en Enter/Espacio para quien juega con teclado.
  const TOCABLES = 'button, a[href], [role="button"], summary, label, .choice, input[type="checkbox"], input[type="radio"]';
  function alTocar(ev) {
    const t = ev.target.closest && ev.target.closest(TOCABLES);
    if (!t || t.disabled || t.getAttribute("aria-disabled") === "true") return;
    if (t.closest("[data-sin-clic]") || t.hasAttribute("aria-haspopup")) return;
    tocar("clic");
    // Android: un toque háptico casi imperceptible (el iPhone no lo permite desde la web)
    if (ev.type === "pointerdown" && ev.pointerType === "touch" && navigator.vibrate) {
      try { navigator.vibrate(8); } catch (e) {}
    }
  }
  document.addEventListener("pointerdown", (ev) => { if (ev.button === 0) alTocar(ev); }, true);
  document.addEventListener("keydown", (ev) => {
    if ((ev.key === "Enter" || ev.key === " ") && !ev.repeat) alTocar(ev);
  }, true);
})();
