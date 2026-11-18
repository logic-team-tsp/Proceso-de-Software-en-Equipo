"""CU-08 Obtener logros: estadísticas, logros, ranking personal y finales, sin nada de HTTP.

Flujo (especificación CU-08):
  pasos 1-6   el jugador hace algo en la partida o en un minijuego -> la vista llama a
              registrar() con los eventos -> se suman las estadísticas, se revisan los logros
              bloqueados y se guardan los que se cumplieron (RN01, RN02). La respuesta JSON
              lleva {"cu08": {"nuevos": [...]}} y js/logros.js muestra las notificaciones.
  pasos 7-9   al llegar a un final se calcula la puntuación del ranking (RN05, RN06) y se
              guarda con su desglose; resultado_partida() arma la pantalla de resultados.
  pasos 10-16 el panel (js/logros.js) pide resumen(), ranking() e informe().

FE1: si no se pudo guardar, los eventos viajan firmados en "pendiente" y el navegador los
reintenta (reintentar()); cada evento lleva un id para que no se cuente dos veces.
FE4: un contador inválido (negativo o de otro tipo) se ignora y se recalcula.

El catálogo vive en app/data/logros.json y los puntos del ranking en config_juego.json >
ranking. Igual que CU04, CU05 y CU09, todo es del jugador (usuario o sesión del navegador).
"""

import logging
import uuid

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from app.models import EstadisticaJugador, LogroJugador, Partida, Puntuacion

from . import conseguir_vidas, escenarios

logger = logging.getLogger(__name__)

LOGROS_PATH = escenarios.DATA_DIR / "logros.json"
SAL_PENDIENTE = "cu08-logros-pendientes"
EVENTOS_RECORDADOS = 300  # ids de eventos ya aplicados que se guardan (FE1)

# Estadísticas que puede mirar un logro (paso 3). Las de CONJUNTOS guardan una lista y valen
# lo que mide la lista (finales distintos, materias distintas, tipos de minijuego).
ESTADISTICAS = {
    "historias_terminadas": "Historias terminadas",
    "historias_completadas": "Historias completadas",
    "derrotas": "Historias sin vidas",
    "finales": "Finales",
    "materias_terminadas": "Materias terminadas",
    "mejor_puntuacion": "Mejor puntuación",
    "records_superados": "Récords superados",
    "puntos_acumulados": "Puntos acumulados",
    "vidas_perdidas": "Vidas perdidas",
    "vidas_recuperadas": "Vidas recuperadas",
    "historias_sin_perder_vidas": "Historias sin perder vidas",
    "racha_sin_perder_vidas": "Mejor racha sin perder vidas",
    "minijuegos_jugados": "Jugados",
    "minijuegos_completados": "Completados",
    "tipos_minijuego_completados": "Tipos completados",
    "cuestionarios_perfectos": "Cuestionarios perfectos",
    "niveles_tres_estrellas": "Niveles con 3 estrellas",
    "nivel_jugador": "Nivel",
    "xp_total": "XP total",
}
CONJUNTOS = {"finales", "materias_terminadas", "tipos_minijuego_completados"}
# Contadores que se muestran en la cabecera de cada categoría del panel (paso 12)
CONTADORES_CATEGORIA = {
    "historia": ["historias_terminadas", "finales"],
    "puntuacion": ["puntos_acumulados"],
    "vidas": ["vidas_perdidas"],
    "minijuegos": ["minijuegos_jugados", "minijuegos_completados"],
    "nivel": ["nivel_jugador", "xp_total"],
}
MINIJUEGOS = {
    "codigo": "Minijuego de código",
    "cuestionario": "Cuestionario de tecnicismos",
    "ordenar": "Ordenar algoritmos",
    "vidas": "Conseguir vidas",
}
COMPONENTES = (
    ("decisiones", "✔ Decisiones correctas"),
    ("riesgo", "🎲 Pruebas de probabilidad superadas"),
    ("vidas", "❤️ Vidas conservadas"),
    ("minijuegos", "🧩 Minijuegos de vidas ganados"),
)
MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
TEXTO_OCULTO = "Logro oculto. Sigue explorando las historias."

_cache = {"firma": None, "resultado": None}


# ---------------------------------------------------------------- catálogo
def _entero(valor, minimo=0):
    return isinstance(valor, int) and not isinstance(valor, bool) and valor >= minimo


def _validar_ranking(config, errores):
    ranking = (config or {}).get("ranking")
    donde = "config_juego.json > ranking"
    if not isinstance(ranking, dict):
        errores.append(f"{donde}: falta la sección del CU-08")
        return
    if not _entero(ranking.get("top"), 1):
        errores.append(f"{donde}: 'top' debe ser un entero mayor que 0")
    puntos = ranking.get("puntos")
    if not isinstance(puntos, dict):
        errores.append(f"{donde}: falta 'puntos'")
        return
    for clave in ("decision_correcta", "vida_conservada", "minijuego_ganado"):
        if not _entero(puntos.get(clave)):
            errores.append(f"{donde} > puntos: '{clave}' debe ser un entero de 0 o más")


