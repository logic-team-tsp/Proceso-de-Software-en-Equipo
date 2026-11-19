"""CU07 - Comprar nuevos módulos temáticos de partida.

Cubre el catálogo (RN02, RN05, RN07, FE4), el saldo (RN01), la tienda (paso 2, FA4, FA5, FE6),
la vista previa (pasos 3 y 4, FA1, FA3), la compra (pasos 5 a 9, FE1, FE2, FE3) y jugar con
la temática en CU02 y CU01 (flujo B, RN04, RN06, RN08, FA6, FE5).
"""

import json
from unittest import mock

import pytest
from django.core.management import call_command
from django.db import DatabaseError

from app.models import CompraTematica, IntentoCodigo, IntentoOrdenar, MonederoTienda, Partida
from app.services import escenarios, minijuego_codigo, motor_partida, tematicas
from app.services.tecnicismos import Jugador
from app.views_personalizar import PERFILES

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- ayudas
def _jugador(client):
    client.get("/jugar/")  # abre la sesión del navegador
    return Jugador(sesion=client.session.session_key)


def _estrellas_ordenar(jugador, nivel, estrellas, juego=1):
    return IntentoOrdenar.objects.create(
        **jugador.campos(), juego=juego, nivel=nivel, algoritmo="burbuja",
        estado=IntentoOrdenar.RESUELTO, estrellas=estrellas,
    )


def _estrellas_codigo(jugador, estrellas, nivel_id=None):
    nivel_id = nivel_id or sorted(minijuego_codigo.cargar()["ids"])[0]
    return IntentoCodigo.objects.create(
        **jugador.campos(), nivel_id=nivel_id, estado=IntentoCodigo.RESUELTO, estrellas=estrellas
    )


def _dar(jugador, cuantas):
    """Le da al jugador `cuantas` estrellas con niveles distintos de Ordenar y de código."""
    por_nivel = {}  # un programa por cada (lenguaje, nivel) del minijuego de código
    for nivel_id in sorted(minijuego_codigo.cargar()["ids"]):
        por_nivel.setdefault(minijuego_codigo._ubicar(nivel_id), nivel_id)
    ids = list(por_nivel.values())
    nivel = 0
    while cuantas > 0:
        n = min(3, cuantas)
        if nivel < 3:
            _estrellas_ordenar(jugador, nivel + 1, n)
        else:
            _estrellas_codigo(jugador, n, ids[nivel - 3])
        cuantas -= n
        nivel += 1


def _comprar(client, tematica_id):
    return client.post(
        "/api/tienda/comprar/", json.dumps({"tematica": tematica_id}),
        content_type="application/json",
    )


def _precio(tematica_id):
    return tematicas.cargar()["tematicas"][tematica_id]["precio"]


def _iniciar_partida(client, tematica_id):
    """CU02 completo: perfil, temas y temática; devuelve la partida creada."""
    client.post("/personalizar/", {"perfil": PERFILES[0]["id"]})
    respuesta = client.post(
        "/personalizar/modulo/", {"tema": ["intro-programacion:0"], "tematica": tematica_id}
    )
    assert respuesta.status_code == 302
    client.get("/personalizar/comenzar/")
    return Partida.objects.latest("creada")


# ---------------------------------------------------------------- catálogo (RN02, RN05, RN07)
def test_el_catalogo_de_tematicas_es_valido():
    assert tematicas.validar() == []
    cat = tematicas.cargar()
    nombres = [cat["tematicas"][i]["nombre"] for i in cat["orden"]]
    assert nombres == ["Clásica", "Medieval", "Samurái", "Academia de magia"]  # RN07
    assert cat["tematicas"]["clasica"]["precio"] == 0  # RN02
    assert all(cat["tematicas"][i]["precio"] > 0 for i in cat["orden"][1:])


def test_rn05_glosario_medieval_y_samurai():
    cat = tematicas.cargar()
    medieval, samurai = cat["tematicas"]["medieval"], cat["tematicas"]["samurai"]
    texto = "El cliente revisa el proyecto con tu equipo y el gerente."
    assert tematicas.aplicar_texto(texto, medieval) == (
        "El rey revisa el encargo con tu gremio y el consejero real."
    )
    assert tematicas.aplicar_texto(texto, samurai) == (
        "El shogun revisa el mandato con tu clan y el daimyō."
    )


