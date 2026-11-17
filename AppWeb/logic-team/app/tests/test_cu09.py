"""CU09 - Ordenar algoritmos: se abre desde el menú de modos.

Casos del documento «Diseño de casos de prueba CU07-CU09 (9.1)». Cada nivel es un algoritmo
(burbuja, selección e inserción) y el jugador ordena una lista al azar paso a paso como lo haría
el algoritmo. Cubre el contenido, las listas (RN06), el siguiente movimiento de cada algoritmo
(RN08), la calificación (RN01 a RN05) y la API de la mesa (flujo normal, FA1 a FA6, FE1 a FE4).
"""

import json

import pytest
from django.core.management import call_command

from app.models import IntentoOrdenar
from app.services import ordenar

BURBUJA = [5, 1, 4, 2, 8]
SELECCION = [29, 10, 14, 37, 13, 50]
INSERCION = [7, 3, 9, 1, 8, 2]
LISTAS = {1: BURBUJA, 2: SELECCION, 3: INSERCION}


def _abrir(client, numero=1):
    respuesta = client.get(f"/jugar/ordenar/{numero}/")
    assert respuesta.status_code == 200
    return IntentoOrdenar.objects.filter(nivel=numero).latest("creado")


def _post(client, intento, accion, datos=None):
    url = f"/api/ordenar/{intento.id}/{accion}/"
    return client.post(url, json.dumps(datos or {}), content_type="application/json")


def _empezar(client, intento, lista=None):
    """Empieza el nivel; la lista sale al azar, así que las pruebas pueden fijar una conocida."""
    assert _post(client, intento, "empezar").status_code == 200
    intento.refresh_from_db()
    if lista is not None:
        intento.lista_inicial = list(lista)
        intento.lista = list(lista)
        intento.save()
    return intento


def _mover(client, intento, **movimiento):
    intento.refresh_from_db()
    respuesta = _post(client, intento, "mover", {"paso": intento.paso, **movimiento})
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()["ordenar"]


def _como_dato(mov):
    claves = {"intercambiar": ("a", "b"), "insertar": ("desde", "hasta"), "ya": ()}[mov["tipo"]]
    return {"tipo": mov["tipo"], **{k: mov[k] for k in claves}}


def _resolver(client, intento):
    """Hace los movimientos correctos que le faltan al nivel."""
    intento.refresh_from_db()
    r = None
    movimientos = ordenar.traza(intento.algoritmo, intento.lista_inicial)["movimientos"]
    for mov in movimientos[intento.paso :]:
        r = _mover(client, intento, **_como_dato(mov))
    return r


def _jugar_nivel(client, numero):
    return _resolver(client, _empezar(client, _abrir(client, numero), LISTAS[numero]))


def _estado(client, numero):
    html = client.get(f"/jugar/ordenar/{numero}/").content.decode()
    inicio = html.index('id="or-estado"')
    return json.loads(html[html.index(">", inicio) + 1 : html.index("</script>", inicio)])


def _movimientos(algoritmo, lista):
    salida = []
    for m in ordenar.traza(algoritmo, lista)["movimientos"]:
        if m["tipo"] == "intercambiar":
            salida.append(f"{m['a']}-{m['b']}")
        elif m["tipo"] == "insertar":
            salida.append(f"{m['desde']}->{m['hasta']}")
        else:
            salida.append("ya")
    return salida


# ---------------------------------------------------------------- unitarias: contenido y reglas
def test_contenido_de_los_3_algoritmos_es_valido(capsys):
    """Test 1 · Precondición y RN07."""
    assert ordenar.validar() == []
    catalogo = ordenar.cargar()
    niveles = catalogo["niveles"]
    nombres = [catalogo["algoritmos"][n["algoritmo"]]["nombre"] for n in niveles]
    assert nombres == ["Burbuja", "Selección", "Inserción"]
    assert [n["xp_base"] for n in niveles] == [30, 40, 50]
    for algoritmo in catalogo["algoritmos"].values():
        assert algoritmo["explicacion"] and algoritmo["pseudocodigo"] and algoritmo["ejemplo"]
    call_command("validar_escenarios")
    assert "Ordenar algoritmos válido: 3 niveles" in capsys.readouterr().out