def _validar_nivel(config, errores):
    """config_juego.json > nivel_jugador: curva de XP y títulos del nivel del jugador."""
    reglas = (config or {}).get("nivel_jugador")
    donde = "config_juego.json > nivel_jugador"
    if not isinstance(reglas, dict):
        errores.append(f"{donde}: falta la sección del nivel del jugador")
        return
    for clave, minimo in (
        ("xp_base", 1),
        ("maximo", 2),
        ("xp_cuestionario_por_acierto", 0),
        ("xp_ronda_vidas_ganada", 0),
    ):
        if not _entero(reglas.get(clave), minimo):
            errores.append(f"{donde}: '{clave}' debe ser un entero de {minimo} o más")
    titulos = reglas.get("titulos")
    if not isinstance(titulos, list) or not titulos:
        errores.append(f"{donde}: 'titulos' debe ser una lista con al menos un título")
        return
    anterior = 0
    for titulo in titulos:
        desde = titulo.get("desde") if isinstance(titulo, dict) else None
        if not _entero(desde, 1) or desde <= anterior:
            errores.append(f"{donde} > titulos: 'desde' debe ir en orden y empezar en 1")
            return
        if not escenarios._texto_ok(titulo.get("titulo")):
            errores.append(f"{donde} > titulos: el título del nivel {desde} está vacío")
        anterior = desde
    if titulos[0].get("desde") != 1:
        errores.append(f"{donde} > titulos: el primer título debe ser 'desde': 1")


def _validar_logros(datos, errores):
    nombre = LOGROS_PATH.name
    categorias = datos.get("categorias") if isinstance(datos, dict) else None
    logros = datos.get("logros") if isinstance(datos, dict) else None
    if not isinstance(categorias, list) or not categorias:
        errores.append(f"{nombre}: 'categorias' debe ser una lista con al menos una categoría")
        categorias = []
    if not isinstance(logros, list) or not logros:
        errores.append(f"{nombre}: 'logros' debe ser una lista con al menos un logro")
        logros = []
    ids_cat = set()
    for cat in categorias:
        if not isinstance(cat, dict) or not escenarios._texto_ok(cat.get("id")):
            errores.append(f"{nombre}: cada categoría necesita 'id'")
            continue
        if cat["id"] in ids_cat:
            errores.append(f"{nombre}: la categoría '{cat['id']}' está repetida")
        ids_cat.add(cat["id"])
        if not escenarios._texto_ok(cat.get("nombre")):
            errores.append(f"{nombre}: la categoría '{cat['id']}' necesita 'nombre'")
    ids = set()
    for logro in logros:
        if not isinstance(logro, dict) or not escenarios._texto_ok(logro.get("id")):
            errores.append(f"{nombre}: cada logro necesita 'id'")
            continue
        donde = f"{nombre} > {logro['id']}"
        if logro["id"] in ids:
            errores.append(f"{donde}: el id está repetido")
        ids.add(logro["id"])
        for campo in ("nombre", "descripcion", "icono"):
            if not escenarios._texto_ok(logro.get(campo)):
                errores.append(f"{donde}: falta '{campo}'")
        if logro.get("categoria") not in ids_cat:
            errores.append(f"{donde}: la categoría '{logro.get('categoria')}' no existe")
        if logro.get("estadistica") not in ESTADISTICAS:
            errores.append(f"{donde}: la estadística '{logro.get('estadistica')}' no existe")
        meta = logro.get("meta")
        if meta != "todos" and not _entero(meta, 1):
            errores.append(f"{donde}: 'meta' debe ser un entero mayor que 0 o \"todos\"")
        if meta == "todos" and logro.get("estadistica") != "finales":
            errores.append(f"{donde}: 'meta': \"todos\" solo sirve con la estadística 'finales'")
        if "oculto" in logro and not isinstance(logro["oculto"], bool):
            errores.append(f"{donde}: 'oculto' debe ser true o false")


def _construir():
    errores = []
    try:
        config, catalogo = escenarios.cargar()
    except escenarios.CatalogoError as exc:
        return None, exc.errores
    _validar_ranking(config, errores)
    _validar_nivel(config, errores)
    datos = escenarios._leer(LOGROS_PATH, errores)
    if datos is not None:
        _validar_logros(datos, errores)
    if errores:
        return None, errores
    # Finales por materia (las «historias» del panel): el de la partida completada y uno por
    # tramo de derrota, en el orden de config_juego.json > finales.
    finales = [{"id": "completada", "titulo": config["finales"]["completada"]["titulo"]}]
    finales += [
        {"id": f"derrota-{n}", "titulo": f["titulo"]}
        for n, f in enumerate(config["finales"]["derrota"], start=1)
    ]
    historias = [
        {"id": tema["id"], "nombre": tema["nombre"]} for tema in catalogo["temas"].values()
    ]
    resultado = {
        "categorias": datos["categorias"],
        "logros": datos["logros"],
        "por_id": {logro["id"]: logro for logro in datos["logros"]},
        "finales": finales,
        "historias": historias,
        "total_finales": len(finales) * len(historias),
        "ranking": config["ranking"],
        "nivel": config["nivel_jugador"],
        "config": config,
    }
    return resultado, []


