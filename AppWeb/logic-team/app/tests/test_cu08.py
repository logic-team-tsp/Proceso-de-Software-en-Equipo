"""CU08 - Obtener logros: logros, ranking personal, finales y nivel del jugador.

Cubre el catálogo (app/data/logros.json), el desbloqueo desde la partida (CU01, CU06) y los
minijuegos (CU04, CU05, CU09), la puntuación del ranking (RN04 a RN06), el panel (resumen,
ranking, informe) y los flujos FA2, FA4 a FA7 y FE1 a FE4.
"""

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import pytest
from django.db import DatabaseError
from django.utils import timezone

from app.models import (
    EstadisticaJugador,
    IntentoOrdenar,
    LogroJugador,
    Partida,
    Puntuacion,
)
from app.services import escenarios, logros, motor_partida
from app.services.tecnicismos import Jugador
from app.views_personalizar import PERFILES

PERFIL = PERFILES[0]
TRES = ["ingenieria-requerimientos:0", "ingenieria-requerimientos:1", "ingenieria-requerimientos:2"]


def _partida(temas=None, semilla=1):
    return motor_partida.crear_partida(PERFIL, temas or TRES, semilla=semilla)


def _post(client, url, datos=None):
    return client.post(url, json.dumps(datos or {}), content_type="application/json")


def _opcion(partida, correcta=True):
    partida.refresh_from_db()
    _, catalogo = escenarios.cargar()
    evento = catalogo["eventos"][partida.secuencia[partida.indice]]
    for opcion in evento["opciones"]:
        if evento["tipo"] == escenarios.NORMAL and opcion["correcta"] == correcta:
            return opcion["id"]
    return evento["opciones"][0]["id"]


def _decidir(client, partida, correcta=True):
    respuesta = _post(
        client, f"/partida/{partida.id}/decision/", {"opcion_id": _opcion(partida, correcta)}
    )
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()


def _jugar_hasta_el_final(client, partida, correcta=True):
    """Juega la partida completa y regresa todos los logros nuevos que se notificaron."""
    nuevos = []
    estado = client.get(f"/partida/{partida.id}/estado/").json()
    while estado["fase"] != "fin":
        if estado["fase"] == "mejora":
            estado = _post(client, f"/partida/{partida.id}/mejorar/", {"atributo": "teoria"})
            estado = estado.json()
            continue
        nuevos += (_decidir(client, partida, correcta).get("cu08") or {}).get("nuevos", [])
        estado = _post(client, f"/partida/{partida.id}/continuar/").json()
    return nuevos


def _jugador(client):
    """El jugador de las peticiones del cliente de pruebas (sesión del navegador)."""
    client.get("/")
    return Jugador(sesion=client.session.session_key)


def _ids(lista):
    return [logro["id"] for logro in lista]


def _puntuacion(jugador, total, dias=0, temas=None):
    """Puntuación de ejemplo (sin jugar) para probar el orden del ranking."""
    partida = _partida()
    partida.estado = Partida.COMPLETADA
    partida.save()
    return Puntuacion.objects.create(
        **jugador.campos(),
        partida=partida,
        temas=temas or ["ingenieria-requerimientos"],
        final_id="completada",
        final_titulo="Fin del Capítulo",
        total=total,
        desglose=[],
        fecha=timezone.now() - timedelta(days=dias),
    )


# ---------------------------------------------------------------- catálogo (RN03)
def test_el_catalogo_de_logros_es_valido():
    assert logros.validar() == []
    cat = logros.cargar()
    categorias = {c["id"] for c in cat["categorias"]}
    assert categorias == {"historia", "puntuacion", "vidas", "minijuegos", "nivel"}
    # 4 materias × (1 final completado + 4 de derrota)
    assert cat["total_finales"] == 20


def test_la_validacion_detecta_errores_del_catalogo():
    errores = []
    logros._validar_logros(
        {
            "categorias": [{"id": "vidas", "nombre": "Vidas"}],
            "logros": [
                {
                    "id": "a",
                    "categoria": "vidas",
                    "nombre": "A",
                    "descripcion": "d",
                    "icono": "x",
                    "estadistica": "no-existe",
                    "meta": 1,
                },
                {
                    "id": "a",
                    "categoria": "otra",
                    "nombre": "B",
                    "descripcion": "d",
                    "icono": "x",
                    "estadistica": "vidas_perdidas",
                    "meta": 0,
                },
            ],
        },
        errores,
    )
    texto = " ".join(errores)
    assert "no-existe" in texto and "repetido" in texto and "'otra' no existe" in texto
    assert "'meta'" in texto


