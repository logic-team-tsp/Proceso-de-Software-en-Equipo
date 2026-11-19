# Entidades del diccionario de datos (WP.12, seccion 3.4).
# Perfil y Tema siguen definidos en app/views_personalizar.py (CU-02) y los escenarios
# (NodoNarrativo, Opcion) viven en app/data/*.json (RNF-MAN-05). En la base de datos se guarda
# lo que genera el jugador: la Partida, su bitacora de decisiones (RegistroDecision), los
# tecnicismos y cuestionarios de CU-05 y los intentos del minijuego de codigo de CU-04.
import uuid

from django.conf import settings
from django.db import models


class Partida(models.Model):
    """Partida de un estudiante. La crea CU-02 (perfil y temas) y se juega en CU-01."""

    EN_CURSO = "en_curso"
    COMPLETADA = "completada"
    DERROTA = "derrota"
    ESTADOS = [
        (EN_CURSO, "En curso"),
        (COMPLETADA, "Completada"),
        (DERROTA, "Derrota (sin vidas)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="partidas",
    )

    # Copia del perfil/antecedente elegido en CU-02.
    perfil_id = models.CharField(max_length=40)
    perfil_nombre = models.CharField(max_length=80)
    perfil_descripcion = models.TextField(blank=True)

    # Estado del jugador (RF-05, RF-21).
    hp_max = models.PositiveSmallIntegerField()
    hp = models.PositiveSmallIntegerField()
    xp = models.PositiveIntegerField(default=0)
    atributos = models.JSONField(default=dict)
    puntos_atributo = models.PositiveSmallIntegerField(default=0)
    puntuacion = models.PositiveIntegerField(default=0)
    aciertos = models.PositiveSmallIntegerField(default=0)
    decisiones = models.PositiveSmallIntegerField(default=0)

    # Historia: subtemas elegidos en CU-02 y la secuencia de eventos de esta partida.
    temas = models.JSONField(default=list)
    secuencia = models.JSONField(default=list)
    indice = models.PositiveSmallIntegerField(default=0)
    semilla = models.BigIntegerField(default=0)

    estado = models.CharField(max_length=12, choices=ESTADOS, default=EN_CURSO)
    logros = models.JSONField(default=list)
    # Resultado de la ultima decision; se muestra hasta que el jugador pasa la pagina.
    resultado_pendiente = models.JSONField(null=True, blank=True)
    # CU-06 Conseguir vidas (app/services/conseguir_vidas.py): conteo de eventos para la
    # sugerencia, preguntas vistas, vidas recuperadas y la ronda en juego.
    vidas_extra = models.JSONField(default=dict, blank=True)
    # CU-07: temática con la que se narra la historia (app/data/tematicas/). Se elige en CU-02
    # y no cambia hasta que la partida termina (RN06). «clasica» es la historia sin cambios.
    tematica = models.CharField(max_length=40, default="clasica", blank=True)

    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creada"]

    def __str__(self):
        return f"Partida {self.id} ({self.perfil_nombre}, {self.estado})"


class RegistroDecision(models.Model):
    """Bitacora de decisiones (RF-06). Alimenta el mapa de decisiones de Post Game."""

    partida = models.ForeignKey(Partida, on_delete=models.CASCADE, related_name="registros")
    orden = models.PositiveSmallIntegerField()
    evento_id = models.CharField(max_length=60)
    evento_titulo = models.CharField(max_length=120)
    tema_id = models.CharField(max_length=60)
    subtema_nombre = models.CharField(max_length=120)
    tipo = models.CharField(max_length=15)
    opcion_id = models.CharField(max_length=10)
    opcion_texto = models.TextField()
    correcta = models.BooleanField()
    probabilidad = models.PositiveSmallIntegerField(null=True, blank=True)
    tirada = models.PositiveSmallIntegerField(null=True, blank=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["orden"]
        constraints = [
            models.UniqueConstraint(fields=["partida", "orden"], name="decision_unica_por_orden"),
        ]

    def __str__(self):
        return f"{self.partida_id} #{self.orden} {self.evento_id} -> {self.opcion_id}"


# ---------------------------------------------------------------- CU05 Cuestionario de tecnicismos
# El registro y el historial son por usuario (SDS 1.3.5). Si nadie inicio sesion se guardan con
# la clave de la sesion del navegador (sesion), para que el modo se pueda jugar en la demo.
class TecnicismoRegistrado(models.Model):
    """Tecnicismo que el jugador ya descubrio en un evento del CU01 (RF-41, CU05-RN02)."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="tecnicismos_registrados",
    )
    sesion = models.CharField(max_length=40, blank=True, db_index=True)
    tecnicismo_id = models.CharField(max_length=60)
    partida = models.ForeignKey(
        Partida, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    registrado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["registrado"]
        constraints = [
            # Acumulativo y sin duplicados (RN02)
            models.UniqueConstraint(
                fields=["usuario", "tecnicismo_id"],
                condition=models.Q(usuario__isnull=False),
                name="tecnicismo_unico_por_usuario",
            ),
            models.UniqueConstraint(
                fields=["sesion", "tecnicismo_id"],
                condition=models.Q(usuario__isnull=True),
                name="tecnicismo_unico_por_sesion",
            ),
        ]

    def __str__(self):
        return f"{self.usuario_id or self.sesion} -> {self.tecnicismo_id}"


class ResultadoCuestionario(models.Model):
    """Resultado de un cuestionario terminado: historial del usuario (RF-58)."""

    EN_LINEA = "en_linea"
    SINCRONIZADO = "sincronizado"
    ORIGENES = [
        (EN_LINEA, "En línea"),
        (SINCRONIZADO, "Sincronizado después (sin conexión, FE1)"),
    ]

    # El id viaja dentro del token firmado: si el navegador reintenta enviar un resultado
    # pendiente, el servidor no lo guarda dos veces (FE1, RF-60).
    id = models.UUIDField(primary_key=True, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="cuestionarios",
    )
    sesion = models.CharField(max_length=40, blank=True, db_index=True)
    fecha = models.DateTimeField()
    puntaje = models.PositiveSmallIntegerField()
    aciertos = models.PositiveSmallIntegerField()
    total = models.PositiveSmallIntegerField()
    # Una entrada por pregunta: tecnicismo, tipo, opcion elegida, opcion correcta y si acerto
    respuestas = models.JSONField(default=list)
    origen = models.CharField(max_length=12, choices=ORIGENES, default=EN_LINEA)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha"]

    def __str__(self):
        return f"Cuestionario {self.id} ({self.puntaje}/100)"


class IntentoCodigo(models.Model):
    """Solución de un jugador a un nivel del minijuego de código (CU-04, SDS 3.4).

    Se juega desde el menú de modos (CU-05) y no depende de una partida. Igual que el registro
    de tecnicismos, es del usuario con sesión iniciada o, si no hay, de la sesión del navegador.
    Los programas viven en app/data/niveles_codigo/*.json: en Python o pseudocódigo, con sus
    líneas revueltas que el jugador acomoda. Cada intento es de un programa y una variante.
    """

    EN_CURSO = "en_curso"
    RESUELTO = "resuelto"
    ABANDONADO = "abandonado"
    ESTADOS = [
        (EN_CURSO, "En curso"),
        (RESUELTO, "Resuelto"),
        (ABANDONADO, "Abandonado (sin XP)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="intentos_codigo",
    )
    sesion = models.CharField(max_length=40, blank=True, db_index=True)
    # Programa y lenguaje («area-rectangulo-python») y variante de valores que tocaron al azar
    nivel_id = models.CharField(max_length=60)
    variante = models.PositiveSmallIntegerField(default=0)
    # Ronda del jugador en ese lenguaje: los niveles 1 a 4 en orden; al acabar empieza otra
    ronda = models.PositiveIntegerField(default=1)

    # Último acomodo comprobado ([{id, sangria}, ...]) y su huella: el mismo acomodo no cuenta
    # dos veces como intento fallido (CU04-RN02). bloques_usados son las líneas del acomodo.
    tablero = models.JSONField(null=True, blank=True)
    huella = models.CharField(max_length=64, blank=True)
    bloques_usados = models.PositiveSmallIntegerField(null=True, blank=True)
    intentos_fallidos = models.PositiveSmallIntegerField(default=0)  # CU04-RN05
    estrellas = models.PositiveSmallIntegerField(null=True, blank=True)
    xp_obtenida = models.PositiveIntegerField(default=0)
    resultado = models.JSONField(null=True, blank=True)  # resumen de la calificación
    estado = models.CharField(max_length=12, choices=ESTADOS, default=EN_CURSO)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado"]

    def __str__(self):
        return f"{self.usuario_id or self.sesion} · {self.nivel_id} ({self.estado})"


class IntentoOrdenar(models.Model):
    """Un nivel de «Ordenar algoritmos» (CU-09): ordenar una lista como lo haría un algoritmo.

    Se juega desde el menú de modos y no depende de una partida. Es del usuario con sesión
    iniciada o, si no hay, de la sesión del navegador. La lista se genera al presionar «Empezar»
    (paso 3); antes de eso el intento existe, pero solo se ve la explicación del algoritmo.
    Los movimientos que tocan no se guardan: el servidor los vuelve a calcular con la lista
    inicial (app/services/ordenar.py), así el navegador nunca los recibe.
    """

    EN_CURSO = "en_curso"
    RESUELTO = "resuelto"
    ABANDONADO = "abandonado"
    ESTADOS = [
        (EN_CURSO, "En curso"),
        (RESUELTO, "Resuelto"),
        (ABANDONADO, "Abandonado (sin XP)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="intentos_ordenar",
    )
    sesion = models.CharField(max_length=40, blank=True, db_index=True)
    # Juego del jugador (1, 2, 3...): los niveles 1 a 3 en orden; «Volver a jugar» empieza otro
    juego = models.PositiveIntegerField(default=1)
    nivel = models.PositiveSmallIntegerField()
    algoritmo = models.CharField(max_length=20)

    # Lista al azar (RN06) y cómo va: null hasta que el jugador presiona «Empezar»
    lista_inicial = models.JSONField(null=True, blank=True)
    lista = models.JSONField(null=True, blank=True)
    paso = models.PositiveSmallIntegerField(default=0)  # movimientos que ya hizo bien
    errores = models.PositiveSmallIntegerField(default=0)  # movimientos incorrectos y pistas (RN02)
    pistas = models.PositiveSmallIntegerField(default=0)
    errores_paso = models.PositiveSmallIntegerField(default=0)  # para FE3
    mostrado = models.BooleanField(default=False)  # FE3: el sistema mostró un paso

    estrellas = models.PositiveSmallIntegerField(null=True, blank=True)
    xp_obtenida = models.PositiveIntegerField(default=0)
    resultado = models.JSONField(null=True, blank=True)  # resumen de la calificación
    estado = models.CharField(max_length=12, choices=ESTADOS, default=EN_CURSO)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado"]

    def __str__(self):
        dueno = self.usuario_id or self.sesion
        return f"{dueno} · juego {self.juego} nivel {self.nivel} ({self.estado})"


# ---------------------------------------------------------------- CU08 Obtener logros
# Igual que CU04, CU05 y CU09, el progreso es del usuario con sesión iniciada o, si no hay, de
# la sesión del navegador. El catálogo de logros vive en app/data/logros.json y las reglas en
# app/services/logros.py.
class EstadisticaJugador(models.Model):
    """Contadores del jugador que revisan los logros (paso 2): vidas perdidas, finales..."""

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="estadistica_logros",
    )
    sesion = models.CharField(max_length=40, blank=True, db_index=True)
    # {"vidas_perdidas": 3, "finales": ["intro-programacion:completada", ...], ...}
    contadores = models.JSONField(default=dict)
    # Eventos ya aplicados: un reintento de FE1 no los vuelve a contar
    procesados = models.JSONField(default=list)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sesion"],
                condition=models.Q(usuario__isnull=True),
                name="estadistica_unica_por_sesion",
            ),
        ]

    def __str__(self):
        return f"Estadísticas de {self.usuario_id or self.sesion}"


class LogroJugador(models.Model):
    """Logro desbloqueado (paso 5). Se obtiene una sola vez y no se pierde (RN01)."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="logros_obtenidos",
    )
    sesion = models.CharField(max_length=40, blank=True, db_index=True)
    logro_id = models.CharField(max_length=60)
    # Partida en la que se obtuvo (para el informe de puntuación); null si fue en un minijuego
    partida = models.ForeignKey(
        Partida, null=True, blank=True, on_delete=models.SET_NULL, related_name="logros_cu08"
    )
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha"]
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "logro_id"],
                condition=models.Q(usuario__isnull=False),
                name="logro_unico_por_usuario",
            ),
            models.UniqueConstraint(
                fields=["sesion", "logro_id"],
                condition=models.Q(usuario__isnull=True),
                name="logro_unico_por_sesion",
            ),
        ]

    def __str__(self):
        return f"{self.usuario_id or self.sesion} -> {self.logro_id}"


class Puntuacion(models.Model):
    """Puntuación de una historia que llegó a un final: el ranking personal (pasos 7 a 9).

    Solo se crea al llegar a un final (RN05); si el jugador sale antes no hay puntuación (FE3).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="puntuaciones",
    )
    sesion = models.CharField(max_length=40, blank=True, db_index=True)
    partida = models.OneToOneField(
        Partida, on_delete=models.CASCADE, related_name="puntuacion_cu08"
    )
    # Materias de la partida (las «historias» del ranking) y el final alcanzado
    temas = models.JSONField(default=list)
    final_id = models.CharField(max_length=30)
    final_titulo = models.CharField(max_length=120)
    total = models.PositiveIntegerField()
    desglose = models.JSONField(default=list)  # RN06: [{id, nombre, cantidad, valor, puntos}]
    vidas_perdidas = models.PositiveSmallIntegerField(default=0)
    minijuegos_jugados = models.PositiveSmallIntegerField(default=0)
    minijuegos_ganados = models.PositiveSmallIntegerField(default=0)
    mejor_anterior = models.PositiveIntegerField(null=True, blank=True)
    nuevo_record = models.BooleanField(default=False)
    fecha = models.DateTimeField()

    class Meta:
        # RN04: de mayor a menor; en empate va primero la más antigua
        ordering = ["-total", "fecha"]

    def __str__(self):
        return f"{self.usuario_id or self.sesion} · {self.total} pts ({self.final_titulo})"


# ---------------------------------------------------------------- CU07 Comprar módulos temáticos
# Igual que CU04, CU05, CU08 y CU09, las compras son del usuario con sesión iniciada o, si no
# hay, de la sesión del navegador. El catálogo vive en app/data/tematicas/*.json y las reglas en
# app/services/tematicas.py. El saldo no se guarda: son las estrellas ganadas en CU04 y CU09
# menos las gastadas (RN01).
class MonederoTienda(models.Model):
    """Estrellas gastadas por el jugador en la tienda.

    Hay uno por jugador y se bloquea durante una compra: así dos compras al mismo tiempo (dos
    pestañas, FE3) no pueden gastar las mismas estrellas.
    """

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="monedero_tienda",
    )
    sesion = models.CharField(max_length=40, blank=True, db_index=True)
    gastadas = models.PositiveIntegerField(default=0)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sesion"],
                condition=models.Q(usuario__isnull=True),
                name="monedero_unico_por_sesion",
            ),
        ]

    def __str__(self):
        return f"Monedero de {self.usuario_id or self.sesion}: {self.gastadas} gastadas"


class CompraTematica(models.Model):
    """Temática comprada en la tienda: permanente y sin reembolso (RN03)."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="compras_tematica",
    )
    sesion = models.CharField(max_length=40, blank=True, db_index=True)
    tematica_id = models.CharField(max_length=40)
    precio = models.PositiveIntegerField()  # el precio que pagó, aunque después cambie
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha"]
        constraints = [
            # Se compra una sola vez (RN03); un doble clic no cobra dos veces (FE2)
            models.UniqueConstraint(
                fields=["usuario", "tematica_id"],
                condition=models.Q(usuario__isnull=False),
                name="compra_unica_por_usuario",
            ),
            models.UniqueConstraint(
                fields=["sesion", "tematica_id"],
                condition=models.Q(usuario__isnull=True),
                name="compra_unica_por_sesion",
            ),
        ]

    def __str__(self):
        return f"{self.usuario_id or self.sesion} -> {self.tematica_id} ({self.precio}★)"
