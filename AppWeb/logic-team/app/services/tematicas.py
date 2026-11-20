"""CU-07 Comprar nuevos módulos temáticos de partida: catálogo, saldo, compras y glosario.

Flujo (especificación CU-07):
  A. Comprar   el jugador abre la tienda (tienda()) -> ve el saldo (RN01) y el catálogo con el
               estado de cada temática -> abre la vista previa (vista_previa()) -> confirma ->
               comprar() vuelve a validar el saldo, descuenta y registra en una sola
               transacción (RN02, RN03, FE1 a FE3).
  B. Jugar     CU-02 ofrece la Clásica y las temáticas adquiridas (adquiridas()); la partida
               guarda la elegida (para_partida(), FE5) y el libro del CU-01 la aplica con
               tematizar_estado() a los eventos, desenlaces y títulos de capítulo (RN04, RN05).

Una temática solo cambia la narrativa (RN04): reemplaza los términos de su glosario (RN05) y
los nombres de los capítulos. Los eventos, opciones, respuestas, probabilidades, vidas, XP,
puntuación y tecnicismos son los mismos, porque el texto se cambia solo al mostrarlo.

El catálogo vive en app/data/tematicas/*.json, separado del código como los escenarios, y se
valida con el comando validar_escenarios. clasica.json define los términos reemplazables;
cada temática da el reemplazo de cada uno. Una temática con errores no aparece en la tienda y
una partida que ya la tenía se narra con la Clásica (FE4).
"""

import json
import logging
import re

from django.db import IntegrityError, transaction
from django.db.models import Sum

from app.models import CompraTematica, MonederoTienda

from . import escenarios, minijuego_codigo, ordenar

logger = logging.getLogger(__name__)

TEMATICAS_DIR = escenarios.DATA_DIR / "tematicas"
CLASICA = "clasica"
CLASICA_PATH = TEMATICAS_DIR / "clasica.json"
CAMPOS_TEXTO = ("id", "nombre", "icono", "descripcion", "vista_previa")

_cache = {"firma": None, "resultado": None}


class CatalogoError(Exception):
    """No se pudo leer el catálogo de temáticas (FE6)."""

    def __init__(self, errores):
        self.errores = list(errores)
        super().__init__("; ".join(self.errores))


class TematicaDesconocida(Exception):
    """La temática no existe o tiene errores (FE4)."""


class EstrellasInsuficientes(Exception):
    """El saldo no alcanza para el precio (FA1, FE3)."""

    def __init__(self, faltan, saldo):
        self.faltan = faltan
        self.saldo = saldo
        super().__init__(f"Te faltan {faltan} estrellas.")


# ---------------------------------------------------------------- texto (RN04, RN05)
def _mayusculas_como(original, reemplazo):
    """El reemplazo respeta las mayúsculas del texto: «El cliente» -> «El rey» y en un título
    «del Cliente» -> «del Rey»."""
    if not original or not reemplazo:
        return reemplazo
    palabras = reemplazo.split(" ")
    if original[0].isupper():
        palabras[0] = palabras[0][:1].upper() + palabras[0][1:]
    ultima = original.split(" ")[-1]
    if len(original.split(" ")) > 1 and ultima[:1].isupper():
        palabras[-1] = palabras[-1][:1].upper() + palabras[-1][1:]
    return " ".join(palabras)


def _expresion(formas):
    """Una sola expresión con todas las formas, las largas primero («tu líder técnica» antes
    que «tu líder»), como palabras completas y sin importar mayúsculas."""
    ordenadas = sorted(formas, key=len, reverse=True)
    return re.compile(
        r"(?<!\w)(" + "|".join(re.escape(f) for f in ordenadas) + r")(?!\w)", re.IGNORECASE
    )


def _segmentos(texto, tematica):
    """Parte el texto en trozos [(texto, es_termino)] y cambia cada término por su reemplazo."""
    texto = texto or ""
    reglas = tematica["_reglas"]
    trozos, inicio = [], 0
    for m in tematica["_expresion"].finditer(texto):
        if m.start() > inicio:
            trozos.append((texto[inicio : m.start()], False))
        original = m.group(0)
        trozos.append((_mayusculas_como(original, reglas[original.lower()]), True))
        inicio = m.end()
    if inicio < len(texto):
        trozos.append((texto[inicio:], False))
    return trozos


def aplicar_texto(texto, tematica):
    """El texto con el glosario de la temática (un dict del catálogo) aplicado."""
    if not texto or tematica["id"] == CLASICA:
        return texto
    return "".join(t for t, _ in _segmentos(texto, tematica))