# ---------------------------------------------------------------- pasos 1 a 6
@pytest.mark.django_db
def test_perder_una_vida_desbloquea_primera_cicatriz_y_se_notifica(client):
    partida = _partida()
    estado = _decidir(client, partida, correcta=False)
    assert estado["resultado"]["cambios"]["hp"] == -1
    nuevos = estado["cu08"]["nuevos"]
    assert "primera-cicatriz" in _ids(nuevos)
    logro = next(lg for lg in nuevos if lg["id"] == "primera-cicatriz")
    assert logro["nombre"] == "Primera cicatriz" and logro["obtenido"] and logro["fecha"]
    jugador = _jugador(client)
    obtenido = LogroJugador.objects.get(**jugador.filtro(), logro_id="primera-cicatriz")
    assert obtenido.partida_id == partida.id
    assert EstadisticaJugador.objects.get(**jugador.filtro()).contadores["vidas_perdidas"] == 1


@pytest.mark.django_db
def test_fa4_un_logro_ya_obtenido_solo_actualiza_el_contador(client):
    partida = _partida()
    _decidir(client, partida, correcta=False)
    _post(client, f"/partida/{partida.id}/continuar/")
    estado = _decidir(client, partida, correcta=False)
    assert "primera-cicatriz" not in _ids((estado.get("cu08") or {}).get("nuevos", []))
    jugador = _jugador(client)
    assert LogroJugador.objects.filter(**jugador.filtro(), logro_id="primera-cicatriz").count() == 1
    assert EstadisticaJugador.objects.get(**jugador.filtro()).contadores["vidas_perdidas"] == 2


@pytest.mark.django_db
def test_una_decision_correcta_suma_xp_al_nivel_del_jugador(client):
    partida = _partida()
    estado = _decidir(client, partida, correcta=True)
    nivel = estado["cu08"]["nivel"]
    assert nivel["xp_ganada"] == 10 and nivel["xp_total"] == 10
    assert nivel["nivel"] == 1 and not nivel["subio"] and nivel["titulo"] == "Becario"
    assert estado["cu08"]["nuevos"] == []


# ---------------------------------------------------------------- pasos 7 a 9 (RN04 a RN06)
@pytest.mark.django_db
def test_al_llegar_al_final_se_guarda_la_puntuacion_con_su_desglose(client):
    partida = _partida()
    nuevos = _jugar_hasta_el_final(client, partida)
    partida.refresh_from_db()
    assert partida.estado == Partida.COMPLETADA
    puntuacion = Puntuacion.objects.get(partida=partida)
    # RN06: el total es la suma de los componentes
    assert puntuacion.total == sum(fila["puntos"] for fila in puntuacion.desglose)
    filas = {fila["id"]: fila for fila in puntuacion.desglose}
    assert filas["decisiones"]["puntos"] == partida.aciertos * 100
    assert filas["vidas"]["puntos"] == partida.hp * 100
    assert puntuacion.final_id == "completada" and puntuacion.temas == ["ingenieria-requerimientos"]
    assert puntuacion.mejor_anterior is None and not puntuacion.nuevo_record
    # Primera historia, completa y sin perder vidas
    assert {"primer-capitulo", "hasta-el-final", "intachable"} <= set(_ids(nuevos))


@pytest.mark.django_db
def test_el_post_game_muestra_resultados_del_ranking(client):
    partida = _partida()
    _jugar_hasta_el_final(client, partida)
    puntuacion = Puntuacion.objects.get(partida=partida)
    html = client.get(f"/partida/{partida.id}/fin/").content.decode()
    assert "¡Historia terminada!" in html and "Desglose de puntuación" in html
    assert logros.miles(puntuacion.total) in html and "#1 de 1" in html
    assert "Primer capítulo cerrado" in html  # logros de esta partida
    assert 'data-lg-abrir="ranking"' in html and "Mapa de decisiones" in html