def _firma():
    return (escenarios._firma(), LOGROS_PATH.stat().st_mtime_ns if LOGROS_PATH.exists() else 0)


def validar():
    """Errores del catálogo de logros y de config_juego.json > ranking (vacía si todo bien)."""
    return _construir()[1]


def cargar():
    """Catálogo de logros listo para usarse. Relee los JSON si cambiaron. Lanza CatalogoError."""
    firma = _firma()
    if _cache["firma"] != firma:
        _cache["firma"] = firma
        _cache["resultado"] = _construir()
    resultado, errores = _cache["resultado"]
    if errores:
        raise escenarios.CatalogoError(errores)
    return resultado


# ---------------------------------------------------------------- utilidades
def fecha_texto(fecha, con_hora=False):
    """«13 nov 2026» (o «13 nov 2026 · 19:05») en la zona horaria del proyecto."""
    local = timezone.localtime(fecha)
    texto = f"{local.day:02d} {MESES[local.month - 1]} {local.year}"
    return f"{texto} · {local:%H:%M}" if con_hora else texto


def miles(numero):
    """13425 -> «13 425» (como en el mockup)."""
    return f"{numero:,}".replace(",", " ") if isinstance(numero, int) else ""


def _tema_de(subtema_id):
    return str(subtema_id).split(":", 1)[0]


def temas_de(partida):
    """Materias de la partida, sin repetir y en el orden en que se eligieron."""
    return list(dict.fromkeys(_tema_de(s) for s in partida.temas or []))


def _nombre_historia(temas, cat):
    nombres = {h["id"]: h["nombre"] for h in cat["historias"]}
    return " + ".join(nombres.get(t, t) for t in temas) or "Historia"


def _valor(contadores, estadistica):
    """Valor de una estadística. FE4: si el contador es inválido se toma como vacío."""
    valor = contadores.get(estadistica)
    if estadistica in CONJUNTOS:
        return len(valor) if isinstance(valor, list) else 0
    return valor if _entero(valor) else 0


def _meta(logro, cat):
    return cat["total_finales"] if logro["meta"] == "todos" else logro["meta"]


def _limpiar(contadores):
    """FE4: quita los contadores inválidos (se recalculan desde cero en vez de romper)."""
    limpios = {}
    for clave, valor in (contadores or {}).items():
        if clave in CONJUNTOS and isinstance(valor, list):
            limpios[clave] = [v for v in valor if isinstance(v, str)]
        elif clave not in CONJUNTOS and _entero(valor):
            limpios[clave] = valor
        else:
            logger.warning("CU08 FE4: contador inválido %r=%r, se ignora", clave, valor)
    return limpios


def _sumar(contadores, clave, cantidad=1):
    contadores[clave] = _valor(contadores, clave) + cantidad


def _agregar(contadores, clave, *valores):
    actuales = contadores.get(clave) if isinstance(contadores.get(clave), list) else []
    contadores[clave] = actuales + [v for v in valores if v not in actuales]


# ---------------------------------------------------------------- nivel del jugador
# La XP se acumula entre partidas y minijuegos. Pasar del nivel n al n+1 cuesta xp_base × n,
# así que cada nivel cuesta más que el anterior (100, 200, 300... con xp_base = 100).
def xp_para_nivel(nivel, reglas):
    """XP total que hace falta para llegar a ese nivel (nivel 1 = 0 XP)."""
    return reglas["xp_base"] * nivel * (nivel - 1) // 2


def nivel_de_xp(xp, reglas):
    nivel = 1
    while nivel < reglas["maximo"] and xp >= xp_para_nivel(nivel + 1, reglas):
        nivel += 1
    return nivel


def titulo_de(nivel, reglas):
    return [t for t in reglas["titulos"] if t["desde"] <= nivel][-1]["titulo"]


def nivel_publico(xp, cat):
    """Nivel, título y avance hacia el siguiente nivel (panel, botón y Post Game)."""
    reglas = cat["nivel"]
    xp = xp if _entero(xp) else 0
    nivel = nivel_de_xp(xp, reglas)
    maximo = nivel >= reglas["maximo"]
    inicio = xp_para_nivel(nivel, reglas)
    necesaria = 0 if maximo else xp_para_nivel(nivel + 1, reglas) - inicio
    en_nivel = xp - inicio
    siguiente = next((t for t in reglas["titulos"] if t["desde"] > nivel), None)
    return {
        "nivel": nivel,
        "maximo": reglas["maximo"],
        "es_maximo": maximo,
        "titulo": titulo_de(nivel, reglas),
        "xp_total": xp,
        "xp_en_nivel": en_nivel,
        "xp_necesaria": necesaria,
        "porcentaje": 100 if maximo else round(en_nivel / necesaria * 100),
        "siguiente_titulo": siguiente,
    }


