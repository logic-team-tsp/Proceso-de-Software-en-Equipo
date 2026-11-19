"""Servicio del CU-09 Ordenar algoritmos.

El modo se abre desde el menu de modos y no depende de una partida. Tiene un nivel por algoritmo
(burbuja, seleccion e insercion) que se juegan en orden (RN07). En cada nivel el sistema genera
una lista al azar (RN06) y el jugador la ordena paso a paso tal como lo haria el algoritmo: cada
movimiento tiene que ser el que el algoritmo haria en ese momento (RN08).

  inicio()   -> «Jugar»: el nivel que sigue en el juego; si el juego ya acabo, empieza otro
  iniciar()  -> pasos 1 y 2: el intento del nivel (sin lista todavia: se ve la explicacion)
  empezar()  -> paso 3: genera la lista al azar
  mover()    -> pasos 4 a 6: revisa el movimiento; FE1 cuenta error, FE2 no, FE3 muestra el paso;
                al ordenar la lista califica (pasos 7 y 8, RN01 a RN05)
  pista()    -> FA1: resalta lo que compara el algoritmo y cuenta un error (RN02)
  salir()    -> FA4: el intento queda abandonado, sin XP

Los movimientos que tocan no se guardan ni se mandan al navegador: se calculan con la lista
inicial cada vez que hacen falta (traza). El contenido vive en app/data (RNF-MAN-07): la
explicacion, el pseudocodigo y el ejemplo de cada algoritmo en algoritmos.json y los niveles,
estrellas y XP en config_juego.json > ordenar_algoritmos.
"""

import json
import random

from django.db import transaction
from django.db.models import Max

from app.models import IntentoOrdenar

from . import escenarios

ALGORITMOS_PATH = escenarios.DATA_DIR / "algoritmos.json"
IMPLEMENTADOS = ("burbuja", "seleccion", "insercion")
INTERCAMBIAR, INSERTAR, YA = "intercambiar", "insertar", "ya"

_cache = {"firma": None, "resultado": None}
_azar = random.Random()  # listas al azar (las pruebas lo pueden sembrar)


class ReglaOrdenar(Exception):
    """El jugador intento algo que las reglas no permiten (la API responde 409)."""


class MovimientoInvalido(Exception):
    """El movimiento que mando el navegador no tiene la forma esperada (la API responde 400)."""


class FueraDeOrden(ReglaOrdenar):
    """Se pidio un nivel que no es el que sigue en el juego: la vista lleva al que sigue (FE4)."""

    def __init__(self, numero):
        super().__init__(f"Primero resuelve el nivel {numero}.")
        self.numero = numero


# ---------------------------------------------------------------- catalogo (contenido en JSON)
def _texto_ok(valor):
    return isinstance(valor, str) and valor.strip() != ""


def _entero(valor, minimo=0, maximo=None):
    if not isinstance(valor, int) or isinstance(valor, bool) or valor < minimo:
        return False
    return maximo is None or valor <= maximo


def _leer(ruta, errores):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errores.append(f"{ruta.name}: JSON invalido (linea {exc.lineno}): {exc.msg}")
    except OSError as exc:
        errores.append(f"{ruta.name}: no se pudo leer ({exc})")
    return None