# ---------------------------------------------------------------- catálogo
def _archivos():
    return sorted(TEMATICAS_DIR.glob("*.json")) if TEMATICAS_DIR.exists() else []


def _firma():
    return tuple((str(r), r.stat().st_mtime_ns) for r in _archivos())


def _leer(ruta, errores):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errores.append(f"tematicas/{ruta.name}: JSON inválido (línea {exc.lineno}): {exc.msg}")
    except OSError as exc:
        errores.append(f"tematicas/{ruta.name}: no se pudo leer ({exc})")
    return None


def _texto_ok(valor):
    return isinstance(valor, str) and valor.strip() != ""


def _entero(valor, minimo=0):
    return isinstance(valor, int) and not isinstance(valor, bool) and valor >= minimo


def _validar_comun(datos, donde, errores, eventos):
    for campo in CAMPOS_TEXTO:
        if not _texto_ok(datos.get(campo)):
            errores.append(f"{donde}: falta '{campo}'")
    if not _entero(datos.get("precio")):
        errores.append(f"{donde}: 'precio' debe ser un entero de 0 o más estrellas (RN02)")
    if not _entero(datos.get("orden")):
        errores.append(f"{donde}: 'orden' debe ser un entero")
    evento = eventos.get(datos.get("vista_previa"))
    if eventos and evento is None:
        errores.append(
            f"{donde}: el evento de la vista previa '{datos.get('vista_previa')}' no existe"
        )


def _validar_terminos(terminos, formas_tec, donde, errores):
    if not isinstance(terminos, dict) or not terminos:
        errores.append(f"{donde}: 'terminos' debe tener al menos un término reemplazable")
        return
    vistas = set()
    for termino, formas in terminos.items():
        if not isinstance(formas, list) or not formas or not all(_texto_ok(f) for f in formas):
            errores.append(f"{donde}: el término '{termino}' necesita una lista de formas")
            continue
        for forma in formas:
            if forma != forma.lower():
                errores.append(f"{donde}: la forma '{forma}' debe ir en minúsculas")
            if forma in vistas:
                errores.append(f"{donde}: la forma '{forma}' está repetida")
            vistas.add(forma)
            # RN05: los términos técnicos y los tecnicismos nunca se reemplazan
            choca = [
                t for t in formas_tec if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", forma)
            ]
            if choca:
                errores.append(f"{donde}: la forma '{forma}' contiene el tecnicismo '{choca[0]}'")


def _validar_tematica(datos, terminos, capitulos, donde, errores):
    if datos.get("id") == CLASICA:
        errores.append(f"{donde}: el id 'clasica' es solo para clasica.json")
    if datos.get("precio") == 0:
        errores.append(f"{donde}: solo la Clásica es gratis (RN02)")
    glosario = datos.get("glosario")
    if not isinstance(glosario, dict):
        errores.append(f"{donde}: falta el 'glosario' (RN05)")
        glosario = {}
    for termino, formas in terminos.items():
        reemplazos = glosario.get(termino)
        if not isinstance(reemplazos, dict):
            errores.append(f"{donde}: al glosario le falta el término '{termino}'")
            continue
        for forma in formas:
            if not _texto_ok(reemplazos.get(forma)):
                errores.append(f"{donde}: al glosario le falta el reemplazo de '{forma}'")
    sobran = set(glosario) - set(terminos)
    if sobran:
        errores.append(f"{donde}: el glosario tiene términos que no están en clasica.json: "
                       f"{', '.join(sorted(sobran))}")
    nombres = datos.get("capitulos")
    if not isinstance(nombres, dict) or any(not _texto_ok(nombres.get(c)) for c in capitulos):
        errores.append(f"{donde}: 'capitulos' necesita un nombre para los capítulos "
                       f"{', '.join(capitulos)}")
    portada = datos.get("portada")
    color = str(portada.get("color")) if isinstance(portada, dict) else ""
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        errores.append(f"{donde}: 'portada.color' debe ser un color como #5b3a1a")


def _preparar(datos, terminos):
    """Agrega al dict de la temática lo que hace falta para aplicar el glosario rápido."""
    formas = [f for lista in terminos.values() for f in lista]
    if datos["id"] == CLASICA:
        reglas = {f: f for f in formas}
    else:
        reglas = {f: datos["glosario"][t][f] for t, lista in terminos.items() for f in lista}
    return {**datos, "_reglas": reglas, "_expresion": _expresion(formas)}