def test_la_lista_al_azar_cumple_rn06():
    """Test 2 · RN06, valores límite."""
    reglas = ordenar.cargar()["reglas"]
    for nivel_ in ordenar.cargar()["niveles"]:
        for _ in range(200):
            lista = ordenar.generar_lista(nivel_, reglas)
            assert len(lista) == {1: 5, 2: 6, 3: 6}[nivel_["numero"]]
            assert len(set(lista)) == len(lista)
            assert all(1 <= x <= 99 for x in lista)
            assert lista != sorted(lista)
            assert len(ordenar.traza(nivel_["algoritmo"], lista)["movimientos"]) >= 3


def test_siguiente_movimiento_burbuja():
    """Test 4 · RN08 (burbuja)."""
    t = ordenar.traza("burbuja", BURBUJA)
    assert _movimientos("burbuja", BURBUJA) == ["0-1", "1-2", "2-3", "1-2"]
    assert t["movimientos"][-1]["lista"] == [1, 2, 4, 5, 8]
    assert t["intercambios"] == 4
    assert t["comparaciones"] == 10  # la burbuja hace todas sus pasadas


def test_siguiente_movimiento_seleccion():
    """Test 5 · RN08 (selección) y FA3."""
    t = ordenar.traza("seleccion", SELECCION)
    assert _movimientos("seleccion", SELECCION) == ["0-1", "1-4", "ya", "3-4", "ya"]
    assert t["intercambios"] == 3
    assert t["comparaciones"] == 15


def test_siguiente_movimiento_insercion():
    """Test 6 · RN08 (inserción) y FA3."""
    t = ordenar.traza("insercion", INSERCION)
    assert _movimientos("insercion", INSERCION) == ["1->0", "ya", "3->0", "4->3", "5->1"]
    assert t["movimientos"][-1]["lista"] == [1, 2, 3, 7, 8, 9]
    assert t["comparaciones"] == 12
    assert t["intercambios"] == 9  # cada corrimiento cuenta como intercambio


@pytest.mark.parametrize(
    "xp_base, errores, mostrado, estrellas, xp",
    [
        (30, 0, False, 3, 30),
        (30, 1, False, 2, 21),
        (30, 2, False, 2, 20),
        (30, 3, False, 1, 13),
        (30, 10, False, 1, 8),
        (30, 12, False, 1, 8),  # la penalización se queda en el tope de 50 %
        (50, 2, False, 2, 34),
        (40, 0, True, 1, 20),  # FE3: si se mostró un paso, máximo 1 estrella
    ],
)
def test_estrellas_y_xp_segun_los_errores(xp_base, errores, mostrado, estrellas, xp):
    """Test 11 · RN01, RN03, RN04 y RN05 (misma fórmula que CU04)."""
    reglas = ordenar.cargar()["reglas"]
    resultado = ordenar.calificar(errores, mostrado, xp_base, reglas)
    assert (resultado["estrellas"], resultado["xp"]) == (estrellas, xp)


# ---------------------------------------------------------------- integración: flujo normal
@pytest.mark.django_db
def test_el_menu_abre_el_nivel_que_sigue(client):
    """Test 7 · Flujo normal (paso 1)."""
    menu = client.get("/jugar/").content.decode()
    assert 'href="/jugar/ordenar/"' in menu and "Ordenar algoritmos" in menu
    assert client.get("/jugar/ordenar/").url == "/jugar/ordenar/1/"
    _jugar_nivel(client, 1)
    assert client.get("/jugar/ordenar/").url == "/jugar/ordenar/2/"


@pytest.mark.django_db
def test_explicacion_y_empezar_crean_el_intento(client):
    """Test 8 · Flujo normal (pasos 2 y 3)."""
    estado = _estado(client, 1)
    assert estado["empezado"] is False and estado["mesa"] is None
    assert estado["algoritmo"]["explicacion"] and estado["algoritmo"]["pseudocodigo"]
    intento = IntentoOrdenar.objects.get()
    respuesta = _post(client, intento, "empezar").json()["ordenar"]
    assert respuesta["empezado"] is True
    mesa = respuesta["mesa"]
    assert len(mesa["lista"]) == 5
    assert mesa["contadores"] == {"comparaciones": 0, "intercambios": 0, "errores": 0}
    intento.refresh_from_db()
    assert intento.estado == IntentoOrdenar.EN_CURSO and intento.lista == mesa["lista"]