def _sumar_xp(contadores, cantidad, cat):
    if _entero(cantidad, 1):
        _sumar(contadores, "xp_total", cantidad)
    contadores["nivel_jugador"] = nivel_de_xp(_valor(contadores, "xp_total"), cat["nivel"])


# ---------------------------------------------------------------- eventos (pasos 1-2)
def evento_vidas_perdidas(cantidad):
    return {"tipo": "vida_perdida", "cantidad": int(cantidad)} if cantidad > 0 else None


def evento_vidas_recuperadas(cantidad):
    return {"tipo": "vida_recuperada", "cantidad": int(cantidad)} if cantidad > 0 else None


def evento_xp(cantidad):
    """XP que ganó el jugador en la partida (CU01): suma al nivel del jugador."""
    return {"tipo": "xp", "cantidad": int(cantidad)} if cantidad > 0 else None


def evento_minijuego(juego, completado, estrellas=None, perfecto=False, xp=0, aciertos=0):
    """xp: la que dio el nivel (CU04, CU09). El cuestionario y la ronda de vidas dan la XP de
    config_juego.json > nivel_jugador (por acierto y por ronda ganada)."""
    return {
        "tipo": "minijuego",
        "juego": juego,
        "completado": bool(completado),
        "estrellas": estrellas,
        "perfecto": bool(perfecto),
        "xp": int(xp or 0),
        "aciertos": int(aciertos or 0),
    }


def eventos_intento(juego, estado_antes, intento):
    """CU04 y CU09: el nivel cuenta como jugado al resolverlo o abandonarlo (paso 1)."""
    if estado_antes != "en_curso" or intento.estado == estado_antes:
        return []
    resuelto = intento.estado == "resuelto"
    estrellas = intento.estrellas if resuelto else None
    xp = (getattr(intento, "xp_obtenida", 0) or 0) if resuelto else 0
    return [evento_minijuego(juego, resuelto, estrellas=estrellas, xp=xp)]


def evento_final(partida):
    return {"tipo": "final", "partida": str(partida.id)}


def _aplicar_evento(jugador, contadores, evento, cat):
    tipo = evento.get("tipo")
    if tipo == "vida_perdida":
        _sumar(contadores, "vidas_perdidas", max(0, int(evento.get("cantidad", 1))))
    elif tipo == "vida_recuperada":
        _sumar(contadores, "vidas_recuperadas", max(0, int(evento.get("cantidad", 1))))
    elif tipo == "xp":
        _sumar_xp(contadores, max(0, int(evento.get("cantidad", 0))), cat)
    elif tipo == "minijuego":
        juego = evento.get("juego")
        if juego not in MINIJUEGOS:
            return None
        _sumar(contadores, "minijuegos_jugados")
        if evento.get("completado"):
            _sumar(contadores, "minijuegos_completados")
            _agregar(contadores, "tipos_minijuego_completados", juego)
            if juego == "cuestionario" and evento.get("perfecto"):
                _sumar(contadores, "cuestionarios_perfectos")
            estrellas = evento.get("estrellas")
            if juego in ("codigo", "ordenar") and _entero(estrellas) and estrellas >= 3:
                _sumar(contadores, "niveles_tres_estrellas")
            reglas = cat["nivel"]
            if juego == "vidas":
                xp = reglas["xp_ronda_vidas_ganada"]
            elif juego == "cuestionario":
                xp = reglas["xp_cuestionario_por_acierto"] * max(0, int(evento.get("aciertos", 0)))
            else:
                xp = max(0, int(evento.get("xp", 0)))
            _sumar_xp(contadores, xp, cat)
    elif tipo == "final":
        return _registrar_final(jugador, contadores, evento.get("partida"), cat)
    return None


# ---------------------------------------------------------------- puntuación (pasos 7-9)
def final_id(partida, config):
    """'completada' o 'derrota-N', igual que motor_partida.final_de()."""
    if partida.estado == Partida.COMPLETADA:
        return "completada"
    derrotas = config["finales"]["derrota"]
    numero = next(
        (i for i, f in enumerate(derrotas) if partida.decisiones <= f["hasta_evento"]),
        len(derrotas) - 1,
    )
    return f"derrota-{numero + 1}"