def _validar_reglas(reglas, errores):
    donde = f"{escenarios.CONFIG_PATH.name} > ordenar_algoritmos"
    if not isinstance(reglas, dict):
        errores.append(f"{escenarios.CONFIG_PATH.name}: falta la clave 'ordenar_algoritmos'")
        return []
    estrellas = reglas.get("estrellas")
    if not isinstance(estrellas, list) or not estrellas:
        errores.append(f"{donde}: 'estrellas' debe ser una lista con al menos una regla")
    else:
        for regla in estrellas:
            if not isinstance(regla, dict) or not _entero(regla.get("estrellas"), 1, 5):
                errores.append(f"{donde}: cada regla necesita 'estrellas' de 1 a 5")
                continue
            if not _entero(regla.get("porcentaje_xp"), 0, 100):
                errores.append(f"{donde}: 'porcentaje_xp' debe ser de 0 a 100")
            fallos = regla.get("fallos_max")
            if fallos is not None and not _entero(fallos):
                errores.append(f"{donde}: 'fallos_max' debe ser un entero o null")
        if isinstance(estrellas[-1], dict) and estrellas[-1].get("fallos_max", 0) is not None:
            errores.append(f"{donde}: la ultima regla debe tener fallos_max: null")
    for clave in ("penalizacion_por_error", "penalizacion_maxima"):
        if not _entero(reglas.get(clave), 0, 100):
            errores.append(f"{donde}: '{clave}' debe ser de 0 a 100")
    for clave in ("errores_por_paso", "estrellas_si_se_muestra", "movimientos_minimos"):
        if not _entero(reglas.get(clave), 1):
            errores.append(f"{donde}: '{clave}' debe ser un entero mayor que 0")
    minimo, maximo = reglas.get("minimo"), reglas.get("maximo")
    if not _entero(minimo) or not _entero(maximo) or maximo <= minimo:
        errores.append(f"{donde}: 'minimo' y 'maximo' deben ser enteros con minimo < maximo")
        minimo, maximo = 0, 0

    niveles = reglas.get("niveles")
    if not isinstance(niveles, list) or not niveles:
        errores.append(f"{donde}: 'niveles' debe ser una lista con al menos un nivel")
        return []
    validos = []
    for nivel_ in niveles:
        if not isinstance(nivel_, dict):
            errores.append(f"{donde}: cada nivel debe ser un objeto")
            continue
        numero = nivel_.get("numero")
        if (
            not _entero(numero, 1)
            or any(n["numero"] == numero for n in validos)
            or nivel_.get("algoritmo") not in IMPLEMENTADOS
            or not _entero(nivel_.get("xp_base"), 0)
            or not _entero(nivel_.get("numeros"), 3, 12)
        ):
            errores.append(
                f"{donde}: cada nivel necesita 'numero' unico, 'algoritmo' "
                f"({', '.join(IMPLEMENTADOS)}), 'xp_base' y 'numeros' de 3 a 12"
            )
            continue
        if maximo - minimo + 1 < nivel_["numeros"]:
            errores.append(f"{donde}: no caben {nivel_['numeros']} numeros sin repetir")
        validos.append(nivel_)
    return sorted(validos, key=lambda n: n["numero"])


def _validar_algoritmo(datos, errores):
    donde = f"{ALGORITMOS_PATH.name} > {datos.get('id', '?')}"
    antes = len(errores)
    for campo in ("id", "nombre", "explicacion", "como_se_juega", "indicacion"):
        if not _texto_ok(datos.get(campo)):
            errores.append(f"{donde}: falta '{campo}'")
    pseudo = datos.get("pseudocodigo")
    if not isinstance(pseudo, list) or not pseudo or not all(_texto_ok(x) for x in pseudo):
        errores.append(f"{donde}: 'pseudocodigo' debe ser una lista de lineas")
    elif not _entero(datos.get("linea_actual"), 0, len(pseudo) - 1):
        errores.append(f"{donde}: 'linea_actual' debe ser una linea del pseudocodigo")
    ejemplo = datos.get("ejemplo")
    if not isinstance(ejemplo, list) or not ejemplo:
        errores.append(f"{donde}: 'ejemplo' debe ser una lista de pasos")
    else:
        for paso in ejemplo:
            lista = paso.get("lista") if isinstance(paso, dict) else None
            if (
                not isinstance(lista, list)
                or not all(_entero(x) for x in lista)
                or not _texto_ok(paso.get("texto"))
                or not all(
                    isinstance(paso.get(k, []), list)
                    and all(_entero(i, 0, len(lista) - 1) for i in paso.get(k, []))
                    for k in ("comp", "ord")
                )
            ):
                errores.append(f"{donde}: cada paso del ejemplo necesita 'lista', 'comp', 'ord'")
                break
    return len(errores) == antes


def _archivos():
    return [escenarios.CONFIG_PATH, ALGORITMOS_PATH]


def _firma():
    return tuple((str(r), r.stat().st_mtime_ns) for r in _archivos() if r.exists())