def _construir():
    errores = []
    try:
        config, catalogo_esc = escenarios.cargar()
    except escenarios.CatalogoError:
        config, catalogo_esc = None, {"eventos": {}, "tecnicismos": {}}
    eventos = catalogo_esc["eventos"]
    formas_tec = {f.lower() for t in catalogo_esc["tecnicismos"].values() for f in t["formas"]}
    capitulos = [b["capitulo"] for b in (config or {}).get("bloques", [])]

    clasica = _leer(CLASICA_PATH, errores) if CLASICA_PATH.exists() else None
    if clasica is None:
        if not errores:
            errores.append("tematicas/clasica.json: no existe")
        return None, errores
    antes = len(errores)
    _validar_comun(clasica, "tematicas/clasica.json", errores, eventos)
    _validar_terminos(clasica.get("terminos"), formas_tec, "tematicas/clasica.json", errores)
    if clasica.get("id") != CLASICA or clasica.get("precio") != 0:
        errores.append("tematicas/clasica.json: el id debe ser 'clasica' y el precio 0 (RN02)")
    if len(errores) > antes:
        return None, errores  # sin términos válidos no se puede revisar ninguna temática
    terminos = clasica["terminos"]

    tematicas = {CLASICA: _preparar(clasica, terminos)}
    for ruta in _archivos():
        if ruta == CLASICA_PATH:
            continue
        donde = f"tematicas/{ruta.name}"
        datos = _leer(ruta, errores)
        if datos is None:
            continue
        antes = len(errores)
        _validar_comun(datos, donde, errores, eventos)
        _validar_tematica(datos, terminos, capitulos, donde, errores)
        if datos.get("id") in tematicas:
            errores.append(f"{donde}: el id '{datos.get('id')}' está repetido")
        if len(errores) > antes:
            continue  # FE4: no se muestra en la tienda
        tematicas[datos["id"]] = _preparar(datos, terminos)
    orden = sorted(tematicas, key=lambda i: (tematicas[i]["orden"], tematicas[i]["nombre"]))
    return {"terminos": terminos, "tematicas": tematicas, "orden": orden}, errores


def _resultado():
    firma = _firma()
    if _cache["firma"] != firma:
        _cache["firma"] = firma
        _cache["resultado"] = _construir()
        for error in _cache["resultado"][1]:
            logger.error("CU07 temática con errores: %s", error)  # FE4: se registra
    return _cache["resultado"]


def validar():
    """Errores de app/data/tematicas/*.json (vacía si todo está bien)."""
    _cache["firma"] = None
    return _resultado()[1]


def cargar():
    """Catálogo con las temáticas válidas. Lanza CatalogoError si falla la Clásica (FE6)."""
    catalogo, errores = _resultado()
    if catalogo is None:
        raise CatalogoError(errores)
    return catalogo


def tematica(tematica_id):
    """La temática válida con ese id o, si no existe o tiene errores, la Clásica (FE4)."""
    try:
        cat = cargar()
    except CatalogoError:
        return None
    return cat["tematicas"].get(tematica_id) or cat["tematicas"][CLASICA]


def publica(datos):
    """Lo que el navegador necesita de una temática (sin el glosario compilado)."""
    return {
        "id": datos["id"],
        "nombre": datos["nombre"],
        "icono": datos["icono"],
        "descripcion": datos["descripcion"],
        "precio": datos["precio"],
        "color": (datos.get("portada") or {}).get("color", ""),
    }


# ---------------------------------------------------------------- saldo (RN01)
def ganadas(jugador):
    """Estrellas ganadas en los minijuegos: la mejor calificación de cada nivel."""
    codigo = minijuego_codigo.estrellas_ganadas(jugador)
    algoritmos = ordenar.estrellas_ganadas(jugador)
    return {"codigo": codigo, "ordenar": algoritmos, "total": codigo + algoritmos}


def gastadas(jugador):
    total = CompraTematica.objects.filter(**jugador.filtro()).aggregate(s=Sum("precio"))["s"]
    return total or 0


def saldo(jugador):
    estrellas = ganadas(jugador)
    gasto = gastadas(jugador)
    return {
        "ganadas": estrellas["total"],
        "gastadas": gasto,
        "saldo": max(0, estrellas["total"] - gasto),
        "detalle": [
            {"nombre": "Minijuego de código", "estrellas": estrellas["codigo"]},
            {"nombre": "Ordenar algoritmos", "estrellas": estrellas["ordenar"]},
        ],
    }


ESTRELLAS_POR_NIVEL = 3  # máximo por nivel en el Minijuego de código y en Ordenar algoritmos


def _compras(jugador):
    return {c.tematica_id: c for c in CompraTematica.objects.filter(**jugador.filtro())}


