"""Motor del CU-01 Realizar Partida: las reglas del juego, sin nada de HTTP.

Flujo (SRS, CU01): se muestra un evento -> el usuario elige una opcion -> el sistema calcula
el resultado, da la retroalimentacion tecnica, actualiza vidas/XP/progreso, registra la
decision y muestra el desenlace -> el usuario pasa la pagina (RN-01).

La historia se divide en bloques por porcentaje de avance (config_juego.json). Cada bloque
dice que parte de sus eventos son de probabilidad (prueba de atributos); el resto son normales
(analizar y decidir). Con los bloques de config_juego.json la dificultad sube 10 / 25 / 35 / 50 %.

Una partida dura entre min_eventos_por_partida y max_eventos_por_partida eventos, sin repetir.
Si los subtemas elegidos en CU-02 no alcanzan, se completa con subtemas de las mismas materias
y despues con los de las demas; los eventos de los temas elegidos entran completos si caben.
"""

import random
from collections import Counter

from django.db import transaction
from django.urls import reverse

from app.models import Partida, RegistroDecision

from . import conseguir_vidas, escenarios, tecnicismos, tematicas


class ReglaError(Exception):
    """El jugador intento algo que las reglas del juego no permiten."""


# ---------------------------------------------------------------- creacion de partida
def bloque_de(posicion, total, config):
    """Bloque (nivel) al que pertenece un evento segun el porcentaje de historia avanzado."""
    porcentaje = posicion / total * 100 if total else 0
    for numero, bloque in enumerate(config["bloques"]):
        if porcentaje < bloque["hasta_porcentaje"]:
            return numero, bloque
    ultimo = len(config["bloques"]) - 1
    return ultimo, config["bloques"][ultimo]


def _primer_libre(grupos, orden, tipo, usados, rng):
    for llave in orden:
        libres = [e for e in grupos[llave][tipo] if e not in usados]
        if libres:
            return rng.choice(libres)
    return None


def de_probabilidad_por_bloque(total, config):
    """Cuantos eventos de probabilidad lleva cada bloque en una partida de 'total' eventos:
    la parte 'probabilidad_evento' de las posiciones del bloque, redondeada."""
    tamanos = Counter(bloque_de(p, total, config)[0] for p in range(total))
    return {
        numero: int(config["bloques"][numero]["probabilidad_evento"] * tamano + 0.5)
        for numero, tamano in tamanos.items()
    }


def _largo_posible(normales, probabilidad, config):
    """La partida mas larga (hasta el maximo) cuya mezcla de tipos alcanza con los eventos."""
    for total in range(min(config["max_eventos_por_partida"], normales + probabilidad), 0, -1):
        prob = sum(de_probabilidad_por_bloque(total, config).values())
        if prob <= probabilidad and total - prob <= normales:
            return total
    return 0


def subtemas_de_la_partida(subtemas, config, catalogo, rng):
    """Los subtemas de los que salen los eventos y el largo de la partida.

    Entran primero los elegidos; si no alcanzan para min_eventos_por_partida, se agregan al
    azar subtemas de las mismas materias y luego del resto, hasta llegar al minimo.
    """
    conteo = {}
    for evento in catalogo["eventos"].values():
        conteo.setdefault(evento["subtema"], Counter())[evento["tipo"]] += 1
    elegidos = [s for s in subtemas if s in conteo]
    materias = {s.split(":")[0] for s in elegidos}
    resto = [s for s in conteo if s not in elegidos]
    rng.shuffle(resto)
    resto.sort(key=lambda s: s.split(":")[0] not in materias)  # estable: el azar se conserva

    def largo(lista):
        normales = sum(conteo[s][escenarios.NORMAL] for s in lista)
        probabilidad = sum(conteo[s][escenarios.PROBABILIDAD] for s in lista)
        return _largo_posible(normales, probabilidad, config)

    minimo = config.get("min_eventos_por_partida", 1)
    lista = list(elegidos)
    while resto and largo(lista) < minimo:
        lista.append(resto.pop(0))
    return lista, largo(lista)