def _construir():
    errores = []
    config = _leer(escenarios.CONFIG_PATH, errores) or {}
    reglas = config.get("ordenar_algoritmos")
    niveles = _validar_reglas(reglas, errores)
    contenido = _leer(ALGORITMOS_PATH, errores) or {}
    algoritmos = {}
    for datos in contenido.get("algoritmos") or []:
        if not isinstance(datos, dict):
            errores.append(f"{ALGORITMOS_PATH.name}: cada algoritmo debe ser un objeto")
            continue
        if datos.get("id") in algoritmos:
            errores.append(f"{ALGORITMOS_PATH.name}: id de algoritmo repetido")
            continue
        if _validar_algoritmo(datos, errores):
            algoritmos[datos["id"]] = datos
    for nivel_ in niveles:
        if nivel_["algoritmo"] not in algoritmos:
            errores.append(
                f"{ALGORITMOS_PATH.name}: falta el algoritmo '{nivel_['algoritmo']}' del "
                f"nivel {nivel_['numero']}"
            )
    return {"reglas": reglas, "niveles": niveles, "algoritmos": algoritmos}, errores


def validar():
    """Errores de las reglas y del contenido de los algoritmos (vacia si todo esta bien)."""
    return _construir()[1]


def cargar():
    """Devuelve {"reglas", "niveles", "algoritmos"}. Lanza escenarios.CatalogoError."""
    firma = _firma()
    if _cache["firma"] != firma:
        _cache["firma"] = firma
        _cache["resultado"] = _construir()
    catalogo, errores = _cache["resultado"]
    if errores:
        raise escenarios.CatalogoError(errores)
    return catalogo


def nivel_info(numero):
    return next((n for n in cargar()["niveles"] if n["numero"] == numero), None)


def _numeros():
    return [n["numero"] for n in cargar()["niveles"]]


# ---------------------------------------------------------------- algoritmos (RN08)
# La traza es la lista de movimientos que haria el algoritmo, en orden. Cada movimiento lleva
# lo que hace falta para revisarlo y para la mesa: la lista despues de hacerlo, los contadores
# despues de hacerlo, las posiciones que ya estaban ordenadas antes y las que compara el
# algoritmo en ese momento (para la pista).
def _burbuja(lista):
    a, movs, comp, inter = list(lista), [], 0, 0
    n = len(a)
    for i in range(n - 1):
        for j in range(n - 1 - i):
            comp += 1
            if a[j] > a[j + 1]:
                a[j], a[j + 1] = a[j + 1], a[j]
                inter += 1
                movs.append(
                    {
                        "tipo": INTERCAMBIAR,
                        "a": j,
                        "b": j + 1,
                        "pasada": i + 1,
                        "ordenadas": list(range(n - i, n)),
                        "comparando": [j, j + 1],
                        "turno": None,
                        "lista": list(a),
                        "comparaciones": comp,
                        "intercambios": inter,
                    }
                )
    return movs, comp, inter


def _seleccion(lista):
    a, movs, comp, inter = list(lista), [], 0, 0
    n = len(a)
    for i in range(n - 1):
        menor = i
        for j in range(i + 1, n):
            comp += 1
            if a[j] < a[menor]:
                menor = j
        mov = {
            "pasada": i + 1,
            "ordenadas": list(range(i)),
            "comparando": [i, menor] if menor != i else [i],
            "turno": i,
        }
        if menor == i:
            mov.update({"tipo": YA, "i": i})
        else:
            a[i], a[menor] = a[menor], a[i]
            inter += 1
            mov.update({"tipo": INTERCAMBIAR, "a": i, "b": menor})
        mov.update({"lista": list(a), "comparaciones": comp, "intercambios": inter})
        movs.append(mov)
    return movs, comp, inter


def _insercion(lista):
    """Cada corrimiento a la derecha cuenta como intercambio."""
    a, movs, comp, inter = list(lista), [], 0, 0
    n = len(a)
    for i in range(1, n):
        clave, j = a[i], i
        while j > 0:
            comp += 1
            if a[j - 1] > clave:
                inter += 1
                j -= 1
            else:
                break
        mov = {
            "pasada": i,
            "ordenadas": list(range(i)),
            "comparando": [i - 1, i] if j == i else [j, i],
            "turno": i,
        }
        if j == i:
            mov.update({"tipo": YA, "i": i})
        else:
            a.insert(j, a.pop(i))
            mov.update({"tipo": INSERTAR, "desde": i, "hasta": j})
        mov.update({"lista": list(a), "comparaciones": comp, "intercambios": inter})
        movs.append(mov)
    return movs, comp, inter