def desglose_de(partida, cat):
    """RN06: la puntuación del ranking es la suma de sus componentes."""
    config = cat["config"]
    valores = cat["ranking"]["puntos"]
    por_acierto = config["puntos"]["por_acierto"]
    riesgo = max(0, partida.puntuacion - partida.aciertos * por_acierto)
    superadas = partida.registros.filter(tipo=escenarios.PROBABILIDAD, correcta=True).count()
    extra = partida.vidas_extra or {}
    por_ronda = max(1, conseguir_vidas.reglas(config)["vidas_por_ronda"])
    ganados = conseguir_vidas.recuperadas(partida) // por_ronda
    filas = {
        "decisiones": (partida.aciertos, valores["decision_correcta"]),
        "riesgo": (superadas, None),
        "vidas": (partida.hp, valores["vida_conservada"]),
        "minijuegos": (ganados, valores["minijuego_ganado"]),
    }
    desglose = []
    for clave, nombre in COMPONENTES:
        cantidad, valor = filas[clave]
        puntos = riesgo if clave == "riesgo" else cantidad * valor
        desglose.append(
            {"id": clave, "nombre": nombre, "cantidad": cantidad, "valor": valor, "puntos": puntos}
        )
    total = sum(fila["puntos"] for fila in desglose)
    jugados = int(extra.get("rondas", 0)) if isinstance(extra.get("rondas"), int) else 0
    return total, desglose, ganados, max(jugados, ganados)


def _puntuaciones(jugador):
    return Puntuacion.objects.filter(**jugador.filtro())


def _registrar_final(jugador, contadores, partida_id, cat):
    """Guarda la puntuación de la partida que llegó a un final (RN05) y suma sus estadísticas.

    Es idempotente: si la partida ya tiene puntuación no se vuelve a contar.
    """
    try:
        partida = Partida.objects.get(pk=partida_id)
    except (Partida.DoesNotExist, ValueError, ValidationError):
        return None
    if partida.estado == Partida.EN_CURSO or Puntuacion.objects.filter(partida=partida).exists():
        return None  # FE3: sin final no hay puntuación
    config = cat["config"]
    temas = temas_de(partida)
    total, desglose, ganados, jugados = desglose_de(partida, cat)
    vidas_perdidas = max(0, partida.hp_max - partida.hp + conseguir_vidas.recuperadas(partida))
    mejor = max((p.total for p in _puntuaciones(jugador)), default=None)
    final = final_id(partida, config)
    titulo = (
        config["finales"]["completada"]["titulo"]
        if final == "completada"
        else config["finales"]["derrota"][int(final.split("-")[1]) - 1]["titulo"]
    )
    puntuacion = Puntuacion.objects.create(
        **jugador.campos(),
        partida=partida,
        temas=temas,
        final_id=final,
        final_titulo=titulo,
        total=total,
        desglose=desglose,
        vidas_perdidas=vidas_perdidas,
        minijuegos_jugados=jugados,
        minijuegos_ganados=ganados,
        mejor_anterior=mejor,
        nuevo_record=mejor is not None and total > mejor,
        fecha=timezone.now(),
    )
    # Estadísticas de la historia (paso 2)
    _sumar(contadores, "historias_terminadas")
    if partida.estado == Partida.COMPLETADA:
        _sumar(contadores, "historias_completadas")
    else:
        _sumar(contadores, "derrotas")
    _agregar(contadores, "finales", *[f"{t}:{final}" for t in temas])
    _agregar(contadores, "materias_terminadas", *temas)
    _sumar(contadores, "puntos_acumulados", total)
    contadores["mejor_puntuacion"] = max(_valor(contadores, "mejor_puntuacion"), total)
    if puntuacion.nuevo_record:
        _sumar(contadores, "records_superados")
    if partida.estado == Partida.COMPLETADA and vidas_perdidas == 0:
        _sumar(contadores, "historias_sin_perder_vidas")
        racha = _valor(contadores, "racha_actual") + 1
        contadores["racha_actual"] = racha
        contadores["racha_sin_perder_vidas"] = max(
            _valor(contadores, "racha_sin_perder_vidas"), racha
        )
    else:
        contadores["racha_actual"] = 0
    return partida


# ---------------------------------------------------------------- registrar (pasos 2-6)
def _estadistica(jugador, bloquear=True):
    consulta = EstadisticaJugador.objects
    if bloquear:
        consulta = consulta.select_for_update()
    estadistica = consulta.filter(**jugador.filtro()).first()
    if estadistica is None:
        estadistica = EstadisticaJugador.objects.create(**jugador.campos())
    return estadistica


def _por_desbloquear(contadores, obtenidos, cat):
    """Logros bloqueados cuya meta ya se alcanzó (pasos 3 y 4)."""
    return [
        logro
        for logro in cat["logros"]
        if logro["id"] not in obtenidos
        and _valor(contadores, logro["estadistica"]) >= _meta(logro, cat)
    ]


