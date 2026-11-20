from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from .services.continuar import partida_para_continuar


def health(request):
    """Comprueba que Django responde y que PostgreSQL esta accesible."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok", "database": "ok"})


def portada(request):
    """Portada. Si hay una partida a medias ofrece continuarla (idea UX «Continuar»)."""
    return render(request, "index.html", {"continuar": partida_para_continuar(request)})