TRAZAS = {"burbuja": _burbuja, "seleccion": _seleccion, "insercion": _insercion}


def traza(algoritmo, lista):
    """{"movimientos": [...], "comparaciones": total, "intercambios": total} del algoritmo."""
    movs, comp, inter = TRAZAS[algoritmo](lista)
    return {"movimientos": movs, "comparaciones": comp, "intercambios": inter}


def generar_lista(nivel_, reglas, evitar=()):
    """RN06: numeros al azar sin repetir, nunca ya ordenada y con al menos N movimientos."""
    rango = range(reglas["minimo"], reglas["maximo"] + 1)
    for _ in range(500):
        lista = _azar.sample(rango, nivel_["numeros"])
        if lista == sorted(lista) or lista in evitar:
            continue
        if len(traza(nivel_["algoritmo"], lista)["movimientos"]) >= reglas["movimientos_minimos"]:
            return lista
    raise escenarios.CatalogoError(["No se pudo generar una lista que cumpla RN06"])


# ---------------------------------------------------------------- movimientos del navegador
def leer_movimiento(datos, tamano):
    """Movimiento del navegador: {"tipo": "intercambiar", "a", "b"}, {"tipo": "insertar",
    "desde", "hasta"} o {"tipo": "ya"}."""
    if not isinstance(datos, dict):
        raise MovimientoInvalido("El movimiento no tiene un formato válido.")
    tipo = datos.get("tipo")
    if tipo == YA:
        return {"tipo": YA}
    claves = {INTERCAMBIAR: ("a", "b"), INSERTAR: ("desde", "hasta")}.get(tipo)
    if claves is None:
        raise MovimientoInvalido("El movimiento no tiene un formato válido.")
    x, y = (datos.get(k) for k in claves)
    if not _entero(x, 0, tamano - 1) or not _entero(y, 0, tamano - 1) or x == y:
        raise MovimientoInvalido("Esas tarjetas no existen.")
    if tipo == INTERCAMBIAR:
        return {"tipo": tipo, "a": min(x, y), "b": max(x, y)}
    return {"tipo": tipo, "desde": x, "hasta": y}


def no_permitido(algoritmo, mov, esperado):
    """FE2: aviso si el movimiento es de los que ese algoritmo nunca hace (si no, None)."""
    tipo = mov["tipo"]
    if algoritmo == "burbuja":
        if tipo == INTERCAMBIAR and mov["b"] - mov["a"] == 1:
            return None
        if tipo == INTERCAMBIAR:
            return "En burbuja solo se intercambian tarjetas vecinas."
        if tipo == YA:
            return (
                "En burbuja no se usa «Ya está en su lugar»: intercambia el siguiente par de "
                "vecinos desordenado."
            )
        return (
            "En burbuja no se mete una tarjeta entre otras: se intercambian dos tarjetas vecinas."
        )
    if algoritmo == "seleccion":
        if tipo == INSERTAR:
            return "En selección no se mete una tarjeta entre otras: se intercambian dos tarjetas."
        return None
    # insercion
    if tipo == INTERCAMBIAR:
        return "En inserción no se intercambian tarjetas: se toma una y se mete en su lugar."
    if tipo == INSERTAR and mov["hasta"] > mov["desde"]:
        return "En inserción las tarjetas se meten hacia la izquierda, dentro de la parte ordenada."
    if tipo == INSERTAR and esperado is not None and mov["hasta"] > esperado["turno"]:
        return (
            "En inserción la tarjeta se mete dentro de la parte ordenada, no en la parte "
            "sin ordenar."
        )
    return None


def _igual(mov, esperado):
    if mov["tipo"] != esperado["tipo"]:
        return False
    if mov["tipo"] == INTERCAMBIAR:
        return (mov["a"], mov["b"]) == (esperado["a"], esperado["b"])
    if mov["tipo"] == INSERTAR:
        return (mov["desde"], mov["hasta"]) == (esperado["desde"], esperado["hasta"])
    return True