def test_el_glosario_respeta_mayusculas_y_frases_largas():
    medieval = tematicas.cargar()["tematicas"]["medieval"]
    assert tematicas.aplicar_texto("La Lista de Deseos del Cliente", medieval) == (
        "La Lista de Deseos del Rey"
    )
    # «tu líder técnica» va antes que «tu líder»
    assert tematicas.aplicar_texto("Tu líder técnica aprueba.", medieval) == (
        "Tu maestra de forja aprueba."
    )
    # solo palabras completas: «clientela» no es «cliente»
    assert tematicas.aplicar_texto("la clientela", medieval) == "la clientela"


def test_la_clasica_no_cambia_el_texto():
    clasica = tematicas.cargar()["tematicas"]["clasica"]
    texto = "El cliente revisa el proyecto."
    assert tematicas.aplicar_texto(texto, clasica) == texto


def test_rn05_los_tecnicismos_nunca_se_reemplazan():
    _, catalogo = escenarios.cargar()
    formas = {f.lower() for t in catalogo["tecnicismos"].values() for f in t["formas"]}
    reemplazables = {f for lista in tematicas.cargar()["terminos"].values() for f in lista}
    assert not formas & reemplazables


def test_fe4_una_tematica_con_errores_no_aparece_y_se_registra(tmp_path, monkeypatch, caplog):
    for ruta in tematicas.TEMATICAS_DIR.glob("*.json"):
        (tmp_path / ruta.name).write_text(ruta.read_text(encoding="utf-8"), encoding="utf-8")
    samurai = json.loads((tmp_path / "samurai.json").read_text(encoding="utf-8"))
    del samurai["glosario"]["equipo"]  # le falta un término del glosario
    (tmp_path / "samurai.json").write_text(json.dumps(samurai), encoding="utf-8")
    (tmp_path / "medieval.json").write_text("{ no es json", encoding="utf-8")
    monkeypatch.setattr(tematicas, "TEMATICAS_DIR", tmp_path)
    monkeypatch.setattr(tematicas, "CLASICA_PATH", tmp_path / "clasica.json")
    monkeypatch.setitem(tematicas._cache, "firma", None)

    errores = tematicas.validar()
    assert any("samurai.json" in e and "'equipo'" in e for e in errores)
    assert any("medieval.json" in e and "JSON inválido" in e for e in errores)
    assert set(tematicas.cargar()["tematicas"]) == {"clasica", "academia-magia"}
    # FE4: una partida que ya la tenía se presenta con la Clásica
    assert tematicas.tematica("samurai")["id"] == "clasica"
    monkeypatch.setitem(tematicas._cache, "firma", None)


def test_fe4_precio_invalido_y_tecnicismo_en_el_glosario(tmp_path, monkeypatch):
    for ruta in tematicas.TEMATICAS_DIR.glob("*.json"):
        (tmp_path / ruta.name).write_text(ruta.read_text(encoding="utf-8"), encoding="utf-8")
    medieval = json.loads((tmp_path / "medieval.json").read_text(encoding="utf-8"))
    medieval["precio"] = "tres"
    (tmp_path / "medieval.json").write_text(json.dumps(medieval), encoding="utf-8")
    clasica = json.loads((tmp_path / "clasica.json").read_text(encoding="utf-8"))
    clasica["terminos"]["equipo"].append("la variable")
    (tmp_path / "clasica.json").write_text(json.dumps(clasica), encoding="utf-8")
    monkeypatch.setattr(tematicas, "TEMATICAS_DIR", tmp_path)
    monkeypatch.setattr(tematicas, "CLASICA_PATH", tmp_path / "clasica.json")
    monkeypatch.setitem(tematicas._cache, "firma", None)
    errores = tematicas.validar()
    assert any("tecnicismo" in e for e in errores)
    monkeypatch.setitem(tematicas._cache, "firma", None)


def test_validar_escenarios_revisa_las_tematicas(capsys):
    call_command("validar_escenarios")
    assert "Temáticas del CU-07 válidas" in capsys.readouterr().out