@pytest.mark.django_db
def test_el_navegador_no_recibe_los_movimientos_de_la_solucion(client):
    """Special Requirements: la revisión la hace el servidor."""
    intento = _empezar(client, _abrir(client, 1))
    estado = _estado(client, 1)
    claves = set()

    def juntar(valor):
        if isinstance(valor, dict):
            claves.update(valor)
            for v in valor.values():
                juntar(v)
        elif isinstance(valor, list):
            for v in valor:
                juntar(v)

    juntar(estado)
    assert not claves & {"movimientos", "comparando", "lista_inicial"}
    assert set(estado["mesa"]) == {
        "lista",
        "ordenadas",
        "turno",
        "indicacion",
        "linea",
        "contadores",
        "paso",
    }
    assert intento.lista_inicial is not None


@pytest.mark.django_db
def test_movimiento_correcto_se_aplica_y_se_guarda(client):
    """Test 9 · Flujo normal (pasos 4 y 5)."""
    intento = _empezar(client, _abrir(client, 1), BURBUJA)
    r = _mover(client, intento, tipo="intercambiar", a=0, b=1)
    assert r["aplicado"] and r["correcto"]
    assert r["mesa"]["lista"] == [1, 5, 4, 2, 8]
    assert r["mesa"]["contadores"]["intercambios"] == 1
    intento.refresh_from_db()
    assert intento.paso == 1 and intento.lista == [1, 5, 4, 2, 8]


@pytest.mark.django_db
def test_resolver_el_nivel_califica_y_guarda(client):
    """Test 10 · Flujo normal (pasos 6 a 9), RN01 y RN04."""
    r = _jugar_nivel(client, 1)
    assert r["terminado"] is True
    assert r["resultado"]["estrellas"] == 3 and r["resultado"]["xp"] == 30
    assert r["resultado"]["comparaciones"] == 10 and r["resultado"]["intercambios"] == 4
    assert r["juego"]["siguiente"] == 2
    intento = IntentoOrdenar.objects.get(nivel=1)
    assert intento.estado == IntentoOrdenar.RESUELTO
    assert (intento.estrellas, intento.xp_obtenida, intento.errores) == (3, 30, 0)
    assert intento.resultado["lista_inicial"] == BURBUJA


# ---------------------------------------------------------------- integración: FA y FE
@pytest.mark.django_db
def test_movimiento_incorrecto_no_se_aplica_y_cuenta_error(client):
    """Test 12 · FE1 y RN02."""
    intento = _empezar(client, _abrir(client, 1), BURBUJA)
    r = _mover(client, intento, tipo="intercambiar", a=2, b=3)  # el par 4-2, pero toca el 5-1
    assert r["aplicado"] is False and r["correcto"] is False
    assert "5 y 1" in r["explicacion"]
    assert r["mesa"]["lista"] == BURBUJA and r["mesa"]["contadores"]["errores"] == 1
    r = _mover(client, intento, tipo="intercambiar", a=3, b=4)  # 2 y 8 ya están en orden
    assert "ya están en orden" in r["explicacion"]


@pytest.mark.django_db
def test_movimiento_no_permitido_no_cuenta_error(client):
    """Test 13 · FE2 y RN02."""
    intento = _empezar(client, _abrir(client, 1), BURBUJA)
    r = _mover(client, intento, tipo="intercambiar", a=0, b=2)
    assert r["permitido"] is False
    assert r["aviso"] == "En burbuja solo se intercambian tarjetas vecinas."
    intento.refresh_from_db()
    assert intento.errores == 0

    intento.lista = intento.lista_inicial = INSERCION
    intento.nivel, intento.algoritmo, intento.paso = 3, "insercion", 1
    intento.lista = [3, 7, 9, 1, 8, 2]
    intento.save()
    r = _mover(client, intento, tipo="insertar", desde=4, hasta=3)  # en la parte sin ordenar
    assert r["permitido"] is False and "parte ordenada" in r["aviso"]
    intento.refresh_from_db()
    assert intento.errores == 0