def _aplicar(jugador, eventos, partida, cat):
    estadistica = _estadistica(jugador)
    contadores = _limpiar(estadistica.contadores)
    _sumar_xp(contadores, 0, cat)  # el nivel siempre sale de la XP (por si cambió la curva)
    xp_antes = _valor(contadores, "xp_total")
    procesados = [p for p in (estadistica.procesados or []) if isinstance(p, str)]
    for evento in eventos:
        if evento["id"] in procesados:  # FE1: un reintento no cuenta dos veces
            continue
        de_la_partida = _aplicar_evento(jugador, contadores, evento, cat)
        partida = partida or de_la_partida
        procesados.append(evento["id"])
    estadistica.contadores = contadores
    estadistica.procesados = procesados[-EVENTOS_RECORDADOS:]
    estadistica.save()

    obtenidos = set(
        LogroJugador.objects.filter(**jugador.filtro()).values_list("logro_id", flat=True)
    )
    nuevos = []
    for logro in _por_desbloquear(contadores, obtenidos, cat):
        nuevo = LogroJugador.objects.create(
            **jugador.campos(), logro_id=logro["id"], partida=partida
        )
        nuevos.append(_publico(logro, cat, contadores, nuevo))
    return nuevos, _cambio_nivel(xp_antes, _valor(contadores, "xp_total"), cat)


def _cambio_nivel(xp_antes, xp_despues, cat):
    """Bloque "nivel" de la respuesta: el nivel actual y si subió (y si cambió el título)."""
    antes = nivel_publico(xp_antes, cat)
    despues = nivel_publico(xp_despues, cat)
    return {
        **despues,
        "xp_ganada": xp_despues - xp_antes,
        "subio": despues["nivel"] > antes["nivel"],
        "titulo_nuevo": despues["titulo"] != antes["titulo"],
    }


def _simular(jugador, eventos, cat):
    """FE1: los logros que se habrían desbloqueado, sin guardar nada (para notificarlos igual)."""
    try:
        estadistica = EstadisticaJugador.objects.filter(**jugador.filtro()).first()
        contadores = _limpiar(estadistica.contadores if estadistica else {})
        obtenidos = set(
            LogroJugador.objects.filter(**jugador.filtro()).values_list("logro_id", flat=True)
        )
    except DatabaseError:
        return [], None
    xp_antes = _valor(contadores, "xp_total")
    for evento in eventos:
        if evento.get("tipo") != "final":  # la puntuación necesita la base de datos
            _aplicar_evento(jugador, contadores, evento, cat)
    nuevos = [_publico(lg, cat, contadores) for lg in _por_desbloquear(contadores, obtenidos, cat)]
    return nuevos, _cambio_nivel(xp_antes, _valor(contadores, "xp_total"), cat)


def _firmar(jugador, eventos, partida):
    return signing.dumps(
        {"j": jugador.clave, "e": eventos, "p": str(partida.id) if partida else None},
        salt=SAL_PENDIENTE,
        compress=True,
    )


def registrar(jugador, eventos, partida=None):
    """Pasos 2 a 5: aplica los eventos y devuelve el bloque "cu08" de la respuesta JSON.

    {"nuevos": [logro, ...], "nivel": {nivel, titulo, subio, ...}, "pendiente": null | "token
    firmado (FE1)"}. Devuelve None si no
    hubo eventos. Nunca rompe la acción del juego: si los logros fallan, se avisa y se reintenta.
    """
    eventos = [dict(e) for e in eventos if e]
    if not eventos:
        return None
    for evento in eventos:
        evento.setdefault("id", uuid.uuid4().hex)
    try:
        cat = cargar()
    except escenarios.CatalogoError as exc:
        logger.error("CU08: el catálogo de logros tiene errores: %s", exc)
        return None
    try:
        with transaction.atomic():
            nuevos, nivel = _aplicar(jugador, eventos, partida, cat)
        return {"nuevos": nuevos, "nivel": nivel, "pendiente": None}
    except DatabaseError:
        logger.exception("CU08 FE1: no se pudo guardar el progreso de logros")
        nuevos, nivel = _simular(jugador, eventos, cat)
        return {"nuevos": nuevos, "nivel": nivel, "pendiente": _firmar(jugador, eventos, partida)}


def reintentar(jugador, token):
    """FE1: vuelve a aplicar los eventos que no se pudieron guardar. Lanza ValueError."""
    try:
        datos = signing.loads(token or "", salt=SAL_PENDIENTE, max_age=60 * 60 * 24 * 7)
    except signing.BadSignature as exc:
        raise ValueError("El progreso pendiente no es válido.") from exc
    if datos.get("j") != jugador.clave:
        raise ValueError("Ese progreso pendiente es de otro jugador.")
    partida = Partida.objects.filter(pk=datos["p"]).first() if datos.get("p") else None
    resultado = registrar(jugador, datos.get("e") or [], partida)
    return resultado or {"nuevos": [], "nivel": None, "pendiente": None}