# ---------------------------------------------------------------- saldo (RN01)
def test_rn01_saldo_suma_la_mejor_calificacion_de_cada_nivel(client):
    jugador = _jugador(client)
    _estrellas_ordenar(jugador, 1, 2)
    _estrellas_ordenar(jugador, 1, 2, juego=2)  # repetir con el mismo resultado no suma
    _estrellas_ordenar(jugador, 1, 3, juego=3)  # mejorarlo suma solo la diferencia
    _estrellas_ordenar(jugador, 2, 1)
    _estrellas_codigo(jugador, 2)
    _estrellas_codigo(jugador, 1)
    cuenta = tematicas.saldo(jugador)
    assert cuenta["ganadas"] == 3 + 1 + 2
    assert cuenta["saldo"] == 6


def test_rn01_y_rn03_gastar_no_cambia_las_estrellas_de_los_minijuegos(client):
    jugador = _jugador(client)
    _dar(jugador, 9)
    antes = minijuego_codigo.estrellas_ganadas(jugador)
    assert _comprar(client, "medieval").status_code == 201
    assert minijuego_codigo.estrellas_ganadas(jugador) == antes
    cuenta = tematicas.saldo(jugador)
    assert (cuenta["ganadas"], cuenta["gastadas"], cuenta["saldo"]) == (9, 6, 3)


def test_el_saldo_es_de_cada_jugador(client, django_user_model):
    jugador = _jugador(client)
    _dar(jugador, 9)
    usuario = django_user_model.objects.create_user("ana", password="x")
    assert tematicas.saldo(Jugador(usuario=usuario))["saldo"] == 0


# ---------------------------------------------------------------- tienda (paso 2)
def test_paso1_el_menu_de_modos_abre_la_tienda_en_un_clic(client):
    _dar(_jugador(client), 4)
    html = client.get("/jugar/").content.decode()
    assert 'href="/jugar/tienda/"' in html
    assert "★ 4" in html


def test_paso2_la_tienda_muestra_saldo_catalogo_y_estados(client):
    jugador = _jugador(client)
    _dar(jugador, 9)
    datos = tematicas.tienda(jugador)
    estados = {t["id"]: (t["estado"], t["faltan"]) for t in datos["tematicas"]}
    assert estados == {
        "clasica": ("adquirida", 0),
        "medieval": ("disponible", 0),
        "samurai": ("faltan", 10 - 9),
        "academia-magia": ("faltan", 15 - 9),
    }
    html = client.get("/jugar/tienda/").content.decode()
    assert "Tienda de temáticas" in html
    assert "✔ ADQUIRIDA" in html and "★ DISPONIBLE" in html and "🔒 FALTAN 1 ★" in html


def test_fa4_sin_estrellas_todavia(client):
    _jugador(client)
    html = client.get("/jugar/tienda/").content.decode()
    assert "Completa minijuegos para ganar estrellas" in html
    assert 'href="/jugar/tienda/samurai/"' in html  # puede ver las vistas previas


def test_fa5_todas_las_tematicas_adquiridas(client):
    jugador = _jugador(client)
    _dar(jugador, 33)
    for tid in ("medieval", "samurai", "academia-magia"):
        assert _comprar(client, tid).status_code == 201
    html = client.get("/jugar/tienda/").content.decode()
    assert "¡Tienes todas las temáticas!" in html
    assert tematicas.saldo(jugador)["saldo"] == 33 - 6 - 10 - 15


def test_fe6_error_al_cargar_la_tienda(client):
    with mock.patch.object(tematicas, "tienda", side_effect=DatabaseError("caída")):
        respuesta = client.get("/jugar/tienda/")
    assert respuesta.status_code == 503
    assert "No se pudo cargar la tienda" in respuesta.content.decode()
    assert "Reintentar" in respuesta.content.decode()


def test_el_menu_de_modos_funciona_aunque_falle_la_tienda(client):
    with mock.patch.object(tematicas, "resumen_menu", side_effect=DatabaseError("caída")):
        assert client.get("/jugar/").status_code == 200


