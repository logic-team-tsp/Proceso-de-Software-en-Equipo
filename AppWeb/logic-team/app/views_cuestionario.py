"""CU05 — Completar cuestionario de tecnicismos.

Menú de modos de juego (RF-51), pantalla del cuestionario y la API JSON que usa
js/cuestionario.js. Las reglas viven en app/services/cuestionario.py y el catálogo en
app/data/tecnicismos.json.
"""

import json

from django.db import DatabaseError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .services import (
    cuestionario,
    escenarios,
    logros,
    minijuego_codigo,
    ordenar,
    tecnicismos,
    tematicas,
)
from .services.continuar import partida_para_continuar


def _cuerpo_json(request):
    try:
        datos = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _error(error, estado=400, **extra):
    return JsonResponse({"error": error, **extra}, status=estado)


def _error_catalogo(exc):
    return _error("El catálogo de tecnicismos tiene errores: " + "; ".join(exc.errores), 500)


# ---------------------------------------------------------------- páginas
@ensure_csrf_cookie
@require_GET
def menu_modos(request):
    """Pasos 1 y 2: «Iniciar juego» muestra «Historia narrativa», «Minijuego de código» (CU04),
    «Cuestionario súbito» y «Ordenar algoritmos» (CU09)."""
    jugador = tecnicismos.jugador_de(request)
    try:
        resumen = cuestionario.resumen_jugador(jugador)
        codigo = minijuego_codigo.resumen_jugador(jugador)
        algoritmos = ordenar.resumen_jugador(jugador)
    except escenarios.CatalogoError as exc:
        return render(request, "partida_error.html", {"errores": exc.errores}, status=500)
    try:  # CU07 paso 1: acceso a la tienda con el saldo a la vista
        tienda = tematicas.resumen_menu(jugador)
    except (tematicas.CatalogoError, DatabaseError):
        tienda = None  # FE6: el botón abre la tienda, que muestra «Reintentar»
    try:  # Sistema visual: el panel «Tu bitácora» muestra el nivel del jugador
        nivel = logros.nivel(jugador)
    except (escenarios.CatalogoError, DatabaseError):
        nivel = None
    return render(
        request,
        "modos.html",
        {
            "resumen": resumen,
            "codigo": codigo,
            "ordenar": algoritmos,
            "tienda": tienda,
            "nivel": nivel,
            # Ideas UX: «Continuar donde te quedaste» y aviso al salir de la partida
            "continuar": partida_para_continuar(request),
            "partida_guardada": request.GET.get("guardada") == "1",
        },
    )


@require_GET
def bitacora(request):
    """Idea UX «Bitácora de tecnicismos»: repasar los tecnicismos descubiertos.

    Muestra, por materia, los que el jugador ya descubrió (definición, ejemplo y el tema donde
    aparecen) y cuántos le faltan, sin revelar cuáles. Lleva al cuestionario si ya se abrió.
    """
    from .models import TecnicismoRegistrado
    from .views_personalizar import MODULOS, TEMAS

    jugador = tecnicismos.jugador_de(request)
    try:
        _, catalogo = tecnicismos.cargar()
        resumen = cuestionario.resumen_jugador(jugador)
    except escenarios.CatalogoError as exc:
        return render(request, "partida_error.html", {"errores": exc.errores}, status=500)

    registros = TecnicismoRegistrado.objects.filter(**jugador.filtro()).order_by("registrado")
    descubiertos = {r.tecnicismo_id: r for r in registros if r.tecnicismo_id in catalogo}
    recientes = [tid for tid in reversed(list(descubiertos))][:3]

    materias = []
    for modulo in MODULOS:
        del_modulo = [
            (tid, t)
            for tid, t in catalogo.items()
            if t.get("subtema", "").split(":")[0] == modulo["id"]
        ]
        if not del_modulo:
            continue
        tarjetas = [
            {
                "id": tid,
                "nombre": t["nombre"],
                "descripcion": t["descripcion"],
                "ejemplo": t.get("escenario_aplicacion", ""),
                "tema": TEMAS.get(t.get("subtema", ""), ""),
                "reciente": tid in recientes,
            }
            for tid, t in del_modulo
            if tid in descubiertos
        ]
        tarjetas.sort(key=lambda x: x["nombre"].lower())
        materias.append(
            {
                "titulo": modulo["titulo"],
                "tarjetas": tarjetas,
                "total": len(del_modulo),
                "faltan": len(del_modulo) - len(tarjetas),
            }
        )
    return render(
        request,
        "bitacora.html",
        {
            "materias": materias,
            "total": len(descubiertos),
            "catalogo": len(catalogo),
            "resumen": resumen,
        },
    )


@ensure_csrf_cookie
@require_GET
def pagina_cuestionario(request):
    """Pasos 7 a 13. js/cuestionario.js pide el cuestionario y dibuja la mesa de trabajo."""
    return render(request, "cuestionario.html")


# ---------------------------------------------------------------- API (js/cuestionario.js)
@require_POST
def api_generar(request):
    """Pasos 4 a 6 (y FA4: cada llamada arma un cuestionario nuevo). FA1 responde 409."""
    try:
        return JsonResponse(cuestionario.crear(tecnicismos.jugador_de(request)))
    except cuestionario.Insuficientes as exc:
        return _error(
            "insuficientes",
            409,
            registrados=exc.registrados,
            necesarios=exc.necesarios,
            mensaje=str(exc),
        )
    except escenarios.CatalogoError as exc:
        return _error_catalogo(exc)


@require_POST
def api_resultado(request):
    """Pasos 10 y 11, y FE1 (sincronizar un resultado pendiente).

    Cuerpo: {"token": "...", "respuestas": [1, 0, 3, ...], "fecha": "ISO-8601",
             "pendiente": false}
    201 si se guardó; 200 si ese cuestionario ya estaba guardado (reintento).
    """
    datos = _cuerpo_json(request)
    jugador = tecnicismos.jugador_de(request)
    try:
        resultado, creado = cuestionario.guardar_resultado(
            jugador,
            datos.get("token"),
            datos.get("respuestas"),
            fecha=datos.get("fecha"),
            pendiente=bool(datos.get("pendiente")),
        )
    except cuestionario.CuestionarioAjeno as exc:
        return _error(str(exc), 403)
    except cuestionario.ResultadoInvalido as exc:
        return _error(str(exc), 400)
    except escenarios.CatalogoError as exc:
        return _error_catalogo(exc)
    if creado:  # CU08: un reintento de FE1 del cuestionario no cuenta dos veces
        perfecto = resultado["aciertos"] == resultado["total"]
        evento = logros.evento_minijuego(
            "cuestionario", True, perfecto=perfecto, aciertos=resultado["aciertos"]
        )
        cu08 = logros.registrar(jugador, [evento])
        if cu08:
            resultado = {**resultado, "cu08": cu08}
    return JsonResponse(resultado, status=201 if creado else 200)
