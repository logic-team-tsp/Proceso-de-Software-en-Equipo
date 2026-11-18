# Registra aqui los modelos para editarlos desde Django Admin (modulo de autoria).
from django.contrib import admin

from .models import (
    EstadisticaJugador,
    IntentoCodigo,
    LogroJugador,
    Partida,
    Puntuacion,
    RegistroDecision,
    ResultadoCuestionario,
    TecnicismoRegistrado,
)


class RegistroDecisionInline(admin.TabularInline):
    model = RegistroDecision
    extra = 0
    can_delete = False
    readonly_fields = ("orden", "evento_id", "opcion_id", "correcta", "probabilidad", "tirada")
    fields = readonly_fields


@admin.register(Partida)
class PartidaAdmin(admin.ModelAdmin):
    list_display = ("id", "perfil_nombre", "estado", "hp", "xp", "indice", "puntuacion", "creada")
    list_filter = ("estado",)
    inlines = [RegistroDecisionInline]


# CU05 - Cuestionario de tecnicismos
@admin.register(TecnicismoRegistrado)
class TecnicismoRegistradoAdmin(admin.ModelAdmin):
    list_display = ("tecnicismo_id", "usuario", "sesion", "partida", "registrado")
    list_filter = ("tecnicismo_id",)
    search_fields = ("tecnicismo_id", "usuario__username", "sesion")


@admin.register(ResultadoCuestionario)
class ResultadoCuestionarioAdmin(admin.ModelAdmin):
    list_display = ("id", "usuario", "sesion", "fecha", "puntaje", "aciertos", "total", "origen")
    list_filter = ("origen",)
    readonly_fields = ("respuestas",)


# CU04 - Minijuego de código
@admin.register(IntentoCodigo)
class IntentoCodigoAdmin(admin.ModelAdmin):
    list_display = (
        "nivel_id",
        "variante",
        "ronda",
        "usuario",
        "sesion",
        "estado",
        "bloques_usados",
        "intentos_fallidos",
        "estrellas",
        "xp_obtenida",
        "creado",
    )
    list_filter = ("nivel_id", "estado")
    readonly_fields = ("tablero", "huella", "resultado")


# CU08 - Obtener logros
@admin.register(LogroJugador)
class LogroJugadorAdmin(admin.ModelAdmin):
    list_display = ("logro_id", "usuario", "sesion", "partida", "fecha")
    list_filter = ("logro_id",)
    search_fields = ("logro_id", "usuario__username", "sesion")


@admin.register(Puntuacion)
class PuntuacionAdmin(admin.ModelAdmin):
    list_display = ("total", "final_titulo", "usuario", "sesion", "nuevo_record", "fecha")
    list_filter = ("final_id", "nuevo_record")
    readonly_fields = ("desglose",)


@admin.register(EstadisticaJugador)
class EstadisticaJugadorAdmin(admin.ModelAdmin):
    list_display = ("usuario", "sesion", "actualizada")
    readonly_fields = ("contadores", "procesados")