# ---------------------------------------------------------------- vista previa (pasos 3 y 4)
def test_paso4_vista_previa_con_la_clasica_y_la_tematica(client):
    _dar(_jugador(client), 6)
    respuesta = client.get("/jugar/tienda/medieval/")
    assert respuesta.status_code == 200
    html = respuesta.content.decode()
    assert "📖 Clásica" in html and "🏰 Medieval" in html
    assert '<span class="c7-term">la startup</span>' in html
    assert '<span class="c7-term">la corte</span>' in html
    assert "Comprar por 6 ★" in html
    assert '<span class="c7-tec">' in html  # el tecnicismo se marca y no cambia


def test_rn04_las_opciones_de_la_vista_previa_son_las_mismas(client):
    jugador = _jugador(client)
    vista = tematicas.vista_previa(jugador, "samurai")
    textos = lambda escena: ["".join(s["texto"] for s in op) for op in escena["opciones"]]  # noqa: E731
    assert textos(vista["clasica"]) == textos(vista["escena"])


def test_fa1_estrellas_insuficientes_en_la_vista_previa(client):
    _dar(_jugador(client), 4)
    html = client.get("/jugar/tienda/samurai/").content.decode()
    assert 'id="c7-comprar" disabled' in html
    assert "Te faltan <b id=\"c7-faltan\">6</b>" in html


def test_fa3_tematica_ya_adquirida(client):
    _dar(_jugador(client), 6)
    _comprar(client, "medieval")
    html = client.get("/jugar/tienda/medieval/").content.decode()
    assert "Usar en mi próxima partida" in html
    assert 'id="c7-comprar"' not in html


def test_una_tematica_que_no_existe_da_404(client):
    assert client.get("/jugar/tienda/pirata/").status_code == 404


# ---------------------------------------------------------------- compra (pasos 7 a 9)
def test_paso8_la_compra_descuenta_y_registra(client):
    jugador = _jugador(client)
    _dar(jugador, 12)
    respuesta = _comprar(client, "samurai")
    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert (datos["saldo_anterior"], datos["saldo"], datos["precio"]) == (12, 2, 10)
    compra = CompraTematica.objects.get(tematica_id="samurai")
    assert compra.precio == 10 and compra.fecha
    assert MonederoTienda.objects.get(sesion=jugador.sesion).gastadas == 10


def test_fe2_compra_repetida_cobra_una_sola_vez(client):
    jugador = _jugador(client)
    _dar(jugador, 12)
    assert _comprar(client, "medieval").status_code == 201
    segunda = _comprar(client, "medieval")
    assert segunda.status_code == 200 and segunda.json()["nueva"] is False
    assert CompraTematica.objects.filter(tematica_id="medieval").count() == 1
    assert tematicas.saldo(jugador)["saldo"] == 12 - 6


def test_fe3_el_saldo_cambio_y_ya_no_alcanza(client):
    jugador = _jugador(client)
    _dar(jugador, 12)
    assert _comprar(client, "medieval").status_code == 201  # «otra pestaña»
    respuesta = _comprar(client, "samurai")
    assert respuesta.status_code == 409
    assert respuesta.json()["faltan"] == 10 - 6
    assert not CompraTematica.objects.filter(tematica_id="samurai").exists()


def test_fe1_error_al_registrar_no_descuenta_nada(client):
    jugador = _jugador(client)
    _dar(jugador, 12)
    with mock.patch.object(CompraTematica.objects, "create", side_effect=DatabaseError("x")):
        respuesta = _comprar(client, "samurai")
    assert respuesta.status_code == 500
    assert "No se pudo completar la compra" in respuesta.json()["error"]
    assert not CompraTematica.objects.exists()
    assert tematicas.saldo(jugador)["saldo"] == 12


def test_la_clasica_no_se_compra_y_una_inexistente_da_404(client):
    _dar(_jugador(client), 12)
    assert _comprar(client, "clasica").status_code == 404
    assert _comprar(client, "pirata").status_code == 404


def test_rn08_iniciar_otra_partida_no_borra_compras_ni_saldo(client):
    jugador = _jugador(client)
    _dar(jugador, 9)
    _comprar(client, "medieval")
    _iniciar_partida(client, "clasica")
    assert tematicas.saldo(jugador)["saldo"] == 3
    assert CompraTematica.objects.filter(tematica_id="medieval").exists()