def explicar(algoritmo, mov, esperado, lista):
    """FE1: por qué el movimiento no es el que haría el algoritmo."""
    L = lista
    if algoritmo == "burbuja":
        a, b = mov["a"], mov["b"]
        if L[a] < L[b]:
            return f"{L[a]} y {L[b]} ya están en orden: la burbuja no los intercambia."
        return (
            "La burbuja compara vecinos de izquierda a derecha: antes toca el par "
            f"{L[esperado['a']]} y {L[esperado['b']]}."
        )
    i = esperado["turno"]
    if algoritmo == "seleccion":
        if esperado["tipo"] == YA:
            return f"{L[i]} ya es el menor de la parte sin ordenar: presiona «Ya está en su lugar»."
        if mov["tipo"] == YA:
            return f"{L[i]} no es el menor de la parte sin ordenar: todavía hay que moverlo."
        if i not in (mov["a"], mov["b"]):
            return f"Toca acomodar el lugar {i + 1}: ahí va el menor de la parte sin ordenar."
        otro = mov["b"] if mov["a"] == i else mov["a"]
        return f"{L[otro]} no es el menor de la parte sin ordenar."
    # insercion
    x = L[i]
    if esperado["tipo"] == YA:
        return (
            f"El {x} es mayor que el {L[i - 1]}: ya está en su lugar. "
            "Presiona «Ya está en su lugar»."
        )
    if mov["tipo"] == YA:
        return f"El {x} es menor que el {L[i - 1]}: hay que meterlo más a la izquierda."
    if mov["desde"] != i:
        return f"Toca tomar el {x}: el primer número de la parte sin ordenar."
    if mov["hasta"] > esperado["hasta"]:
        return f"El {x} es menor que el {L[mov['hasta'] - 1]}: va más a la izquierda."
    return f"El {x} es mayor que el {L[mov['hasta']]}: va más a la derecha."


def texto_pista(algoritmo, esperado, lista, linea):
    L, c = lista, esperado["comparando"]
    if algoritmo == "burbuja":
        return f"La burbuja está comparando {L[c[0]]} y {L[c[1]]} (línea {linea}). ¿Están en orden?"
    if algoritmo == "seleccion":
        if esperado["tipo"] == YA:
            return (
                f"El menor que encontró el algoritmo es el {L[c[0]]}, que ya está en el "
                f"lugar {c[0] + 1} (línea {linea})."
            )
        return (
            f"El algoritmo encontró que el menor de la parte sin ordenar es el {L[c[1]]} "
            f"(línea {linea})."
        )
    return (
        f"El algoritmo toma el {L[esperado['turno']]} y lo compara con los de su izquierda "
        f"(línea {linea})."
    )


# ---------------------------------------------------------------- calificar (RN01 a RN05)
def penalizacion(errores, reglas):
    return min(reglas["penalizacion_maxima"], errores * reglas["penalizacion_por_error"])


def calificar(errores, mostrado, xp_base, reglas):
    """Estrellas según los errores (FE3 limita las estrellas) y XP con penalización."""
    regla = next(
        r for r in reglas["estrellas"] if r["fallos_max"] is None or errores <= r["fallos_max"]
    )
    if mostrado and regla["estrellas"] > reglas["estrellas_si_se_muestra"]:
        regla = next(
            r for r in reglas["estrellas"] if r["estrellas"] <= reglas["estrellas_si_se_muestra"]
        )
    castigo = penalizacion(errores, reglas)
    base = round(xp_base * regla["porcentaje_xp"] / 100)
    return {
        "estrellas": regla["estrellas"],
        "estrellas_max": max(r["estrellas"] for r in reglas["estrellas"]),
        "xp_nivel": xp_base,
        "xp_base": base,
        "porcentaje_xp": regla["porcentaje_xp"],
        "errores": errores,
        "mostrado": mostrado,
        "penalizacion": castigo,
        "xp": round(base * (100 - castigo) / 100),
    }


# ---------------------------------------------------------------- juegos del jugador
def _de_jugador(jugador):
    return IntentoOrdenar.objects.filter(**jugador.filtro())


def _del_dueno(intento):
    if intento.usuario_id:
        return IntentoOrdenar.objects.filter(usuario_id=intento.usuario_id)
    return IntentoOrdenar.objects.filter(usuario__isnull=True, sesion=intento.sesion)


