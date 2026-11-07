# CLAUDE.md

Este archivo orienta a Claude Code (claude.ai/code) cuando trabaja con el código de este repositorio.

## Estado del proyecto

Creado con `uv init --package` y usado después para alojar la **variante base** del ejercicio Music Analytics API: una API REST mínima en Flask que funciona principalmente con **datos simulados en memoria**, más un endpoint SQLite de solo lectura (un Blueprint bajo `/db`) que consulta `chinook.db`. Los módulos de la API (`app.py`, `config.py`, `models.py`, `routes.py`, `db_routes.py`, `analytics.py`) y las suites de pytest (`test_routes.py`, `test_db_routes.py`) están en la raíz del repositorio como módulos planos de nivel superior, no dentro del paquete.

El paquete `src/music_analytics_api/` todavía contiene solo el `main()` de ejemplo generado al crear el proyecto. El README está vacío.

## Herramientas

- Python 3.12 (fijado en `.python-version`), gestionado con **uv**; el backend de build es `uv_build`.
- Dependencias de ejecución: `flask`, `flask-session`, `cachelib`. Dependencias de desarrollo (`[dependency-groups].dev`, instaladas por defecto con `uv sync`): `pytest`, `ruff`.
- Ruff es el linter y formateador (reglas por defecto; la única configuración es `[tool.ruff.lint.isort] known-third-party = ["flask_session"]`, necesaria porque, de lo contrario, el directorio de sesiones `flask_session/` haría que ruff ordene ese paquete como first-party).
- Estructura `src/`: el paquete `music_analytics_api` está en `src/music_analytics_api/`. El script de consola `music-analytics-api` apunta a `music_analytics_api:main` (`[project.scripts]` en `pyproject.toml`).
- `.claude/agents/code-reviewer.md` es un subagente de revisión de solo lectura (nomenclatura, manejo de errores, rendimiento) que ejecuta ruff como parte de su revisión.
- `.claude/skills/unit-tests` es una skill para escribir y ejecutar pruebas con pytest.

## Comandos

```sh
uv sync                    # crear/actualizar .venv a partir de uv.lock
uv add <pkg>               # agregar una dependencia de ejecución (actualiza pyproject.toml + uv.lock)
uv add --dev <pkg>         # agregar una dependencia de desarrollo
uv run ruff check .        # lint (agrega --fix para corregir automáticamente)
uv run ruff format .       # formatear el código (--check solo verifica)
uv build                   # construir sdist/wheel en dist/
uv run music-analytics-api # ejecutar el punto de entrada CLI de ejemplo del paquete
```

Music Analytics API (ejecutar desde la raíz del repositorio):

```sh
uv run flask run                  # ejecutar la API (o: uv run python app.py)
FLASK_DEBUG=1 uv run python app.py  # el modo debug es opcional (desactivado por defecto)
uv run pytest                     # ejecutar todas las pruebas
uv run pytest test_routes.py::test_name  # ejecutar una sola prueba
```

`SECRET_KEY` se lee del entorno; si no está definida, se genera una clave aleatoria por proceso.

## Arquitectura (Music Analytics API)

Flujo de una petición: `app.py` crea la app Flask, configura las sesiones, registra el Blueprint `db_routes` y luego importa `routes` por su efecto secundario de registrar las rutas en `app` (`routes.py` hace `from app import app`; este import circular solo funciona porque `app.py` importa `routes` *después* de que `app` está completamente definida). Los handlers de las rutas usan `models.music_store` para obtener datos y `analytics.py` para las funciones estadísticas puras, y luego devuelven `jsonify(...)`.

- `app.py`: punto de entrada de la app Flask. Es dueño de la instancia de la app; los demás módulos importan `app` desde aquí en lugar de crear la suya.
- `config.py`: configuración de Flask-Session basada en el sistema de archivos (`cachelib`); los archivos de sesión van a `flask_session/`.
- `models.py`: capa de datos en memoria. Contiene las clases `Artist`/`Album` y un `MusicStore` que se carga al importarse con datos de ejemplo fijos en el código (5 artistas, 8 álbumes). Una única instancia `music_store` a nivel de módulo es el almacén compartido que usan todas las rutas.
- `routes.py`: todos los handlers de rutas en memoria (`/artists`, `/artists/search`, `/artists/<id>`, `/artists/<id>/albums`, `/albums`, `/stats/albums`, `/stats/average-tracks`).
- `db_routes.py`: Blueprint `db_bp` (`url_prefix="/db"`) respaldado por `chinook.db`, ubicado en la raíz del repositorio. `GET /db/artists/<id>/albums` devuelve los álbumes del artista ordenados por título (con las claves `album_id`, `title`, `artist_id`, como la API en memoria pero sin `track_count`), o un 404 `{"error": "Artist not found"}` si el artista no está en la tabla `Artist`. Cada petición abre una conexión de solo lectura (`mode=ro`), usa consultas parametrizadas y la cierra al terminar. A diferencia de `routes.py`, no importa `app`: es `app.py` quien lo importa y llama a `app.register_blueprint(db_bp)`. El prefijo `/db` existe para no chocar con la ruta en memoria `/artists/<id>/albums` de `routes.py`. Se prueba en `test_db_routes.py` contra el `chinook.db` real (las tablas de Chinook tienen nombres en singular: `Artist`, `Album`, `Track`, ...).
- `analytics.py`: funciones puras (`calculate_album_stats`, `calculate_average_tracks`) que usan las rutas `/stats/*`. `calculate_album_stats` filtra por `min_tracks`, aplica un multiplicador de popularidad, clasifica los resultados en los niveles `platinum`/`gold` y devuelve solo los 5 primeros.

Las nuevas rutas respaldadas por SQLite deben ir en el Blueprint `db_routes` (bajo `/db`), no en `routes.py`. Los hooks de petición y el middleware pertenecen a otra variante del ejercicio (`-with-hooks`), que no está en este repositorio.

Convenciones de código usadas en todo el proyecto: type hints en los parámetros de las funciones, docstrings en las funciones públicas y PEP 8.