@pytest.mark.django_db
def test_nuevo_record_y_mejor_marca_anterior(client):
    jugador = _jugador(client)
    _puntuacion(jugador, 100, dias=3)
    partida = _partida()
    _jugar_hasta_el_final(client, partida)
    puntuacion = Puntuacion.objects.get(partida=partida)
    assert puntuacion.mejor_anterior == 100 and puntuacion.nuevo_record
    assert LogroJugador.objects.filter(**jugador.filtro(), logro_id="superacion").exists()
    html = client.get(f"/partida/{partida.id}/fin/").content.decode()
    assert "¡NUEVO RÉCORD!" in html and "Mejor marca anterior" in html


@pytest.mark.django_db
def test_fa5_la_puntuacion_no_entra_al_top_10(client):
    jugador = _jugador(client)
    for n in range(10):
        _puntuacion(jugador, 9000 + n, dias=5 + n)
    partida = _partida()
    _jugar_hasta_el_final(client, partida, correcta=False)
    resultado = logros.resultado_partida(jugador, Partida.objects.get(pk=partida.id))
    assert not resultado["en_top"] and resultado["posicion"] == 11
    assert resultado["mejor_marca"] == 9009
    html = client.get(f"/partida/{partida.id}/fin/").content.decode()
    assert "Tu mejor marca sigue siendo 9 009 puntos" in html and "Fuera del top 10" in html


@pytest.mark.django_db
def test_derrota_tambien_llega_a_un_final(client):
    partida = _partida()
    partida.hp = 1
    partida.save()
    estado = _decidir(client, partida, correcta=False)
    assert "sin-vidas" in _ids(estado["cu08"]["nuevos"])
    puntuacion = Puntuacion.objects.get(partida=partida)
    assert puntuacion.final_id == "derrota-1" and puntuacion.final_titulo == "El Primer Commit"
    contadores = EstadisticaJugador.objects.get(**_jugador(client).filtro()).contadores
    assert (
        contadores["derrotas"] == 1
        and "ingenieria-requerimientos:derrota-1" in contadores["finales"]
    )


@pytest.mark.django_db
def test_fe3_salir_antes_del_final_no_registra_puntuacion(client):
    partida = _partida()
    _decidir(client, partida, correcta=False)
    jugador = _jugador(client)
    assert not Puntuacion.objects.exists()
    assert logros.resultado_partida(jugador, Partida.objects.get(pk=partida.id)) is None
    # Los logros que obtuvo en la partida se conservan (RN01)
    assert LogroJugador.objects.filter(**jugador.filtro(), logro_id="primera-cicatriz").exists()


@pytest.mark.django_db
def test_una_puntuacion_no_se_registra_dos_veces(client):
    partida = _partida()
    _jugar_hasta_el_final(client, partida)
    jugador = _jugador(client)
    logros.registrar(jugador, [logros.evento_final(partida)], partida)
    assert Puntuacion.objects.filter(partida=partida).count() == 1
    contadores = EstadisticaJugador.objects.get(**jugador.filtro()).contadores
    assert contadores["historias_terminadas"] == 1


# ---------------------------------------------------------------- ranking (paso 13, RN04, FA7)
@pytest.mark.django_db
def test_rn04_ranking_de_mayor_a_menor_y_en_empate_la_mas_antigua(client):
    jugador = _jugador(client)
    vieja = _puntuacion(jugador, 1240, dias=9)
    nueva = _puntuacion(jugador, 1240, dias=4)
    _puntuacion(jugador, 1690, dias=1)
    for n in range(10):
        _puntuacion(jugador, 100 + n, dias=20 + n)
    datos = client.get("/api/logros/ranking/").json()
    assert len(datos["top"]) == 10 and datos["registradas"] == 13
    assert [p["total"] for p in datos["top"][:3]] == [1690, 1240, 1240]
    assert datos["top"][1]["id"] == str(vieja.id) and datos["top"][2]["id"] == str(nueva.id)
    assert datos["top"][0]["reciente"] and datos["top"][0]["posicion"] == 1