def _juego(intentos):
    """(numero del juego en curso, {nivel: intento resuelto}, nivel que sigue o None)."""
    juego = intentos.aggregate(ultimo=Max("juego"))["ultimo"] or 1
    resueltos = {}
    for intento in intentos.filter(juego=juego, estado=IntentoOrdenar.RESUELTO):
        resueltos.setdefault(intento.nivel, intento)
    siguiente = next((n for n in _numeros() if n not in resueltos), None)
    return juego, resueltos, siguiente


def _nombre(algoritmo):
    return cargar()["algoritmos"][algoritmo]["nombre"]


def resumen_juego(intentos):
    """Avance del juego en curso; si se completó, el total y la gráfica de FA5."""
    catalogo = cargar()
    juego, resueltos, siguiente = _juego(intentos)
    maximo = max(r["estrellas"] for r in catalogo["reglas"]["estrellas"])
    niveles = []
    for n in catalogo["niveles"]:
        hecho = resueltos.get(n["numero"])
        estado = "hecho" if hecho else ("actual" if n["numero"] == siguiente else "pendiente")
        niveles.append(
            {
                "numero": n["numero"],
                "nombre": _nombre(n["algoritmo"]),
                "estado": estado,
                "estrellas": (hecho.estrellas or 0) if hecho else 0,
                "xp": hecho.xp_obtenida if hecho else 0,
            }
        )
    resumen = {
        "numero": juego,
        "completo": siguiente is None,
        "siguiente": siguiente,
        "niveles": niveles,
        "estrellas": sum(n["estrellas"] for n in niveles),
        "estrellas_max": maximo * len(niveles),
        "xp": sum(n["xp"] for n in niveles),
        "grafica": None,
    }
    if resumen["completo"]:
        # FA5: lo que haría cada algoritmo con la lista del último nivel
        lista = resueltos[catalogo["niveles"][-1]["numero"]].lista_inicial
        algoritmos = []
        for n in catalogo["niveles"]:
            t = traza(n["algoritmo"], lista)
            algoritmos.append(
                {
                    "nombre": _nombre(n["algoritmo"]),
                    "comparaciones": t["comparaciones"],
                    "intercambios": t["intercambios"],
                }
            )
        resumen["grafica"] = {"lista": lista, "algoritmos": algoritmos}
    return resumen


def estrellas_ganadas(jugador):
    """CU07-RN01: suma de la mejor calificación de cada nivel, en cualquier juego.

    Repetir un nivel con el mismo resultado no suma; mejorarlo suma solo la diferencia.
    """
    mejores = {}
    resueltos = _de_jugador(jugador).filter(estado=IntentoOrdenar.RESUELTO)
    for nivel, estrellas in resueltos.values_list("nivel", "estrellas"):
        mejores[nivel] = max(mejores.get(nivel, 0), estrellas or 0)
    return sum(mejores.values())


def resumen_jugador(jugador):
    """Para la tarjeta del menú de modos: el avance del juego en curso."""
    return resumen_juego(_de_jugador(jugador))


def _crear(jugador, numero, juego):
    nivel_ = nivel_info(numero)
    return IntentoOrdenar.objects.create(
        juego=juego, nivel=numero, algoritmo=nivel_["algoritmo"], **jugador.campos()
    )


@transaction.atomic
def inicio(jugador):
    """«Jugar»: el nivel que sigue; si el juego ya acabó, empieza otro en el nivel 1 (FA5)."""
    juego, _, siguiente = _juego(_de_jugador(jugador))
    if siguiente is None:
        siguiente = _numeros()[0]
        _crear(jugador, siguiente, juego + 1)
    return siguiente


@transaction.atomic
def iniciar(jugador, numero):
    """Pasos 1 y 2: el intento del nivel en el juego en curso.

    Un nivel ya resuelto muestra su resultado. El nivel que sigue retoma su intento en curso
    (FA6: la misma lista en el mismo paso) o abre uno nuevo. Otro nivel no se puede abrir (FE4).
    """
    if nivel_info(numero) is None:
        raise ReglaOrdenar("Ese nivel no existe.")
    juego, resueltos, siguiente = _juego(_de_jugador(jugador))
    if numero in resueltos:
        return resueltos[numero]
    if numero != siguiente:
        raise FueraDeOrden(siguiente)
    ultimo = _de_jugador(jugador).filter(juego=juego, nivel=numero).first()
    if ultimo is not None and ultimo.estado == IntentoOrdenar.EN_CURSO:
        return ultimo
    return _crear(jugador, numero, juego)


