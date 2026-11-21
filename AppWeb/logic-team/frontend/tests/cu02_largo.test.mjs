// Pruebas de personalizar_modulo.js (CU02, pantalla de temas): la hoja «Tu partida» dice en vivo
// cuántos eventos y minutos durará la partida según los temas marcados.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const raiz = join(dirname(fileURLToPath(import.meta.url)), "..");
const script = readFileSync(join(raiz, "js", "personalizar_modulo.js"), "utf8");

// Lo que manda el servidor (motor_partida.largos_posibles): 8 normales y 5 de probabilidad por tema
const LARGOS = {
  subtemas: { "a:0": [8, 5], "a:1": [8, 5], "b:0": [8, 5] },
  largos: { "0,0": 0, "8,5": 10, "16,10": 20, "24,15": 30 },
  minutos: [1, 1.5],
};

function crear() {
  const temas = Object.keys(LARGOS.subtemas)
    .map((id) => `<input type="checkbox" name="tema" value="${id}" data-titulo="${id}">`)
    .join("");
  const dom = new JSDOM(
    `<!DOCTYPE html><html><body><form id="form-modulo">
      <fieldset id="modulos"><div class="modulo-card"><span class="contador-modulo"></span>${temas}</div></fieldset>
      <span id="prev-cuenta"></span><dd id="prev-modulo"></dd><dd id="prev-largo"></dd>
      <p id="error-modulo" hidden></p><button type="button" id="todos-temas"></button>
      <script type="application/json" id="largo-partida">${JSON.stringify(LARGOS)}</script>
    </form></body></html>`,
    { url: "http://localhost/", runScripts: "outside-only" }
  );
  dom.window.eval(script);
  return dom.window;
}

const marcar = (w, valor) => {
  const caja = w.document.querySelector(`input[value="${valor}"]`);
  caja.checked = !caja.checked;
  caja.dispatchEvent(new w.Event("change", { bubbles: true }));
};
const largo = (w) => w.document.getElementById("prev-largo").textContent;

test("sin temas pide elegir uno", () => {
  assert.equal(largo(crear()), "Elige al menos un tema");
});

test("un tema es una partida corta y crece al marcar más", () => {
  const w = crear();
  marcar(w, "a:0");
  assert.equal(largo(w), "≈ 10 eventos · unos 10–15 min (partida corta)");
  marcar(w, "b:0");
  assert.equal(largo(w), "≈ 20 eventos · unos 20–30 min (partida corta)");
  marcar(w, "a:1");
  assert.equal(largo(w), "≈ 30 eventos · unos 30–45 min (partida media)");
  marcar(w, "a:1");
  assert.equal(largo(w), "≈ 20 eventos · unos 20–30 min (partida corta)");
});

test("marcar todos actualiza la duración", () => {
  const w = crear();
  w.document.getElementById("todos-temas").click();
  assert.equal(largo(w), "≈ 30 eventos · unos 30–45 min (partida media)");
});