@pytest.mark.django_db
def test_fa7_ranking_por_historia(client):
    jugador = _jugador(client)
    _puntuacion(jugador, 500, temas=["intro-programacion"])
    _puntuacion(jugador, 900, temas=["logica-algoritmos"])
    datos = client.get("/api/logros/ranking/?historia=intro-programacion").json()
    assert datos["historia"] == "intro-programacion"
    assert [p["total"] for p in datos["top"]] == [500]
    # Una historia que no existe muestra la clasificación general
    assert len(client.get("/api/logros/ranking/?historia=nada").json()["top"]) == 2


@pytest.mark.django_db
def test_el_ranking_es_personal(client, django_user_model):
    _puntuacion(Jugador(sesion="otra-sesion"), 5000)
    assert client.get("/api/logros/ranking/").json()["registradas"] == 0


# ---------------------------------------------------------------- panel (pasos 11, 12, 14)
@pytest.mark.django_db
def test_fa6_panel_sin_progreso(client):
    datos = client.get("/api/logros/").json()
    assert datos["logros"]["obtenidos"] == 0 and datos["logros"]["porcentaje"] == 0
    assert datos["finales"]["porcentaje"] == 0 and not datos["hay_puntuaciones"]
    assert client.get("/api/logros/ranking/").json()["registradas"] == 0


@pytest.mark.django_db
def test_resumen_porcentajes_ocultos_y_progresivos(client):
    partida = _partida()
    _decidir(client, partida, correcta=False)
    datos = client.get("/api/logros/").json()
    total = datos["logros"]["total"]
    obtenidos = datos["logros"]["obtenidos"]
    assert datos["logros"]["porcentaje"] == round(obtenidos / total * 100)  # RN07
    todos = {lg["id"]: lg for c in datos["categorias"] for lg in c["logros"]}
    # RN08: los ocultos sin obtener van como «???»
    assert todos["explorador"]["nombre"] == "???" and todos["explorador"]["icono"] == "?"
    # FA2: avance de un logro progresivo
    diez = todos["diez-cicatrices"]
    assert diez["progresivo"] and diez["valor"] == 1 and diez["meta"] == 10
    assert diez["porcentaje"] == 10 and not diez["obtenido"]
    vidas = next(c for c in datos["categorias"] if c["id"] == "vidas")
    assert vidas["contadores"] == [{"nombre": "Vidas perdidas", "valor": 1}]


@pytest.mark.django_db
def test_finales_por_historia_con_el_nuevo_resaltado(client):
    partida = _partida()
    _jugar_hasta_el_final(client, partida)
    finales = client.get("/api/logros/").json()["finales"]
    assert finales["desbloqueados"] == 1 and finales["total"] == 20 and finales["porcentaje"] == 5
    historia = next(h for h in finales["historias"] if h["id"] == "ingenieria-requerimientos")
    completada = historia["finales"][0]
    assert completada["descubierto"] and completada["nuevo"]
    assert completada["titulo"] == "Fin del Capítulo"
    assert historia["finales"][1]["titulo"] is None  # RN08: «?»


@pytest.mark.django_db
def test_informe_de_puntuacion(client):
    partida = _partida()
    _jugar_hasta_el_final(client, partida)
    puntuacion = Puntuacion.objects.get(partida=partida)
    datos = client.get(f"/api/logros/puntuacion/{puntuacion.id}/").json()
    assert datos["posicion"] == 1 and datos["total"] == puntuacion.total
    assert len(datos["desglose"]) == 4 and "primer-capitulo" in _ids(datos["logros"])
    otra = _puntuacion(Jugador(sesion="otra-sesion"), 10)
    assert client.get(f"/api/logros/puntuacion/{otra.id}/").status_code == 404


@pytest.mark.django_db
def test_fe2_error_al_cargar_el_panel(client):
    with mock.patch.object(logros, "resumen", side_effect=DatabaseError("caída")):
        respuesta = client.get("/api/logros/")
    assert respuesta.status_code == 500
    assert respuesta.json()["error"] == "No se pudieron cargar tus logros."


