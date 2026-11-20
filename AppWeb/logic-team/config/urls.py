from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from app.views import portada

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("app.urls")),
    path("personalizar/", include("app.urls_personalizar")),
    path("partida/", include("app.urls_partida")),
    path("jugar/codigo/", include("app.urls_codigo")),
    path("jugar/ordenar/", include("app.urls_ordenar")),
    path("jugar/tienda/", include("app.urls_tienda")),
    path("jugar/", include("app.urls_cuestionario")),
    path("personalizar-partida/", RedirectView.as_view(pattern_name="personalizar_perfil")),
    path("", portada, name="home"),
]