# ---------------------------------------------------------------- lo que ve el navegador
def _publico(logro, cat, contadores, obtenido=None):
    """Logro para el panel o la notificación. Los ocultos sin obtener van como «?» (RN08)."""
    meta = _meta(logro, cat)
    valor = min(_valor(contadores, logro["estadistica"]), meta)
    oculto = bool(logro.get("oculto")) and obtenido is None
    datos = {
        "id": logro["id"],
        "categoria": logro["categoria"],
        "nombre": "???" if oculto else logro["nombre"],
        "descripcion": TEXTO_OCULTO if oculto else logro["descripcion"],
        "icono": "?" if oculto else logro["icono"],
        "oculto": oculto,
        "obtenido": obtenido is not None,
        "fecha": fecha_texto(obtenido.fecha) if obtenido else None,
        "valor": valor,
        "meta": meta,
        "progresivo": meta > 1 and not oculto,
        "porcentaje": round(valor / meta * 100) if meta else 0,
    }
    return datos


def _obtenidos(jugador):
    return {lj.logro_id: lj for lj in LogroJugador.objects.filter(**jugador.filtro())}


def _contadores(jugador, cat=None):
    estadistica = EstadisticaJugador.objects.filter(**jugador.filtro()).first()
    contadores = _limpiar(estadistica.contadores if estadistica else {})
    _sumar_xp(contadores, 0, cat or cargar())
    return contadores


def nivel(jugador):
    """Nivel del jugador para el botón de Logros (se pide al cargar cada pantalla)."""
    cat = cargar()
    return nivel_publico(_valor(_contadores(jugador, cat), "xp_total"), cat)


def _porcentaje(parte, total):
    return round(parte / total * 100) if total else 0  # RN07


def resumen(jugador):
    """Pasos 11-12 y FA6: pestañas Logros y Finales del panel."""
    cat = cargar()
    contadores = _contadores(jugador)
    obtenidos = _obtenidos(jugador)
    categorias = []
    for categoria in cat["categorias"]:
        lista = [
            _publico(lg, cat, contadores, obtenidos.get(lg["id"]))
            for lg in cat["logros"]
            if lg["categoria"] == categoria["id"]
        ]
        categorias.append(
            {
                "id": categoria["id"],
                "nombre": categoria["nombre"],
                "icono": categoria.get("icono", ""),
                "obtenidos": sum(1 for lg in lista if lg["obtenido"]),
                "total": len(lista),
                "contadores": [
                    {"nombre": ESTADISTICAS[c], "valor": _valor(contadores, c)}
                    for c in CONTADORES_CATEGORIA.get(categoria["id"], [])
                ],
                "logros": lista,
            }
        )
    total = len(cat["logros"])
    conseguidos = sum(1 for lg in cat["logros"] if lg["id"] in obtenidos)

    desbloqueados = set(contadores.get("finales") or [])
    ultima = _puntuaciones(jugador).order_by("-fecha").first()
    nuevos = {f"{t}:{ultima.final_id}" for t in ultima.temas} if ultima else set()
    historias = []
    for historia in cat["historias"]:
        finales = []
        for final in cat["finales"]:
            clave = f"{historia['id']}:{final['id']}"
            visto = clave in desbloqueados
            finales.append(
                {
                    "id": final["id"],
                    "titulo": final["titulo"] if visto else None,  # RN08: «?» si falta
                    "descubierto": visto,
                    "nuevo": visto and clave in nuevos,
                }
            )
        hechos = sum(1 for f in finales if f["descubierto"])
        historias.append(
            {
                "id": historia["id"],
                "nombre": historia["nombre"],
                "desbloqueados": hechos,
                "total": len(finales),
                "porcentaje": _porcentaje(hechos, len(finales)),
                "finales": finales,
            }
        )
    finales_hechos = sum(h["desbloqueados"] for h in historias)
    return {
        "logros": {
            "obtenidos": conseguidos,
            "total": total,
            "porcentaje": _porcentaje(conseguidos, total),
        },
        "categorias": categorias,
        "finales": {
            "desbloqueados": finales_hechos,
            "total": cat["total_finales"],
            "porcentaje": _porcentaje(finales_hechos, cat["total_finales"]),
            "historias": historias,
        },
        "hay_puntuaciones": ultima is not None,
        "nivel": nivel_publico(_valor(contadores, "xp_total"), cat),
    }


def _ordenadas(jugador):
    """RN04: de mayor a menor y, en empate, primero la más antigua."""
    return list(_puntuaciones(jugador).order_by("-total", "fecha"))


def posicion_de(puntuacion, lista):
    for numero, p in enumerate(lista, start=1):
        if p.pk == puntuacion.pk:
            return numero
    return None