# ---------------------------------------------------------------- minijuegos
@pytest.mark.django_db
def test_minijuegos_jugados_completados_y_variedad():
    jugador = Jugador(sesion="mini")
    resultado = logros.registrar(
        jugador,
        [
            logros.evento_minijuego("codigo", True, estrellas=3),
            logros.evento_minijuego("cuestionario", True, perfecto=True),
            logros.evento_minijuego("ordenar", False),
        ],
    )
    nuevos = set(_ids(resultado["nuevos"]))
    assert {"primer-reto", "primera-victoria", "sin-titubeos"} <= nuevos
    contadores = EstadisticaJugador.objects.get(**jugador.filtro()).contadores
    assert contadores["minijuegos_jugados"] == 3 and contadores["minijuegos_completados"] == 2
    assert contadores["niveles_tres_estrellas"] == 1
    assert sorted(contadores["tipos_minijuego_completados"]) == ["codigo", "cuestionario"]
    resultado = logros.registrar(
        jugador,
        [
            logros.evento_minijuego("ordenar", True, estrellas=2),
            logros.evento_minijuego("vidas", True),
        ],
    )
    assert "variedad" in _ids(resultado["nuevos"])


def test_eventos_de_un_intento_de_cu04_o_cu09():
    resuelto = SimpleNamespace(estado="resuelto", estrellas=3)
    assert logros.eventos_intento("ordenar", "en_curso", resuelto)[0]["completado"]
    abandonado = SimpleNamespace(estado="abandonado", estrellas=None)
    assert not logros.eventos_intento("codigo", "en_curso", abandonado)[0]["completado"]
    # Una acción que no termina el nivel no es un evento
    assert logros.eventos_intento("codigo", "en_curso", SimpleNamespace(estado="en_curso")) == []


@pytest.mark.django_db
def test_abandonar_un_nivel_de_ordenar_cuenta_como_jugado(client):
    assert client.get("/jugar/ordenar/1/").status_code == 200
    intento = IntentoOrdenar.objects.latest("creado")
    respuesta = _post(client, f"/api/ordenar/{intento.id}/salir/")
    assert respuesta.status_code == 200
    assert "primer-reto" in _ids(respuesta.json()["cu08"]["nuevos"])


# ---------------------------------------------------------------- FE1 y FE4
@pytest.mark.django_db
def test_fe1_si_no_se_puede_guardar_se_notifica_y_se_reintenta(client):
    partida = _partida()
    with mock.patch.object(LogroJugador.objects, "create", side_effect=DatabaseError("caída")):
        estado = _decidir(client, partida, correcta=False)
    cu08 = estado["cu08"]
    assert cu08["pendiente"] and "primera-cicatriz" in _ids(cu08["nuevos"])
    jugador = _jugador(client)
    assert not LogroJugador.objects.filter(**jugador.filtro()).exists()  # no se guardó nada

    respuesta = _post(client, "/api/logros/reintentar/", {"pendiente": cu08["pendiente"]})
    assert respuesta.status_code == 200 and not respuesta.json()["cu08"]["pendiente"]
    assert "primera-cicatriz" in _ids(respuesta.json()["cu08"]["nuevos"])
    # Un segundo reintento con el mismo progreso no cuenta dos veces
    _post(client, "/api/logros/reintentar/", {"pendiente": cu08["pendiente"]})
    assert EstadisticaJugador.objects.get(**jugador.filtro()).contadores["vidas_perdidas"] == 1


@pytest.mark.django_db
def test_fe1_el_progreso_pendiente_es_del_jugador(client):
    token = logros._firmar(Jugador(sesion="otra"), [{"id": "x", "tipo": "vida_perdida"}], None)
    respuesta = _post(client, "/api/logros/reintentar/", {"pendiente": token})
    assert respuesta.status_code == 400
    assert _post(client, "/api/logros/reintentar/", {"pendiente": "basura"}).status_code == 400


@pytest.mark.django_db
def test_fe4_contadores_invalidos_se_ignoran_y_se_recalculan():
    jugador = Jugador(sesion="fe4")
    EstadisticaJugador.objects.create(
        **jugador.campos(), contadores={"vidas_perdidas": -3, "finales": "no-es-lista"}
    )
    resultado = logros.registrar(jugador, [logros.evento_vidas_perdidas(1)])
    assert "primera-cicatriz" in _ids(resultado["nuevos"])
    contadores = EstadisticaJugador.objects.get(**jugador.filtro()).contadores
    assert contadores["vidas_perdidas"] == 1 and "finales" not in contadores