# ---------------------------------------------------------------- jugar con la temática (B)
def test_b1_cu02_ofrece_la_clasica_y_las_adquiridas(client):
    _dar(_jugador(client), 6)
    _comprar(client, "medieval")
    client.post("/personalizar/", {"perfil": PERFILES[0]["id"]})
    html = client.get("/personalizar/modulo/").content.decode()
    assert 'value="clasica" checked' in html
    assert 'value="medieval"' in html
    assert 'value="samurai"' not in html


def test_b1_usar_en_mi_proxima_partida_la_deja_seleccionada(client):
    _dar(_jugador(client), 6)
    _comprar(client, "medieval")
    respuesta = client.post("/jugar/tienda/medieval/usar/")
    assert respuesta.status_code == 302 and respuesta["Location"] == "/personalizar/"
    client.post("/personalizar/", {"perfil": PERFILES[0]["id"]})
    assert 'value="medieval" checked' in client.get("/personalizar/modulo/").content.decode()


def test_b3_la_partida_guarda_la_tematica_y_el_libro_la_aplica(client):
    _dar(_jugador(client), 6)
    _comprar(client, "medieval")
    partida = _iniciar_partida(client, "medieval")
    assert partida.tematica == "medieval"  # RN06
    estado = client.get(f"/partida/{partida.id}/estado/").json()
    assert estado["tematica"]["id"] == "medieval"
    config, _ = escenarios.cargar()
    nombres = {b["nombre"] for b in config["bloques"]}
    assert estado["bloque"]["nombre"] not in nombres  # el capítulo se llama distinto


def test_rn04_la_tematica_no_cambia_reglas_ni_opciones(client):
    clasica = motor_partida.crear_partida(PERFILES[0], ["ingenieria-requerimientos:0"], semilla=7)
    medieval = motor_partida.crear_partida(
        PERFILES[0], ["ingenieria-requerimientos:0"], semilla=7, tematica="medieval"
    )
    a, b = motor_partida.estado_publico(clasica), motor_partida.estado_publico(medieval)
    assert a["evento"]["id"] == b["evento"]["id"]
    assert a["evento"]["opciones"] == b["evento"]["opciones"]
    assert a["tecnicismos"] == b["tecnicismos"]
    for campo in ("hp", "hp_max", "xp", "atributos", "evento_total"):
        assert a[campo] == b[campo]
    # el desenlace se narra con la temática, pero el resultado es el mismo
    opcion = a["evento"]["opciones"][0]["id"]
    motor_partida.resolver_decision(clasica, opcion)
    motor_partida.resolver_decision(medieval, opcion)
    ra = motor_partida.estado_publico(clasica)["resultado"]
    rb = motor_partida.estado_publico(medieval)["resultado"]
    assert (ra["acierto"], ra["cambios"]) == (rb["acierto"], rb["cambios"])
    assert ra["retroalimentacion"] == rb["retroalimentacion"]
    medieval.refresh_from_db()
    # lo guardado en la partida queda en la Clásica; solo cambia lo que se muestra
    assert medieval.resultado_pendiente["desenlace"] == ra["desenlace"]


def test_fa6_sin_cambiar_el_selector_se_juega_con_la_clasica(client):
    _jugador(client)
    client.post("/personalizar/", {"perfil": PERFILES[0]["id"]})
    client.post("/personalizar/modulo/", {"tema": ["intro-programacion:0"]})
    client.get("/personalizar/comenzar/")
    assert Partida.objects.latest("creada").tematica == "clasica"


def test_fe5_una_tematica_no_adquirida_se_juega_con_la_clasica(client):
    _jugador(client)
    partida = _iniciar_partida(client, "samurai")  # modificando la petición
    assert partida.tematica == "clasica"


def test_fe4_una_partida_con_tematica_invalida_se_narra_con_la_clasica():
    partida = motor_partida.crear_partida(
        PERFILES[0], ["intro-programacion:0"], semilla=3, tematica="ya-no-existe"
    )
    assert motor_partida.estado_publico(partida)["tematica"]["id"] == "clasica"