def _eventos_de_la_partida(elegidos, subtemas, total, tipos, catalogo, rng):
    """Los eventos que se juegan: los de los subtemas elegidos completos (si caben) y el
    resto, de cada tipo, al azar entre los subtemas de relleno."""
    por_tipo = {escenarios.NORMAL: ([], []), escenarios.PROBABILIDAD: ([], [])}
    for evento_id, evento in catalogo["eventos"].items():
        if evento["subtema"] in subtemas:
            propios, relleno = por_tipo[evento["tipo"]]
            (propios if evento["subtema"] in elegidos else relleno).append(evento_id)
    necesarios = Counter(tipos)
    seleccion = []
    for tipo, (propios, relleno) in por_tipo.items():
        rng.shuffle(propios)
        rng.shuffle(relleno)
        seleccion += (propios + relleno)[: necesarios[tipo]]
    return set(seleccion)


def construir_secuencia(subtemas, config, catalogo, rng):
    """Arma la lista de eventos de la partida, repartiendo los subtemas.

    En cada bloque, la parte 'probabilidad_evento' de sus posiciones (elegidas al azar) es de
    probabilidad y el resto normal, asi cada partida tiene exactamente la dificultad del
    bloque. Si un tipo se acabara se usa el otro, para que la partida no se quede corta.
    """
    elegidos = set(subtemas)
    subtemas, total = subtemas_de_la_partida(subtemas, config, catalogo, rng)

    tipos = [escenarios.NORMAL] * total
    lugares = {}
    for posicion in range(total):
        lugares.setdefault(bloque_de(posicion, total, config)[0], []).append(posicion)
    for numero, cuantos in de_probabilidad_por_bloque(total, config).items():
        for posicion in rng.sample(lugares[numero], cuantos):
            tipos[posicion] = escenarios.PROBABILIDAD

    jugables = _eventos_de_la_partida(elegidos, subtemas, total, tipos, catalogo, rng)
    grupos = {}
    for evento_id in sorted(jugables):
        evento = catalogo["eventos"][evento_id]
        grupo = grupos.setdefault(
            evento["subtema"], {escenarios.NORMAL: [], escenarios.PROBABILIDAD: []}
        )
        grupo[evento["tipo"]].append(evento_id)
    if not grupos:
        return []

    llaves = sorted(grupos)
    rng.shuffle(llaves)
    otro = {escenarios.NORMAL: escenarios.PROBABILIDAD, escenarios.PROBABILIDAD: escenarios.NORMAL}
    usados, secuencia = set(), []
    for posicion, tipo in enumerate(tipos):
        giro = posicion % len(llaves)
        orden = llaves[giro:] + llaves[:giro]
        elegido = _primer_libre(grupos, orden, tipo, usados, rng) or _primer_libre(
            grupos, orden, otro[tipo], usados, rng
        )
        if elegido is None:
            break
        usados.add(elegido)
        secuencia.append(elegido)
    return secuencia


def valor_atributo(valor, config):
    """Valor inicial de un atributo (entero de 0 al maximo de config_juego.json)."""
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        return 0
    return max(0, min(config["niveles"]["maximo_atributo"], valor))