def _fila(puntuacion, numero, cat, ultima_id):
    return {
        "id": str(puntuacion.id),
        "posicion": numero,
        "total": puntuacion.total,
        "historia": _nombre_historia(puntuacion.temas, cat),
        "temas": puntuacion.temas,
        "final": puntuacion.final_titulo,
        "fecha": fecha_texto(puntuacion.fecha),
        "reciente": str(puntuacion.id) == ultima_id,
    }


def ranking(jugador, historia=None):
    """Paso 13 y FA7: las mejores puntuaciones del jugador, en general o de una materia."""
    cat = cargar()
    top = cat["ranking"]["top"]
    todas = _ordenadas(jugador)
    ultima = max(todas, key=lambda p: p.fecha, default=None)
    ultima_id = str(ultima.id) if ultima else None
    ids = {h["id"] for h in cat["historias"]}
    historia = historia if historia in ids else None
    lista = [p for p in todas if historia is None or historia in p.temas]
    return {
        "historias": cat["historias"],
        "historia": historia,
        "top": [_fila(p, n, cat, ultima_id) for n, p in enumerate(lista[:top], start=1)],
        "tamano_top": top,
        "registradas": len(todas),
        "ultima": ultima_id,
    }


def _logros_de_partida(jugador, partida, cat, contadores):
    if partida is None:
        return []
    lista = LogroJugador.objects.filter(**jugador.filtro(), partida=partida).order_by("fecha")
    return [
        _publico(cat["por_id"][lj.logro_id], cat, contadores, lj)
        for lj in lista
        if lj.logro_id in cat["por_id"]
    ]


def informe(jugador, puntuacion_id):
    """Paso 14: el informe de una puntuación del ranking. Lanza Puntuacion.DoesNotExist."""
    cat = cargar()
    puntuacion = _puntuaciones(jugador).get(pk=puntuacion_id)
    contadores = _contadores(jugador)
    return {
        "id": str(puntuacion.id),
        "posicion": posicion_de(puntuacion, _ordenadas(jugador)),
        "historia": _nombre_historia(puntuacion.temas, cat),
        "final": puntuacion.final_titulo,
        "fecha": fecha_texto(puntuacion.fecha, con_hora=True),
        "total": puntuacion.total,
        "desglose": puntuacion.desglose,
        "vidas_perdidas": puntuacion.vidas_perdidas,
        "minijuegos_jugados": puntuacion.minijuegos_jugados,
        "minijuegos_ganados": puntuacion.minijuegos_ganados,
        "logros": _logros_de_partida(jugador, puntuacion.partida, cat, contadores),
    }


def resultado_partida(jugador, partida):
    """Pasos 7-9 (pantalla de resultados del Post Game). None si la partida no tiene puntuación.

    Si la partida llegó a su final sin registrarse (p. ej. FE1 o una partida de antes del
    CU-08), se registra aquí: es idempotente.
    """
    if partida.estado == Partida.EN_CURSO:
        return None
    cat = cargar()
    puntuacion = Puntuacion.objects.filter(partida=partida, **jugador.filtro()).first()
    if puntuacion is None and not Puntuacion.objects.filter(partida=partida).exists():
        registrar(jugador, [evento_final(partida)], partida)
        puntuacion = Puntuacion.objects.filter(partida=partida, **jugador.filtro()).first()
    if puntuacion is None:
        return None
    lista = _ordenadas(jugador)
    posicion = posicion_de(puntuacion, lista)
    top = cat["ranking"]["top"]
    mejor = lista[0] if lista else puntuacion
    contadores = _contadores(jugador, cat)
    desglose = [
        {
            **fila,
            "puntos_txt": miles(fila["puntos"]),
            "cantidad_txt": (
                str(fila["cantidad"])
                if fila.get("valor") is None
                else f"{fila['cantidad']} × {fila['valor']}"
            ),
        }
        for fila in puntuacion.desglose
    ]
    return {
        "id": str(puntuacion.id),
        "historia": _nombre_historia(puntuacion.temas, cat),
        "final": puntuacion.final_titulo,
        "completada": partida.estado == Partida.COMPLETADA,
        "total": puntuacion.total,
        "total_txt": miles(puntuacion.total),
        "desglose": desglose,
        "posicion": posicion,
        "posiciones": min(len(lista), top),
        "en_top": posicion is not None and posicion <= top,  # FA5
        "tamano_top": top,
        "registradas": len(lista),
        "nuevo_record": puntuacion.nuevo_record,
        "mejor_anterior": puntuacion.mejor_anterior,
        "mejor_anterior_txt": miles(puntuacion.mejor_anterior),
        "mejor_marca": mejor.total,
        "mejor_marca_txt": miles(mejor.total),
        "fecha": fecha_texto(puntuacion.fecha, con_hora=True),
        "logros": _logros_de_partida(jugador, partida, cat, contadores),
        "xp_partida": partida.aciertos * cat["config"]["xp"]["por_acierto"],
        "nivel": nivel_publico(_valor(contadores, "xp_total"), cat),
    }