def _en_curso(intento, empezado=True):
    if intento.estado == IntentoOrdenar.RESUELTO:
        raise ReglaOrdenar("Ya resolviste este nivel. Sigue con el siguiente.")
    if intento.estado != IntentoOrdenar.EN_CURSO:
        raise ReglaOrdenar("Saliste de este nivel. Vuelve a abrir el modo desde el menú.")
    if empezado and intento.lista is None:
        raise ReglaOrdenar("Primero presiona «Empezar».")
    catalogo = cargar()
    nivel_ = nivel_info(intento.nivel)
    if nivel_ is None or nivel_["algoritmo"] != intento.algoritmo:
        raise ReglaOrdenar("Este nivel ya no existe.")
    return catalogo, nivel_


def empezar(intento):
    """Paso 3: genera la lista al azar, distinta a la del mismo nivel en el juego anterior."""
    catalogo, nivel_ = _en_curso(intento, empezado=False)
    if intento.lista is None:
        anteriores = list(
            _del_dueno(intento)
            .filter(nivel=intento.nivel, lista_inicial__isnull=False)
            .exclude(pk=intento.pk)
            .values_list("lista_inicial", flat=True)[:5]
        )
        lista = generar_lista(nivel_, catalogo["reglas"], evitar=anteriores)
        intento.lista_inicial = lista
        intento.lista = list(lista)
        intento.save(update_fields=["lista_inicial", "lista", "actualizado"])
    return estado_publico(intento)


def _contadores(intento, t):
    if intento.estado == IntentoOrdenar.RESUELTO or intento.paso >= len(t["movimientos"]):
        comp, inter = t["comparaciones"], t["intercambios"]
    elif intento.paso:
        anterior = t["movimientos"][intento.paso - 1]
        comp, inter = anterior["comparaciones"], anterior["intercambios"]
    else:
        comp = inter = 0
    return {"comparaciones": comp, "intercambios": inter, "errores": intento.errores}


def mesa(intento):
    """Lo que dibuja la mesa de trabajo: lista, parte ordenada, turno, avance y contadores."""
    if intento.lista is None:
        return None
    catalogo = cargar()
    algoritmo = catalogo["algoritmos"][intento.algoritmo]
    t = traza(intento.algoritmo, intento.lista_inicial)
    movs = t["movimientos"]
    n = len(intento.lista)
    if intento.estado == IntentoOrdenar.RESUELTO or intento.paso >= len(movs):
        ordenadas, turno, indicacion = list(range(n)), None, "La lista quedó ordenada"
    else:
        sig = movs[intento.paso]
        ordenadas, turno = sig["ordenadas"], sig["turno"]
        indicacion = algoritmo["indicacion"].format(
            pasada=sig["pasada"], lugar=sig["pasada"], paso=sig["pasada"], total=n - 1
        )
    return {
        "lista": intento.lista,
        "ordenadas": ordenadas,
        "turno": turno,
        "indicacion": indicacion,
        "linea": algoritmo["linea_actual"],
        "contadores": _contadores(intento, t),
        "paso": intento.paso,
    }


def estado_publico(intento):
    """Lo que necesita la página (ordenar.html). Sin los movimientos de la solución."""
    catalogo = cargar()
    nivel_ = nivel_info(intento.nivel)
    algoritmo = catalogo["algoritmos"][intento.algoritmo]
    reglas = catalogo["reglas"]
    return {
        "intento_id": str(intento.id),
        "estado": intento.estado,
        "empezado": intento.lista is not None,
        "nivel": {
            "numero": intento.nivel,
            "nombre": algoritmo["nombre"],
            "algoritmo": intento.algoritmo,
            "xp_base": nivel_["xp_base"],
            "numeros": nivel_["numeros"],
        },
        "algoritmo": {
            k: algoritmo[k]
            for k in ("explicacion", "como_se_juega", "pseudocodigo", "linea_actual", "ejemplo")
        },
        "juego": resumen_juego(_del_dueno(intento)),
        "mesa": mesa(intento),
        "penalizacion_por_error": reglas["penalizacion_por_error"],
        "penalizacion_maxima": reglas["penalizacion_maxima"],
        "errores_por_paso": reglas["errores_por_paso"],
        "resultado": intento.resultado if intento.estado == IntentoOrdenar.RESUELTO else None,
    }