@pytest.mark.django_db
def test_tres_errores_en_el_mismo_paso_muestran_el_movimiento(client):
    """Test 14 · FE3 y RN03."""
    intento = _empezar(client, _abrir(client, 1), BURBUJA)
    for _ in range(2):
        assert _mover(client, intento, tipo="intercambiar", a=2, b=3)["aplicado"] is False
    r = _mover(client, intento, tipo="intercambiar", a=2, b=3)
    assert r["aplicado"] is True and r["mostrado"] is True
    assert r["movimiento"] == {"tipo": "intercambiar", "a": 0, "b": 1}
    r = _resolver(client, intento)
    assert r["resultado"]["estrellas"] == 1 and r["resultado"]["errores"] == 3


@pytest.mark.django_db
def test_pista_resalta_sin_mover_y_cuenta_error(client):
    """Test 15 · FA1 y RN02."""
    intento = _empezar(client, _abrir(client, 1), BURBUJA)
    r = _post(client, intento, "pista").json()["ordenar"]
    assert r["comparando"] == [0, 1] and "5 y 1" in r["texto"]
    assert r["mesa"]["lista"] == BURBUJA and r["mesa"]["contadores"]["errores"] == 1
    intento.refresh_from_db()
    assert (intento.errores, intento.pistas, intento.paso) == (1, 1, 0)


@pytest.mark.django_db
def test_ya_esta_en_su_lugar(client):
    """Test 16 · FA3."""
    _jugar_nivel(client, 1)
    intento = _empezar(client, _abrir(client, 2), SELECCION)
    # Toca acomodar el 10, que no está en su lugar: «Ya está en su lugar» es un error (FE1)
    r = _mover(client, intento, tipo="ya")
    assert r["aplicado"] is False and "no es el menor" in r["explicacion"]
    _mover(client, intento, tipo="intercambiar", a=0, b=1)
    _mover(client, intento, tipo="intercambiar", a=1, b=4)
    r = _mover(client, intento, tipo="ya")  # el 14 ya está en su lugar
    assert r["aplicado"] is True and r["correcto"] is True
    intento.refresh_from_db()
    assert intento.paso == 3 and intento.errores == 1


@pytest.mark.django_db
def test_como_funciona_no_pierde_el_avance(client):
    """Test 17 · FA2."""
    intento = _empezar(client, _abrir(client, 1), BURBUJA)
    _mover(client, intento, tipo="intercambiar", a=0, b=1)
    _mover(client, intento, tipo="intercambiar", a=3, b=4)  # error
    estado = _estado(client, 1)
    assert estado["algoritmo"]["explicacion"] and estado["algoritmo"]["ejemplo"]
    assert estado["mesa"]["paso"] == 1 and estado["mesa"]["lista"] == [1, 5, 4, 2, 8]
    assert estado["mesa"]["contadores"]["errores"] == 1


@pytest.mark.django_db
def test_salir_descarta_el_intento_sin_xp(client):
    """Test 18 · FA4."""
    _jugar_nivel(client, 1)
    intento = _empezar(client, _abrir(client, 2))
    r = _post(client, intento, "salir").json()["ordenar"]
    assert r["url"] == "/jugar/"
    intento.refresh_from_db()
    assert intento.estado == IntentoOrdenar.ABANDONADO and intento.xp_obtenida == 0
    assert client.get("/jugar/ordenar/").url == "/jugar/ordenar/2/"
    nuevo = _abrir(client, 2)
    assert nuevo.pk != intento.pk and nuevo.lista is None  # al empezar sale una lista nueva


@pytest.mark.django_db
def test_terminar_los_3_niveles_muestra_el_resumen(client):
    """Test 19 · FA5."""
    for numero in (1, 2):
        _jugar_nivel(client, numero)
    r = _jugar_nivel(client, 3)
    juego = r["juego"]
    assert juego["completo"] is True and juego["siguiente"] is None
    assert [n["estrellas"] for n in juego["niveles"]] == [3, 3, 3]
    assert juego["xp"] == 30 + 40 + 50
    grafica = juego["grafica"]
    assert grafica["lista"] == INSERCION
    valores = {a["nombre"]: (a["comparaciones"], a["intercambios"]) for a in grafica["algoritmos"]}
    assert valores == {"Burbuja": (15, 9), "Selección": (15, 3), "Inserción": (12, 9)}
    # «Volver a jugar» empieza otro juego en el nivel 1
    assert client.get("/jugar/ordenar/").url == "/jugar/ordenar/1/"
    assert IntentoOrdenar.objects.filter(juego=2, nivel=1).exists()


