# Logic Team - Entorno local

Django + PostgreSQL en Docker Compose, con frontend HTML/CSS/JS servido por Django en desarrollo.

## Requisitos
- Docker Desktop (con Docker Compose)
- Git

## Primer arranque
1. `cp .env.example .env` (o `make setup`)
2. `docker compose up --build` (o `make up`)
3. Abre http://localhost:8000 (debe decir "Servidor: ok · Base de datos: ok")
4. En otra terminal: `docker compose exec web python manage.py createsuperuser` (o `make superuser`)
5. Django Admin: http://localhost:8000/admin/

## Comandos utiles (Makefile)
| Comando | Que hace |
| --- | --- |
| `make up` / `make down` | Levanta / detiene los contenedores |
| `make test` | Ejecuta pytest |
| `make lint` / `make format` | Ruff |
| `make makemigrations` / `make migrate` | Migraciones |
| `make psql` | Consola de PostgreSQL |
| `make reset-db` | Borra los contenedores y el volumen de la base de datos |

## Estructura
- `config/`: configuracion del proyecto Django
- `game/`: app principal (modelos, API JSON, admin)
- `frontend/`: HTML, CSS y JS Vanilla

## Despliegue (Render + Neon)

La página se publica en [Render](https://render.com) con el Blueprint `render.yaml` de la raíz del repo, y la base de datos vive en [Neon](https://neon.com) (Postgres gratis que no caduca). Cada push a `main` vuelve a publicar la página.

- Construcción: `pip install -r requirements.txt && python manage.py collectstatic --noinput`.
- Arranque: `./start.sh` aplica las migraciones y levanta gunicorn.
- Variables en Render: `DATABASE_URL` (cadena de conexión de Neon), `DJANGO_SECRET_KEY` (la genera Render) y `DJANGO_DEBUG=0`. El dominio `*.onrender.com` se agrega solo a `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS`; otro dominio va en `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS`.
- En el plan gratis la página se duerme tras 15 minutos sin visitas; la siguiente visita tarda alrededor de un minuto en despertarla.