def _resolver(intento, nivel_, reglas, t):
    calificacion = calificar(intento.errores, intento.mostrado, nivel_["xp_base"], reglas)
    calificacion.update(
        {
            "pistas": intento.pistas,
            "comparaciones": t["comparaciones"],
            "intercambios": t["intercambios"],
            "lista_inicial": intento.lista_inicial,
            "lista": intento.lista,
        }
    )
    intento.estado = IntentoOrdenar.RESUELTO
    intento.estrellas = calificacion["estrellas"]
    intento.xp_obtenida = calificacion["xp"]
    intento.resultado = calificacion
    return calificacion


def mover(intento, datos):
    """Pasos 4 a 8: revisa el movimiento contra el que haría el algoritmo (RN08)."""
    catalogo, nivel_ = _en_curso(intento)
    reglas = catalogo["reglas"]
    t = traza(intento.algoritmo, intento.lista_inicial)
    movs = t["movimientos"]
    paso = datos.get("paso") if isinstance(datos, dict) else None
    if paso is not None and paso != intento.paso:
        # Doble clic o dos pestañas: el movimiento era de otro paso, no cuenta como error
        return {"aplicado": False, "desfasado": True, "mesa": mesa(intento)}
    mov = leer_movimiento(datos, len(intento.lista))
    esperado = movs[intento.paso] if intento.paso < len(movs) else None
    aviso = no_permitido(intento.algoritmo, mov, esperado)
    if aviso:  # FE2: no cuenta como error
        return {"aplicado": False, "permitido": False, "aviso": aviso, "mesa": mesa(intento)}

    respuesta = {"aplicado": True, "permitido": True, "correcto": True, "mostrado": False}
    if not _igual(mov, esperado):
        intento.errores += 1  # FE1, RN02
        intento.errores_paso += 1
        explicacion = explicar(intento.algoritmo, mov, esperado, intento.lista)
        if intento.errores_paso < reglas["errores_por_paso"]:
            intento.save(update_fields=["errores", "errores_paso", "actualizado"])
            return {
                "aplicado": False,
                "permitido": True,
                "correcto": False,
                "explicacion": explicacion,
                "errores_paso": intento.errores_paso,
                "mesa": mesa(intento),
            }
        # FE3: al tercer error en el mismo paso el sistema muestra el movimiento correcto
        intento.mostrado = True
        respuesta.update({"correcto": False, "mostrado": True, "explicacion": explicacion})

    anterior = list(intento.lista)
    intento.lista = esperado["lista"]
    intento.paso += 1
    intento.errores_paso = 0
    respuesta["movimiento"] = {
        k: esperado[k] for k in ("tipo", "a", "b", "desde", "hasta", "i") if k in esperado
    }
    respuesta["antes"] = anterior
    calificacion = None
    if intento.paso >= len(movs):
        calificacion = _resolver(intento, nivel_, reglas, t)
    intento.save()
    respuesta.update(
        {
            "mesa": mesa(intento),
            "terminado": calificacion is not None,
            "resultado": calificacion,
            "juego": resumen_juego(_del_dueno(intento)) if calificacion else None,
        }
    )
    return respuesta


def pista(intento):
    """FA1: lo que compara el algoritmo y su línea, sin mover nada. Cuenta como error."""
    catalogo, _ = _en_curso(intento)
    t = traza(intento.algoritmo, intento.lista_inicial)
    esperado = t["movimientos"][intento.paso]
    algoritmo = catalogo["algoritmos"][intento.algoritmo]
    intento.errores += 1
    intento.pistas += 1
    intento.save(update_fields=["errores", "pistas", "actualizado"])
    linea = algoritmo["linea_actual"]
    return {
        "comparando": esperado["comparando"],
        "linea": linea,
        "texto": texto_pista(intento.algoritmo, esperado, intento.lista, linea + 1),
        "mesa": mesa(intento),
    }


def salir(intento):
    """FA4: se pierde el avance del nivel y no se gana XP. Un intento resuelto no cambia."""
    if intento.estado == IntentoOrdenar.EN_CURSO:
        intento.estado = IntentoOrdenar.ABANDONADO
        intento.save(update_fields=["estado", "actualizado"])
    return intento