# ---------------------------------------------------------------- paso 10
@pytest.mark.django_db
def test_el_boton_de_logros_esta_en_todas_las_pantallas(client):
    partida = _partida()
    for url in ("/", f"/partida/{partida.id}/", "/jugar/"):
        html = client.get(url).content.decode()
        assert 'id="logros-btn"' in html and "js/logros.js" in html, url


# ---------------------------------------------------------------- nivel del jugador
def test_cada_nivel_cuesta_mas_experiencia_que_el_anterior():
    reglas = logros.cargar()["nivel"]
    costos = [
        logros.xp_para_nivel(n + 1, reglas) - logros.xp_para_nivel(n, reglas) for n in range(1, 6)
    ]
    assert costos == [100, 200, 300, 400, 500]
    assert logros.nivel_de_xp(0, reglas) == 1 and logros.nivel_de_xp(99, reglas) == 1
    assert logros.nivel_de_xp(100, reglas) == 2 and logros.nivel_de_xp(300, reglas) == 3
    assert logros.nivel_de_xp(10**9, reglas) == reglas["maximo"]
    assert logros.titulo_de(1, reglas) == "Becario" and logros.titulo_de(4, reglas) == "Practicante"
    assert logros.titulo_de(20, reglas) == "Arquitecto de software"


@pytest.mark.django_db
def test_subir_de_nivel_cambia_el_titulo_y_desbloquea_logros_de_nivel():
    jugador = Jugador(sesion="nivel")
    primero = logros.registrar(jugador, [logros.evento_xp(150)])
    assert primero["nivel"]["subio"] and primero["nivel"]["nivel"] == 2
    assert not primero["nivel"]["titulo_nuevo"]
    assert primero["nivel"]["xp_en_nivel"] == 50 and primero["nivel"]["xp_necesaria"] == 200
    assert "nivel-2" in _ids(primero["nuevos"])
    segundo = logros.registrar(jugador, [logros.evento_xp(150)])
    assert segundo["nivel"]["nivel"] == 3 and segundo["nivel"]["titulo_nuevo"]
    assert segundo["nivel"]["titulo"] == "Practicante"
    # La XP no se pierde entre partidas: se acumula
    assert logros.nivel(jugador)["xp_total"] == 300


@pytest.mark.django_db
def test_los_minijuegos_dan_xp_al_nivel_del_jugador():
    jugador = Jugador(sesion="xp-mini")
    resuelto = SimpleNamespace(estado="resuelto", estrellas=2, xp_obtenida=40)
    logros.registrar(jugador, logros.eventos_intento("codigo", "en_curso", resuelto))
    assert logros.nivel(jugador)["xp_total"] == 40
    # Cuestionario: 5 XP por acierto; ronda de vidas ganada: 20 XP; abandonar no da XP
    logros.registrar(jugador, [logros.evento_minijuego("cuestionario", True, aciertos=8)])
    logros.registrar(jugador, [logros.evento_minijuego("vidas", True)])
    logros.registrar(jugador, [logros.evento_minijuego("vidas", False)])
    assert logros.nivel(jugador)["xp_total"] == 40 + 40 + 20


@pytest.mark.django_db
def test_el_nivel_se_ve_en_el_panel_y_en_el_post_game(client):
    partida = _partida()
    _jugar_hasta_el_final(client, partida)
    partida.refresh_from_db()
    datos = client.get("/api/logros/nivel/").json()
    assert datos["xp_total"] == partida.aciertos * 10 and datos["titulo"] == "Becario"
    assert client.get("/api/logros/").json()["nivel"]["xp_total"] == datos["xp_total"]
    html = client.get(f"/partida/{partida.id}/fin/").content.decode()
    assert "Nivel de jugador" in html and f"+{partida.aciertos * 10} XP" in html


def test_la_validacion_revisa_la_curva_y_los_titulos():
    errores = []
    logros._validar_nivel(
        {
            "nivel_jugador": {
                "xp_base": 0,
                "maximo": 20,
                "xp_cuestionario_por_acierto": 5,
                "xp_ronda_vidas_ganada": 20,
                "titulos": [{"desde": 3, "titulo": "A"}, {"desde": 2, "titulo": "B"}],
            }
        },
        errores,
    )
    texto = " ".join(errores)
    assert "'xp_base'" in texto and "en orden" in texto
