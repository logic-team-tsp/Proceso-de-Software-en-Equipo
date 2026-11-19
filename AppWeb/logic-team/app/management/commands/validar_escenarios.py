from django.core.management.base import BaseCommand, CommandError

from app.services import conseguir_vidas, escenarios, logros, minijuego_codigo, ordenar, tematicas


class Command(BaseCommand):
    help = (
        "Valida config_juego.json, los escenarios de app/data/escenarios/*.json, las "
        "afirmaciones del CU-06 (app/data/preguntas_vidas.json), los programas del CU-04 "
        "(app/data/niveles_codigo/*.json), los algoritmos del CU-09 (app/data/algoritmos.json) y "
        "los logros del CU-08 (app/data/logros.json) y las temáticas del CU-07 "
        "(app/data/tematicas/*.json)."
    )

    def handle(self, *args, **options):
        errores = escenarios.validar()
        if not errores:
            errores = conseguir_vidas.validar()  # CU-06: necesita los escenarios sin errores
        errores += minijuego_codigo.validar()  # CU-04
        errores += ordenar.validar()  # CU-09
        if not errores:
            errores = logros.validar()  # CU-08: necesita los escenarios sin errores
        if not errores:
            errores = tematicas.validar()  # CU-07: necesita los escenarios sin errores
        if errores:
            for error in errores:
                self.stderr.write(self.style.ERROR(f"- {error}"))
            raise CommandError(f"{len(errores)} error(es) en los escenarios.")
        _, catalogo = escenarios.cargar()
        eventos = catalogo["eventos"].values()
        normales = sum(1 for e in eventos if e["tipo"] == escenarios.NORMAL)
        probabilidad = len(catalogo["eventos"]) - normales
        self.stdout.write(
            self.style.SUCCESS(
                f"Escenarios válidos: {len(catalogo['temas'])} materias, {normales} eventos "
                f"normales y {probabilidad} de probabilidad."
            )
        )
        preguntas = conseguir_vidas.cargar_preguntas()
        verdaderas = sum(1 for p in preguntas.values() if p["respuesta"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Afirmaciones del CU-06 válidas: {len(preguntas)} ({verdaderas} verdaderas y "
                f"{len(preguntas) - verdaderas} falsas)."
            )
        )
        codigo = minijuego_codigo.cargar()
        variantes = sum(len(p["variantes"]) for p in codigo["programas"].values())
        self.stdout.write(
            self.style.SUCCESS(
                f"Minijuego de código válido: {len(codigo['niveles'])} niveles con "
                f"{len(codigo['programas'])} programas y {variantes} variantes, en "
                f"{len(minijuego_codigo.LENGUAJES)} lenguajes."
            )
        )
        algoritmos = ordenar.cargar()
        nombres = ", ".join(a["nombre"] for a in algoritmos["algoritmos"].values())
        self.stdout.write(
            self.style.SUCCESS(
                f"Ordenar algoritmos válido: {len(algoritmos['niveles'])} niveles ({nombres})."
            )
        )
        catalogo_logros = logros.cargar()
        ocultos = sum(1 for lg in catalogo_logros["logros"] if lg.get("oculto"))
        self.stdout.write(
            self.style.SUCCESS(
                f"Logros del CU-08 válidos: {len(catalogo_logros['logros'])} logros "
                f"({ocultos} ocultos) en {len(catalogo_logros['categorias'])} categorías y "
                f"{catalogo_logros['total_finales']} finales."
            )
        )
        catalogo_tematicas = tematicas.cargar()
        de_pago = [
            catalogo_tematicas["tematicas"][i]
            for i in catalogo_tematicas["orden"]
            if catalogo_tematicas["tematicas"][i]["precio"]
        ]
        self.stdout.write(
            self.style.SUCCESS(
                f"Temáticas del CU-07 válidas: la Clásica y {len(de_pago)} de pago "
                f"({', '.join(t['nombre'] for t in de_pago)}), con "
                f"{len(catalogo_tematicas['terminos'])} términos en el glosario."
            )
        )
