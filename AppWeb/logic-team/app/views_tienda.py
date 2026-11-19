"""CU07 — Comprar nuevos módulos temáticos de partida.

La tienda se abre con 1 clic desde el menú de modos. Pantallas: la tienda con el saldo y el
catálogo (paso 2) y la vista previa en el libro (pasos 3 y 4). js/tienda.js pide la compra a
la API (pasos 5 a 9). Las reglas viven en app/services/tematicas.py y el catálogo en
app/data/tematicas/*.json.
"""

import json
import logging

from django.db import DatabaseError
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .services import escenarios, tecnicismos, tematicas

logger = logging.getLogger(__name__)


def _cuerpo_json(request):
    try:
        datos = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _error(mensaje, estado=400, **extra):
    return JsonResponse({"error": mensaje, **extra}, status=estado)


# ---------------------------------------------------------------- páginas
@ensure_csrf_cookie
@require_GET
def tienda(request):
    """Paso 2: saldo (RN01) y catálogo. FA4, FA5 y FE6 (error al cargar, con «Reintentar»)."""
    try:
        datos = tematicas.tienda(tecnicismos.jugador_de(request))
    except (tematicas.CatalogoError, escenarios.CatalogoError, DatabaseError) as exc:
        logger.error("CU07 no se pudo cargar la tienda: %s", exc)
        return render(request, "tienda.html", {"error_carga": True}, status=503)
    return render(request, "tienda.html", {"tienda": datos})


@ensure_csrf_cookie
@require_GET
def vista(request, tematica_id):
    """Pasos 3 y 4: vista previa en el libro, con el botón de comprar (FA1, FA3)."""
    try:
        datos = tematicas.vista_previa(tecnicismos.jugador_de(request), tematica_id)
    except tematicas.TematicaDesconocida as exc:
        raise Http404("Esa temática no está en la tienda") from exc
    except (tematicas.CatalogoError, escenarios.CatalogoError, DatabaseError) as exc:
        logger.error("CU07 no se pudo cargar la vista previa: %s", exc)
        return render(request, "tienda.html", {"error_carga": True}, status=503)
    datos["urls"] = {
        "comprar": reverse("tienda_comprar"),
        "usar": reverse("tienda_usar", args=[tematica_id]),
        "tienda": reverse("tienda"),
        "codigo": reverse("codigo_inicio"),
        "ordenar": reverse("ordenar_inicio"),
    }
    return render(request, "tienda_vista.html", {"vista": datos, "vista_json": datos_json(datos)})


def datos_json(datos):
    """Lo que js/tienda.js necesita para la confirmación y el resultado de la compra."""
    t = datos["tematica"]
    return {
        "tematica": {k: t[k] for k in ("id", "nombre", "icono", "precio", "estado", "faltan")},
        "saldo": datos["saldo"],
        "urls": datos["urls"],
    }


@require_POST
def usar(request, tematica_id):
    """«Usar en mi próxima partida»: CU02 la muestra ya seleccionada (paso B1)."""
    jugador = tecnicismos.jugador_de(request)
    request.session["tematica_elegida"] = tematicas.para_partida(jugador, tematica_id)
    return redirect("personalizar_perfil")


# ---------------------------------------------------------------- API (js/tienda.js)
@require_POST
def api_comprar(request):
    """Pasos 7 a 9. Cuerpo: {"tematica": "samurai"}.

    201 compra nueva · 200 ya la tenía (FE2: no se cobra otra vez) · 409 no alcanza (FE3 ->
    FA1) · 404 no existe · 500 no se pudo guardar (FE1: no se descontó nada).
    """
    jugador = tecnicismos.jugador_de(request)
    tematica_id = str(_cuerpo_json(request).get("tematica", ""))
    try:
        antes = tematicas.saldo(jugador)["saldo"]
        compra, nueva = tematicas.comprar(jugador, tematica_id)
        despues = tematicas.saldo(jugador)["saldo"]
    except tematicas.TematicaDesconocida:
        return _error("Esa temática no está en la tienda.", 404)
    except tematicas.EstrellasInsuficientes as exc:
        return JsonResponse(
            {
                "error": "insuficientes",
                "faltan": exc.faltan,
                "saldo": exc.saldo,
                "mensaje": f"Tu saldo cambió: te faltan {exc.faltan} ★ para esta temática.",
            },
            status=409,
        )
    except (tematicas.CatalogoError, escenarios.CatalogoError, DatabaseError) as exc:
        logger.error("CU07 no se pudo registrar la compra: %s", exc)
        return _error("No se pudo completar la compra. Inténtalo de nuevo.", 500)
    return JsonResponse(
        {
            "tematica": compra.tematica_id,
            "precio": compra.precio,
            "fecha": compra.fecha.isoformat(),
            "nueva": nueva,
            "saldo_anterior": antes if nueva else despues,
            "saldo": despues,
        },
        status=201 if nueva else 200,
    )
