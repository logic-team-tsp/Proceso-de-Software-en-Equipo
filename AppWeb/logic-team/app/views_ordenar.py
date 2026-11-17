"""CU09 — Ordenar algoritmos.

Se abre desde el menú de modos («Ordenar algoritmos»). Página del libro donde se ve la
explicación del algoritmo y luego la mesa de trabajo con las tarjetas, más la API JSON que usa
js/ordenar.js. Las reglas viven en app/services/ordenar.py y el contenido en
app/data/algoritmos.json y config_juego.json > ordenar_algoritmos.
"""

import json
import os

from django.contrib.staticfiles import finders
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import IntentoOrdenar
from .services import escenarios, ordenar, tecnicismos
from .services.ordenar import FueraDeOrden, MovimientoInvalido, ReglaOrdenar


def _cuerpo_json(request):
    try:
        datos = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _error(mensaje, estado=400):
    return JsonResponse({"error": mensaje}, status=estado)


def _pagina_error(request, exc):
    return render(request, "partida_error.html", {"errores": exc.errores}, status=500)


ARCHIVOS = ("js/ordenar.js", "css/ordenar.css")


def _version_archivos():
    """Cambia cada vez que se modifica el JS o el CSS (?v= en la plantilla), como en CU04."""
    rutas = [finders.find(archivo) for archivo in ARCHIVOS]
    return max((int(os.path.getmtime(r)) for r in rutas if r), default=0)


def _enlaces(estado):
    """Direcciones para seguir: siguiente nivel, volver a jugar y el menú."""
    estado["urls"] = {
        "inicio": reverse("ordenar_inicio"),
        "menu": reverse("menu_modos"),
        "niveles": {
            n["numero"]: reverse("ordenar_mesa", args=[n["numero"]])
            for n in estado["juego"]["niveles"]
        },
    }
    return estado


# ---------------------------------------------------------------- páginas
@require_GET
def inicio(request):
    """Paso 1: «Ordenar algoritmos» en el menú abre el nivel que sigue (FA5: o un juego nuevo)."""
    try:
        numero = ordenar.inicio(tecnicismos.jugador_de(request))
    except escenarios.CatalogoError as exc:
        return _pagina_error(request, exc)
    return redirect("ordenar_mesa", numero=numero)


@ensure_csrf_cookie
@require_GET
def mesa(request, numero):
    """Pasos 2 a 9: explicación y mesa de trabajo. Los niveles van en orden (FE4)."""
    try:
        intento = ordenar.iniciar(tecnicismos.jugador_de(request), numero)
        estado = _enlaces(ordenar.estado_publico(intento))
    except FueraDeOrden as exc:
        return redirect("ordenar_mesa", numero=exc.numero)
    except ReglaOrdenar as exc:
        raise Http404(str(exc)) from exc
    except escenarios.CatalogoError as exc:
        return _pagina_error(request, exc)
    return render(request, "ordenar.html", {"estado": estado, "version": _version_archivos()})


# ---------------------------------------------------------------- API (js/ordenar.js)
def _accion(request, intento_id, funcion, con_datos=False):
    """Cada petición bloquea el intento (select_for_update) dentro de una transacción."""
    try:
        with transaction.atomic():
            jugador = tecnicismos.jugador_de(request)
            consulta = IntentoOrdenar.objects.select_for_update().filter(**jugador.filtro())
            intento = get_object_or_404(consulta, pk=intento_id)
            argumentos = [_cuerpo_json(request)] if con_datos else []
            resultado = funcion(intento, *argumentos)
        return JsonResponse({"ordenar": resultado})
    except MovimientoInvalido as exc:
        return _error(str(exc), 400)
    except ReglaOrdenar as exc:
        return _error(str(exc), 409)
    except escenarios.CatalogoError as exc:
        return _error("El modo tiene errores de contenido: " + "; ".join(exc.errores), 500)


@require_POST
def api_empezar(request, intento_id):
    """Paso 3: «Empezar» genera la lista al azar (RN06)."""
    return _accion(request, intento_id, lambda i: _enlaces(ordenar.empezar(i)))


@require_POST
def api_mover(request, intento_id):
    """Pasos 4 a 8, FA3, FE1 a FE3. Cuerpo: {"paso", "tipo", "a", "b"} o {"desde", "hasta"}."""
    return _accion(request, intento_id, ordenar.mover, con_datos=True)


@require_POST
def api_pista(request, intento_id):
    """FA1: pista que cuenta como error (RN02)."""
    return _accion(request, intento_id, ordenar.pista)


def _salir(intento):
    ordenar.salir(intento)
    return {"url": reverse("menu_modos")}


@require_POST
def api_salir(request, intento_id):
    """FA4: abandona el nivel sin XP y regresa al menú de modos."""
    return _accion(request, intento_id, _salir)
