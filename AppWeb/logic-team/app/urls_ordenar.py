from django.urls import path

from . import views_ordenar

# CU09: «Ordenar algoritmos» del menú de modos
urlpatterns = [
    path("", views_ordenar.inicio, name="ordenar_inicio"),
    path("<int:numero>/", views_ordenar.mesa, name="ordenar_mesa"),
]
