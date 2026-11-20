"""«Continuar donde te quedaste»: la última partida a medias del jugador.

CU02 guarda en la sesión el id de la partida que creó (``partida_actual``). Si esa partida
sigue en curso, la portada y el menú de modos ofrecen retomarla. El progreso vive en el
servidor, así que salir del libro nunca pierde nada.
"""

from django.core.exceptions import ValidationError
from django.urls import reverse

from ..models import Partida


def partida_para_continuar(request):
    """Datos para el botón «Continuar», o ``None`` si no hay partida a medias."""
    partida_id = request.session.get("partida_actual")
    if not partida_id:
        return None
    try:
        partida = Partida.objects.filter(pk=partida_id).first()
    except (ValueError, ValidationError):  # id mal formado en la sesión
        return None
    if partida is None:
        return None
    if partida.usuario_id and partida.usuario_id != getattr(request.user, "id", None):
        return None
    if partida.estado != Partida.EN_CURSO and partida.resultado_pendiente is None:
        return None
    total = len(partida.secuencia) or 1
    evento = min(partida.indice + 1, total)
    return {
        "url": reverse("partida_libro", args=[partida.id]),
        "evento": evento,
        "total": total,
        "perfil": partida.perfil_nombre,
        "hp": partida.hp,
        "hp_max": partida.hp_max,
    }