def nivel_de(xp, config):
    """Nivel del personaje: empieza en 1 y sube cada xp.por_nivel, hasta el maximo."""
    return min(config["niveles"]["maximo_personaje"], 1 + xp // config["xp"]["por_nivel"])


@transaction.atomic
def crear_partida(perfil, subtemas, usuario=None, semilla=None, tematica=tematicas.CLASICA):
    """Crea una partida lista para jugarse. La llama CU-02 al pulsar "Comenzar Aventura".

    perfil: dict de CU-02 (id, titulo, descripcion, vidas, xp y los atributos
            teoria/equipo/inteligencia como enteros de 1 a 10).
    subtemas: ids de subtema de CU-02, por ejemplo ["intro-programacion:0"]. Minimo uno (RF-24).
    tematica: CU-07, id de la temática ya validada con tematicas.para_partida() (RN06).
    """
    config, catalogo = escenarios.cargar()
    subtemas = list(dict.fromkeys(subtemas or []))
    if not subtemas:
        raise ReglaError("Toda partida debe incluir al menos un tema educativo.")
    conocidos = {s["id"] for tema in catalogo["temas"].values() for s in tema["subtemas"]}
    desconocidos = [s for s in subtemas if s not in conocidos]
    if desconocidos:
        raise ReglaError(f"No hay escenarios para: {', '.join(desconocidos)}")
    if not perfil or not perfil.get("titulo"):
        raise ReglaError("Toda partida requiere un perfil inicial.")

    if semilla is None:
        semilla = random.SystemRandom().randrange(2**31)
    secuencia = construir_secuencia(subtemas, config, catalogo, random.Random(semilla))
    hp = max(1, int(perfil.get("vidas", 3)))
    atributos = {
        a["id"]: valor_atributo(perfil.get(a["id"], 0), config) for a in config["atributos"]
    }
    return Partida.objects.create(
        usuario=usuario,
        perfil_id=perfil.get("id", ""),
        perfil_nombre=perfil["titulo"],
        perfil_descripcion=perfil.get("descripcion", ""),
        hp_max=hp,
        hp=hp,
        xp=max(0, int(perfil.get("xp", 0))),
        atributos=atributos,
        temas=subtemas,
        secuencia=secuencia,
        semilla=semilla,
        tematica=tematica or tematicas.CLASICA,
    )


# ---------------------------------------------------------------- reglas
def probabilidad_opcion(opcion, atributos, config):
    """Probabilidad de exito = base de la opcion + bonus por el atributo (RF-13)."""
    reglas = config["probabilidad"]
    valor = int(atributos.get(opcion["atributo"], 0))
    bruta = opcion["probabilidad_base"] + valor * reglas["bonus_por_punto_atributo"]
    return max(reglas["minima"], min(reglas["maxima"], bruta))


def _nivel_riesgo(probabilidad, config):
    for nivel in config["riesgo"]:
        if probabilidad <= nivel["hasta"]:
            return nivel
    return config["riesgo"][-1]


def _atributo(config, atributo_id):
    return next((a for a in config["atributos"] if a["id"] == atributo_id), None)


def _evento_actual(partida, catalogo):
    return catalogo["eventos"][partida.secuencia[partida.indice]]


def _opciones_publicas(evento, partida, config):
    """Opciones sin revelar cual es correcta ni los desenlaces."""
    resultado = []
    for opcion in evento["opciones"]:
        item = {"id": opcion["id"], "texto": opcion["texto"]}
        if evento["tipo"] == escenarios.PROBABILIDAD:
            atributo = _atributo(config, opcion["atributo"])
            item.update(
                atributo=opcion["atributo"],
                atributo_nombre=atributo["nombre"],
                atributo_icono=atributo["icono"],
                valor_atributo=partida.atributos.get(opcion["atributo"], 0),
                probabilidad=probabilidad_opcion(opcion, partida.atributos, config),
            )
        resultado.append(item)
    return resultado


def _evaluar_probabilidad(partida, opcion, config):
    probabilidad = probabilidad_opcion(opcion, partida.atributos, config)
    # La tirada depende de la semilla y de la posicion: refrescar la pagina no cambia nada.
    tirada = random.Random(f"{partida.semilla}-{partida.indice}").randint(1, 100)
    acierto = tirada <= probabilidad
    nivel = _nivel_riesgo(probabilidad, config)
    atributo = _atributo(config, opcion["atributo"])
    riesgo = {
        "probabilidad": probabilidad,
        "tirada": tirada,
        "atributo": f"{atributo['icono']} {atributo['nombre']}",
        "nivel": nivel["etiqueta"],
        "mensaje": nivel["mensaje_exito" if acierto else "mensaje_fallo"],
    }
    return acierto, probabilidad, tirada, riesgo


# ---------------------------------------------------------------- decision (RF-02 a RF-15)
@transaction.atomic
def resolver_decision(partida, opcion_id):
    if partida.estado != Partida.EN_CURSO:
        raise ReglaError("La partida ya terminó.")
    if partida.resultado_pendiente is not None:
        raise ReglaError("Primero pasa la página para continuar la historia.")
    if partida.puntos_atributo > 0:
        raise ReglaError("Primero asigna tus puntos de atributo.")
    if conseguir_vidas.ronda_en_juego(partida):  # CU-06: el minijuego pausa la historia
        raise ReglaError("Termina primero el minijuego de vidas.")

    config, catalogo = escenarios.cargar()
    evento = _evento_actual(partida, catalogo)
    opcion = next((o for o in evento["opciones"] if o["id"] == opcion_id), None)
    if opcion is None:
        raise ReglaError("Esa opción no existe en este evento.")

    probabilidad = tirada = riesgo = None
    if evento["tipo"] == escenarios.NORMAL:
        acierto = opcion["correcta"]
        desenlace = opcion["desenlace"]
    else:
        acierto, probabilidad, tirada, riesgo = _evaluar_probabilidad(partida, opcion, config)
        desenlace = opcion["desenlace_exito"] if acierto else opcion["desenlace_fallo"]

    nivel_antes = nivel_de(partida.xp, config)
    hp_antes = partida.hp
    hp_delta = xp_delta = puntos_delta = ganados = 0
    if acierto:
        xp_delta = config["xp"]["por_acierto"]
        puntos_delta = config["puntos"]["por_acierto"]
        if probabilidad is not None and config["puntos"].get("bonus_por_riesgo"):
            puntos_delta += round(config["puntos"]["por_acierto"] * (100 - probabilidad) / 100)
        partida.xp += xp_delta
        partida.puntuacion += puntos_delta
        partida.aciertos += 1
        ganados = nivel_de(partida.xp, config) - nivel_antes  # cada nivel = 1 punto
    else:
        hp_delta = -min(partida.hp, config["hp"]["dano_por_fallo"])
        partida.hp += hp_delta

    RegistroDecision.objects.create(
        partida=partida,
        orden=partida.indice + 1,
        evento_id=evento["id"],
        evento_titulo=evento["titulo"],
        tema_id=evento["tema_id"],
        subtema_nombre=evento["subtema_nombre"],
        tipo=evento["tipo"],
        opcion_id=opcion["id"],
        opcion_texto=opcion["texto"],
        correcta=acierto,
        probabilidad=probabilidad,
        tirada=tirada,
    )

    partida.decisiones += 1
    partida.indice += 1
    if partida.hp == 0:
        partida.estado = Partida.DERROTA  # FE1
    elif partida.indice >= len(partida.secuencia):
        partida.estado = Partida.COMPLETADA  # FA1
        partida.logros = _logros_ganados(partida, config)
    if partida.estado != Partida.EN_CURSO:
        ganados = 0
    partida.puntos_atributo += ganados
    conseguir_vidas.registrar_evento(partida, hp_antes, config)  # CU-06 FA1

    partida.resultado_pendiente = {
        "evento_id": evento["id"],  # CU05: para resaltar sus tecnicismos en el resultado
        "acierto": acierto,
        "tipo": evento["tipo"],
        "evento_titulo": evento["titulo"],
        "tema": evento["tema_nombre"],
        "subtema": evento["subtema_nombre"],
        "opcion": {"id": opcion["id"], "texto": opcion["texto"]},
        "retroalimentacion": opcion["retroalimentacion"],
        "riesgo": riesgo,
        "desenlace": desenlace,
        "cambios": {
            "hp": hp_delta,
            "xp": xp_delta,
            "puntos": puntos_delta,
            "puntos_atributo": ganados,
        },
        "estado_final": partida.estado,
    }
    partida.save()
    return partida


def _logros_ganados(partida, config):
    registros = list(partida.registros.all())
    precision = partida.aciertos / partida.decisiones * 100 if partida.decisiones else 0
    ganados = []
    for logro in config["logros"]:
        condicion = logro["condicion"]
        if condicion == "completar":
            cumple = True
        elif condicion == "sin_dano":
            # Las vidas recuperadas en CU-06 cuentan como dano recibido
            cumple = partida.hp == partida.hp_max and not conseguir_vidas.recuperadas(partida)
        elif condicion == "precision_minima":
            cumple = precision >= logro["valor"]
        else:  # exitos_riesgosos
            umbral = logro.get("umbral", 40)
            riesgosos = [r for r in registros if r.correcta and (r.probabilidad or 100) < umbral]
            cumple = len(riesgosos) >= logro["valor"]
        if cumple:
            ganados.append(logro["id"])
    return ganados


@transaction.atomic
def continuar(partida):
    """El jugador pasa la pagina: se oculta el resultado y la historia sigue (RF-07)."""
    if partida.resultado_pendiente is None:
        raise ReglaError("No hay ningún resultado pendiente.")
    partida.resultado_pendiente = None
    partida.save(update_fields=["resultado_pendiente", "actualizada"])
    return partida


@transaction.atomic
def mejorar_atributo(partida, atributo_id):
    """Gasta un punto de atributo ganado al subir de nivel (estilo Life in Adventure)."""
    config, _ = escenarios.cargar()
    if partida.estado != Partida.EN_CURSO or partida.resultado_pendiente is not None:
        raise ReglaError("Ahora no puedes mejorar atributos.")
    if partida.puntos_atributo < 1:
        raise ReglaError("No tienes puntos de atributo disponibles.")
    if _atributo(config, atributo_id) is None:
        raise ReglaError("Ese atributo no existe.")
    if partida.atributos.get(atributo_id, 0) >= config["niveles"]["maximo_atributo"]:
        raise ReglaError("Ese atributo ya está al máximo.")
    partida.atributos[atributo_id] = partida.atributos.get(atributo_id, 0) + 1
    partida.puntos_atributo -= 1
    partida.save(update_fields=["atributos", "puntos_atributo", "actualizada"])
    return partida


# ---------------------------------------------------------------- lo que ve el navegador
def _fase(partida):
    if partida.resultado_pendiente is not None:
        return "resultado"
    if partida.estado != Partida.EN_CURSO:
        return "fin"
    return "mejora" if partida.puntos_atributo > 0 else "evento"


def estado_publico(partida):
    """Estado de la partida para el libro. Nunca incluye respuestas correctas."""
    config, catalogo = escenarios.cargar()
    fase = _fase(partida)
    total = len(partida.secuencia)
    posicion = partida.indice - 1 if fase == "resultado" else partida.indice
    posicion = max(0, min(posicion, total - 1))
    numero_bloque, bloque = bloque_de(posicion, total, config)
    por_nivel = config["xp"]["por_nivel"]
    nivel = nivel_de(partida.xp, config)
    nivel_maximo = config["niveles"]["maximo_personaje"]

    datos = {
        "id": str(partida.id),
        "fase": fase,
        "estado": partida.estado,
        "perfil": {"nombre": partida.perfil_nombre, "descripcion": partida.perfil_descripcion},
        "hp": partida.hp,
        "hp_max": partida.hp_max,
        "xp": partida.xp,
        "nivel": nivel,
        "nivel_maximo": nivel_maximo,
        "xp_en_nivel": por_nivel if nivel >= nivel_maximo else partida.xp % por_nivel,
        "xp_por_nivel": por_nivel,
        "puntuacion": partida.puntuacion,
        "progreso": round(partida.indice / total * 100) if total else 0,
        "evento_numero": posicion + 1,
        "evento_total": total,
        "bloque": {
            "numero": numero_bloque + 1,
            "capitulo": bloque["capitulo"],
            "nombre": bloque["nombre"],
        },
        "atributos": [
            {
                **a,
                "valor": partida.atributos.get(a["id"], 0),
                "maximo": config["niveles"]["maximo_atributo"],
            }
            for a in config["atributos"]
        ],
        "puntos_atributo": partida.puntos_atributo,
        "evento": None,
        "resultado": partida.resultado_pendiente,
        "url_fin": reverse("partida_fin", args=[partida.id]),
        "vidas": conseguir_vidas.estado_publico(partida, config),  # CU-06
        "tecnicismos": [],  # CU05 (RF-39, RF-40): los que el libro resalta y explica
    }
    if fase == "resultado":
        evento_id = (partida.resultado_pendiente or {}).get("evento_id")
        evento_resultado = catalogo["eventos"].get(evento_id)
        if evento_resultado:
            datos["tecnicismos"] = tecnicismos.publicos(
                evento_resultado.get("tecnicismos", []), catalogo["tecnicismos"]
            )
    if fase == "evento":
        evento = _evento_actual(partida, catalogo)
        datos["evento"] = {
            "id": evento["id"],
            "tipo": evento["tipo"],
            "titulo": evento["titulo"],
            "contexto": evento["contexto"],
            "tema": evento["tema_nombre"],
            "subtema": evento["subtema_nombre"],
            "opciones": _opciones_publicas(evento, partida, config),
        }
        datos["tecnicismos"] = tecnicismos.publicos(
            evento.get("tecnicismos", []), catalogo["tecnicismos"]
        )
    # CU-07: la historia se narra con la temática de la partida (RN04, RN05)
    return tematicas.tematizar_estado(datos, partida.tematica)


def final_de(partida, config):
    """Final de la partida. En derrota depende de hasta dónde llegó: un final por tramo."""
    if partida.estado == Partida.COMPLETADA:
        return config["finales"]["completada"], "Final completado"
    derrotas = config["finales"]["derrota"]
    jugados = partida.decisiones
    numero = next((i for i, f in enumerate(derrotas) if jugados <= f["hasta_evento"]), None)
    numero = len(derrotas) - 1 if numero is None else numero
    return derrotas[numero], f"Final {numero + 1} de {len(derrotas)}"


def resumen_final(partida):
    """Datos de la pantalla Post Game (RF-16, RF-17, RF-18)."""
    config, catalogo = escenarios.cargar()
    completada = partida.estado == Partida.COMPLETADA
    final, etiqueta = final_de(partida, config)
    mapa = list(partida.registros.all())
    # Idea UX «Repasar lo que fallaste»: cada decisión errónea trae su explicación técnica
    for registro in mapa:
        registro.repaso = ""
        if registro.correcta:
            continue
        evento = catalogo["eventos"].get(registro.evento_id) or {}
        opciones = evento.get("opciones", [])
        opcion = next((o for o in opciones if o["id"] == registro.opcion_id), None)
        if opcion:
            registro.repaso = opcion.get("retroalimentacion", "")
    logros = {logro["id"]: logro for logro in config["logros"]}
    decisiones = partida.decisiones
    resumen = {
        "completada": completada,
        "titulo": final["titulo"],
        "texto": final["texto"],
        "final_etiqueta": etiqueta,
        "puntuacion": partida.puntuacion,
        "aciertos": partida.aciertos,
        "decisiones": decisiones,
        "precision": round(partida.aciertos / decisiones * 100) if decisiones else 0,
        "hp": partida.hp,
        "hp_max": partida.hp_max,
        "perfil": partida.perfil_nombre,
        "logros": [logros[i] for i in partida.logros if i in logros],
        "mapa": mapa,
    }
    return tematicas.tematizar_final(resumen, partida.tematica)  # CU-07
