"""CU08 — Obtener logros.

API JSON del panel de logros (js/logros.js): pestañas Logros y Finales, ranking personal,
informe de una puntuación y el reintento de FE1. El panel está en logros_panel.html, que se
incluye en todas las pantallas (igual que el engranaje de CU03). Las reglas viven en
app/services/logros.py y el catálogo en app/data/logros.json.

Los logros se desbloquean desde las vistas de la partida (CU01, CU06) y de los minijuegos
(CU04, CU05, CU09): cada una llama a logros.registrar() y agrega a su respuesta el bloque
"cu08" con los logros nuevos.
"""

import json

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .models import Puntuacion
from .services import escenarios, logros, tecnicismos


def _error(mensaje, estado=400):
    return JsonResponse({"error": mensaje}, status=estado)


def _consulta(funcion, *args):
    """FE2: si no se pueden leer los logros, el panel muestra «Reintentar» (500)."""
    try:
        return JsonResponse(funcion(*args))
    except escenarios.CatalogoError as exc:
        return _error("Los logros tienen errores de contenido: " + "; ".join(exc.errores), 500)
    except DatabaseError:
        return _error("No se pudieron cargar tus logros.", 500)


@require_GET
def api_resumen(request):
    """Pasos 11 y 12, FA6: progreso, logros por categoría y finales por historia."""
    return _consulta(logros.resumen, tecnicismos.jugador_de(request))


@require_GET
def api_nivel(request):
    """Nivel y título del jugador para el botón de Logros (se pide al cargar cada pantalla)."""
    return _consulta(logros.nivel, tecnicismos.jugador_de(request))


@require_GET
def api_ranking(request):
    """Paso 13 y FA7. ?historia=<materia> filtra; sin ella es la clasificación general."""
    historia = request.GET.get("historia") or None
    return _consulta(logros.ranking, tecnicismos.jugador_de(request), historia)


@require_GET
def api_informe(request, puntuacion_id):
    """Paso 14: desglose y logros de una puntuación del ranking."""
    try:
        return _consulta(logros.informe, tecnicismos.jugador_de(request), puntuacion_id)
    except (Puntuacion.DoesNotExist, ValidationError):
        return _error("Esa puntuación no existe.", 404)


@require_POST
def api_reintentar(request):
    """FE1: vuelve a guardar el progreso que no se pudo guardar. Cuerpo: {"pendiente": "..."}."""
    try:
        datos = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        datos = {}
    token = datos.get("pendiente") if isinstance(datos, dict) else None
    try:
        resultado = logros.reintentar(tecnicismos.jugador_de(request), token)
    except ValueError as exc:
        return _error(str(exc), 400)
    return JsonResponse({"cu08": resultado})
