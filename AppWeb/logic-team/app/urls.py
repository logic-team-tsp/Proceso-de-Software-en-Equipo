from django.urls import path

from . import (
    views,
    views_codigo,
    views_cuestionario,
    views_logros,
    views_ordenar,
    views_tienda,
)

urlpatterns = [
    path("health/", views.health, name="health"),
    # CU05 - Cuestionario de tecnicismos (API que usa js/cuestionario.js)
    path(
        "cuestionario/generar/",
        views_cuestionario.api_generar,
        name="cuestionario_generar",
    ),
    path(
        "cuestionario/resultado/",
        views_cuestionario.api_resultado,
        name="cuestionario_resultado",
    ),
    # CU04 - Minijuego de código (API que usa js/minijuego_codigo.js)
    path(
        "codigo/<uuid:intento_id>/comprobar/", views_codigo.api_comprobar, name="codigo_comprobar"
    ),
    path("codigo/<uuid:intento_id>/salir/", views_codigo.api_salir, name="codigo_salir"),
    # CU09 - Ordenar algoritmos (API que usa js/ordenar.js)
    path("ordenar/<uuid:intento_id>/empezar/", views_ordenar.api_empezar, name="ordenar_empezar"),
    path("ordenar/<uuid:intento_id>/mover/", views_ordenar.api_mover, name="ordenar_mover"),
    path("ordenar/<uuid:intento_id>/pista/", views_ordenar.api_pista, name="ordenar_pista"),
    path("ordenar/<uuid:intento_id>/salir/", views_ordenar.api_salir, name="ordenar_salir"),
    # CU07 - Comprar módulos temáticos (API que usa js/tienda.js)
    path("tienda/comprar/", views_tienda.api_comprar, name="tienda_comprar"),
    # CU08 - Obtener logros (API que usa js/logros.js)
    path("logros/", views_logros.api_resumen, name="logros_resumen"),
    path("logros/nivel/", views_logros.api_nivel, name="logros_nivel"),
    path("logros/ranking/", views_logros.api_ranking, name="logros_ranking"),
    path(
        "logros/puntuacion/<uuid:puntuacion_id>/",
        views_logros.api_informe,
        name="logros_informe",
    ),
    path("logros/reintentar/", views_logros.api_reintentar, name="logros_reintentar"),
]