# ---------------------------------------------------------------- tienda (pasos 1 a 4)
def _estado(datos, compras, saldo_actual):
    if datos["id"] == CLASICA or datos["id"] in compras:
        return "adquirida", 0
    if datos["precio"] > saldo_actual:
        return "faltan", datos["precio"] - saldo_actual
    return "disponible", 0


def tienda(jugador):
    """Paso 2: saldo y catálogo con el estado de cada temática (FA4, FA5)."""
    cat = cargar()
    cuenta = saldo(jugador)
    compras = _compras(jugador)
    items = []
    for tid in cat["orden"]:
        datos = cat["tematicas"][tid]
        estado, faltan = _estado(datos, compras, cuenta["saldo"])
        # Cada nivel de los minijuegos da hasta 3 estrellas: «unos N niveles» orienta mejor
        niveles = -(-faltan // ESTRELLAS_POR_NIVEL) if faltan else 0
        items.append({**publica(datos), "estado": estado, "faltan": faltan, "niveles": niveles})
    de_pago = [i for i in items if i["id"] != CLASICA]
    return {
        **cuenta,
        "tematicas": items,
        "sin_estrellas": cuenta["ganadas"] == 0,  # FA4
        "todas": bool(de_pago) and all(i["estado"] == "adquirida" for i in de_pago),  # FA5
        "adquiridas": sum(1 for i in items if i["estado"] == "adquirida"),
    }


def resumen_menu(jugador):
    """Para la tarjeta de la tienda en el menú de modos: el saldo y cuántas tiene."""
    datos = tienda(jugador)
    return {"saldo": datos["saldo"], "adquiridas": datos["adquiridas"],
            "total": len(datos["tematicas"])}


def _con_tecnicismos(trozos, formas_tec):
    """Marca también los tecnicismos del evento, que nunca cambian (leyenda de la vista
    previa). Devuelve [{"texto", "tipo"}] con tipo "termino", "tec" o "".
    """
    salida = []
    expresion = _expresion(formas_tec) if formas_tec else None
    for texto, es_termino in trozos:
        if es_termino or expresion is None:
            salida.append({"texto": texto, "tipo": "termino" if es_termino else ""})
            continue
        inicio = 0
        for m in expresion.finditer(texto):
            if m.start() > inicio:
                salida.append({"texto": texto[inicio : m.start()], "tipo": ""})
            salida.append({"texto": m.group(0), "tipo": "tec"})
            inicio = m.end()
        if inicio < len(texto):
            salida.append({"texto": texto[inicio:], "tipo": ""})
    return salida


def _escena(datos, evento, config, formas_tec):
    bloque = config["bloques"][0]
    capitulo = (datos.get("capitulos") or {}).get(bloque["capitulo"], bloque["nombre"])
    return {
        **publica(datos),
        "capitulo": f"Capítulo {bloque['capitulo']} · {capitulo}",
        "titulo": _con_tecnicismos(_segmentos(evento["titulo"], datos), formas_tec),
        "contexto": _con_tecnicismos(_segmentos(evento["contexto"], datos), formas_tec),
        # RN04: las opciones son las mismas en todas las temáticas
        "opciones": [
            _con_tecnicismos([(o["texto"], False)], formas_tec) for o in evento["opciones"]
        ],
    }


def vista_previa(jugador, tematica_id):
    """Paso 4: un evento real en la Clásica junto a la misma escena con la temática."""
    cat = cargar()
    datos = cat["tematicas"].get(tematica_id)
    if datos is None:
        raise TematicaDesconocida(tematica_id)
    config, catalogo_esc = escenarios.cargar()
    evento = catalogo_esc["eventos"][datos["vista_previa"]]
    formas_tec = [
        f
        for tid in evento.get("tecnicismos", [])
        for f in catalogo_esc["tecnicismos"][tid]["formas"]
    ]
    clasica = cat["tematicas"][CLASICA]
    cuenta = saldo(jugador)
    compras = _compras(jugador)
    estado, faltan = _estado(datos, compras, cuenta["saldo"])
    compra = compras.get(tematica_id)
    glosario = [
        {"de": formas[0].split(" ", 1)[-1], "a": datos["_reglas"][formas[0]]}
        for formas in cat["terminos"].values()
    ]
    return {
        "tematica": {**publica(datos), "estado": estado, "faltan": faltan},
        "clasica": _escena(clasica, evento, config, formas_tec),
        "escena": _escena(datos, evento, config, formas_tec),
        "glosario": [] if tematica_id == CLASICA else glosario,
        "saldo": cuenta["saldo"],
        "queda": cuenta["saldo"] - datos["precio"],
        "compra": {"fecha": compra.fecha, "precio": compra.precio} if compra else None,
    }


# ---------------------------------------------------------------- compra (pasos 7 y 8)
def _monedero(jugador):
    """El monedero del jugador, bloqueado hasta que termine la transacción."""
    consulta = MonederoTienda.objects.select_for_update().filter(**jugador.filtro())
    monedero = consulta.first()
    if monedero is None:
        try:
            with transaction.atomic():
                MonederoTienda.objects.create(**jugador.campos())
        except IntegrityError:
            pass  # otra petición lo creó al mismo tiempo
        monedero = consulta.first()
    return monedero


@transaction.atomic
def comprar(jugador, tematica_id):
    """Paso 8: vuelve a validar el saldo, descuenta y registra la compra (RN02, RN03).

    Todo pasa en una transacción (FE1). Devuelve (compra, nueva). Si ya la tenía, por un doble
    clic o desde otra pestaña, no cobra otra vez y devuelve nueva=False (FE2). Si el saldo ya
    no alcanza lanza EstrellasInsuficientes (FE3 -> FA1).
    """
    datos = cargar()["tematicas"].get(tematica_id)
    if datos is None or tematica_id == CLASICA:
        raise TematicaDesconocida(tematica_id)
    monedero = _monedero(jugador)
    ya = CompraTematica.objects.filter(**jugador.filtro(), tematica_id=tematica_id).first()
    if ya is not None:
        return ya, False
    disponible = saldo(jugador)["saldo"]
    if datos["precio"] > disponible:
        raise EstrellasInsuficientes(datos["precio"] - disponible, disponible)
    compra = CompraTematica.objects.create(
        **jugador.campos(), tematica_id=tematica_id, precio=datos["precio"]
    )
    monedero.gastadas += datos["precio"]
    monedero.save(update_fields=["gastadas", "actualizado"])
    return compra, True


# ---------------------------------------------------------------- jugar con una temática (B)
def adquiridas(jugador):
    """Paso B1: la Clásica y las temáticas que el jugador compró, en el orden del catálogo."""
    cat = cargar()
    compras = _compras(jugador)
    return [
        publica(cat["tematicas"][tid])
        for tid in cat["orden"]
        if tid == CLASICA or tid in compras
    ]


def para_partida(jugador, tematica_id):
    """Paso B3: la temática que se guarda en la partida. Si no existe, tiene errores o el
    jugador no la compró (por ejemplo, si modificó la petición), es la Clásica (FE4, FE5)."""
    try:
        validas = {t["id"] for t in adquiridas(jugador)}
    except CatalogoError:
        return CLASICA
    return tematica_id if tematica_id in validas else CLASICA


def tematizar_estado(datos, tematica_id):
    """Aplica la temática al estado del libro del CU01 (RN04, RN05).

    Cambia la narración (paso B3): el título y la situación del evento, el título del
    resultado, su desenlace y el nombre del capítulo. Las opciones y la retroalimentación
    técnica se quedan igual, como los ids, respuestas, probabilidades, vidas, XP y
    tecnicismos (RN04): son lo que el estudiante aprende.
    """
    tema = tematica(tematica_id)
    if tema is None:  # FE6 sin catálogo: la historia se narra como siempre
        return datos
    datos["tematica"] = publica(tema)
    if tema["id"] == CLASICA:
        return datos
    bloque = datos.get("bloque")
    if bloque:
        bloque["nombre"] = tema["capitulos"].get(bloque["capitulo"], bloque["nombre"])
    evento = datos.get("evento")
    if evento:
        evento["titulo"] = aplicar_texto(evento["titulo"], tema)
        evento["contexto"] = aplicar_texto(evento["contexto"], tema)
    if datos.get("resultado"):
        resultado = {**datos["resultado"]}  # copia: lo guardado en la partida no cambia
        for campo in ("evento_titulo", "desenlace"):
            resultado[campo] = aplicar_texto(resultado.get(campo), tema)
        datos["resultado"] = resultado
    return datos


def tematizar_final(resumen, tematica_id):
    """Post Game: el final también se narra con la temática."""
    tema = tematica(tematica_id)
    if tema is None:
        return resumen
    resumen["tematica"] = publica(tema)
    resumen["titulo"] = aplicar_texto(resumen["titulo"], tema)
    resumen["texto"] = aplicar_texto(resumen["texto"], tema)
    for registro in resumen.get("mapa", []):
        if getattr(registro, "repaso", ""):
            registro.repaso = aplicar_texto(registro.repaso, tema)
    return resumen