@pytest.mark.django_db
def test_volver_a_jugar_da_listas_distintas(client):
    """Test 3 · RN06 y FA5: aunque el azar repita la lista, la del juego anterior se evita."""
    for numero in (1, 2, 3):
        intento = _abrir(client, numero)
        ordenar._azar.seed(7)
        _empezar(client, intento)
        _resolver(client, intento)
    anterior = IntentoOrdenar.objects.get(juego=1, nivel=1).lista_inicial
    client.get("/jugar/ordenar/")
    nuevo = _abrir(client, 1)
    ordenar._azar.seed(7)
    nuevo = _empezar(client, nuevo)
    assert nuevo.juego == 2 and nuevo.lista_inicial != anterior


@pytest.mark.django_db
def test_recargar_conserva_la_lista_y_el_paso(client):
    """Test 20 · FA6."""
    intento = _empezar(client, _abrir(client, 1), BURBUJA)
    _mover(client, intento, tipo="intercambiar", a=0, b=1)
    _mover(client, intento, tipo="intercambiar", a=1, b=2)
    _mover(client, intento, tipo="intercambiar", a=0, b=1)  # error
    mesa = _estado(client, 1)["mesa"]
    assert mesa["lista"] == [1, 4, 5, 2, 8] and mesa["paso"] == 2
    assert mesa["contadores"]["errores"] == 1 and mesa["contadores"]["intercambios"] == 2
    assert IntentoOrdenar.objects.count() == 1


@pytest.mark.django_db
def test_nivel_fuera_de_orden_redirige_al_que_sigue(client):
    """Test 21 · FE4 y RN07."""
    respuesta = client.get("/jugar/ordenar/3/")
    assert respuesta.status_code == 302 and respuesta.url == "/jugar/ordenar/1/"
    assert client.get("/jugar/ordenar/9/").status_code == 404


@pytest.mark.django_db
def test_movimiento_repetido_no_se_aplica_dos_veces(client):
    """Test 22 · Doble clic: el segundo envío es de un paso viejo y no cuenta como error."""
    intento = _empezar(client, _abrir(client, 1), BURBUJA)
    datos = {"paso": 0, "tipo": "intercambiar", "a": 0, "b": 1}
    assert _post(client, intento, "mover", datos).json()["ordenar"]["aplicado"] is True
    segunda = _post(client, intento, "mover", datos).json()["ordenar"]
    assert segunda["aplicado"] is False and segunda["desfasado"] is True
    intento.refresh_from_db()
    assert (intento.paso, intento.errores) == (1, 0)


@pytest.mark.django_db
def test_las_estrellas_aparecen_en_la_tarjeta_del_menu(client):
    """Test 23 · Postcondición."""
    intento = _empezar(client, _abrir(client, 1), BURBUJA)
    _mover(client, intento, tipo="intercambiar", a=3, b=4)  # un error: 2 estrellas
    _resolver(client, intento)
    menu = client.get("/jugar/").content.decode()
    assert "Continuar · Nivel 2" in menu
    assert 'aria-label="2 de 3 estrellas"' in menu


@pytest.mark.django_db
def test_movimiento_mal_formado_se_rechaza(client):
    intento = _empezar(client, _abrir(client, 1), BURBUJA)
    for datos in (
        {"tipo": "volar"},
        {"tipo": "intercambiar", "a": 0, "b": 9},
        {"tipo": "intercambiar", "a": 1, "b": 1},
    ):
        assert _post(client, intento, "mover", datos).status_code == 400
    sin_empezar = _abrir(client, 1)
    sin_empezar.lista = sin_empezar.lista_inicial = None
    sin_empezar.save()
    assert _post(client, sin_empezar, "mover", {"tipo": "ya"}).status_code == 409


@pytest.mark.django_db
def test_el_intento_es_solo_de_su_jugador(client, django_user_model):
    intento = _empezar(client, _abrir(client, 1), BURBUJA)
    otro = django_user_model.objects.create_user("otra", password="x")
    client.force_login(otro)
    assert _post(client, intento, "pista").status_code == 404
