from django.urls import path

from . import views_tienda

# CU07: «Tienda de temáticas» del menú de modos
urlpatterns = [
    path("", views_tienda.tienda, name="tienda"),
    path("<slug:tematica_id>/", views_tienda.vista, name="tienda_vista"),
    path("<slug:tematica_id>/usar/", views_tienda.usar, name="tienda_usar"),
]
