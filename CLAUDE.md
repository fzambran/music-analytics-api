# CLAUDE.md

Este archivo orienta a Claude Code (claude.ai/code) cuando trabaja con el código de este repositorio.

## Estado del proyecto

Creado con `uv init --package` y usado después para alojar la **variante base** del ejercicio Music Analytics API: una API REST mínima en Flask que funciona principalmente con **datos simulados en memoria**, más un endpoint SQLite de solo lectura (un Blueprint bajo `/db`) que consulta `chinook.db`.

Estructura del repositorio:

- `src/music_analytics_api/`: todo el código de la aplicación. Los módulos de la API (`app.py`, `config.py`, `models.py`, `routes.py`, `db_routes.py`, `analytics.py`), el explorador `/ui` (`ui.py` y `templates/ui.html`) y el script de reportes `reporter.py`. Entre ellos se importan con rutas absolutas (`from music_analytics_api.db_routes import ...`). `__init__.py` contiene `main()`, el punto de entrada del script de consola, que importa `app` dentro de la función para que importar el paquete no cargue Flask.
- `tests/`: las suites de pytest (`test_app.py`, `test_routes.py`, `test_db_routes.py`, `test_db_routes_unit.py`, `test_reporter.py`, `test_reporter_unit.py`, `test_ui.py`) y `conftest.py` (su hook solo escribe un resumen si `PYTEST_RESULTS_LOG` está definida). `pyproject.toml` fija `testpaths = ["tests"]`. Las pruebas importan el paquete instalado en modo editable por `uv sync`, no archivos sueltos de la raíz.
- `data/chinook.db`: la base Chinook. `CHINOOK_DB_PATH` (en `db_routes.py`) se lee de la variable de entorno del mismo nombre al importar el módulo y se guarda absoluta (`expanduser().resolve()`, relativa al directorio actual), porque `get_db_connection()` la convierte en URI con `as_uri()`; si no está definida, la ubica respecto de `db_routes.py` (`parents[2] / "data"`), lo que solo funciona desde una copia del repositorio. La base no se incluye en el wheel.
- `docs/`: documentación de diseño (`PLAN.md`).
- La raíz contiene solo la configuración del proyecto, `README.md` y `CLAUDE.md`. Los archivos nuevos van en estas carpetas, no en la raíz.

El `README.md` documenta la instalación, el uso y los endpoints en español.

## Herramientas

- Python 3.12 (fijado en `.python-version`), gestionado con **uv**; el backend de build es `uv_build`.
- Dependencias de ejecución: `flask`, `flask-session`, `cachelib`, `pydantic`. Dependencias de desarrollo (`[dependency-groups].dev`, instaladas por defecto con `uv sync`): `pytest`, `ruff`.
- Ruff es el linter y formateador (reglas por defecto; la única configuración es `[tool.ruff.lint.isort] known-third-party = ["flask_session"]`, porque un directorio `flask_session/` en la raíz, como el que creaban las versiones anteriores al guardar sesiones en el directorio actual, haría que ruff ordene ese paquete como first-party; se mantiene para que el orden de imports no dependa de lo que haya en disco).
- Estructura `src/`: el paquete `music_analytics_api` está en `src/music_analytics_api/`. El script de consola `music-analytics-api` apunta a `music_analytics_api:main` (`[project.scripts]` en `pyproject.toml`) e inicia la API con `run_server()` de `app.py`, igual que `python -m music_analytics_api.app`.
- `.claude/agents/code-reviewer.md` es un subagente de revisión de solo lectura (nomenclatura, manejo de errores, rendimiento) que ejecuta ruff como parte de su revisión.
- Skills del proyecto en `.claude/skills/`:
  - `unit-tests`: escribe y ejecuta pruebas con pytest.
  - `refactor`: refactoriza sin cambiar el comportamiento, con las pruebas en verde antes y después de cada paso (usa `unit-tests`).
  - `commit-message-writer`: escribe mensajes de commit en Conventional Commits, en inglés y con los tipos y scopes del proyecto (`api`, `db`, `reporter`, `deps`, `claude`), y hace el commit si se le pide. Nunca hace commit en `main`; después del commit sigue con `pull-request`.
  - `pull-request`: sube la rama, abre el PR con `gh` y espera el CI. No fusiona.
  - `merge-pr`: solo cuando se le pide, fusiona el PR con squash (con el CI en verde y sin conflictos) y actualiza `main`.

## Comandos

```sh
uv sync                    # crear/actualizar .venv a partir de uv.lock
uv add <pkg>               # agregar una dependencia de ejecución (actualiza pyproject.toml + uv.lock)
uv add --dev <pkg>         # agregar una dependencia de desarrollo
uv run ruff check .        # lint (agrega --fix para corregir automáticamente)
uv run ruff format .       # formatear el código (--check solo verifica)
uv build                   # construir sdist/wheel en dist/
uv run music-analytics-api # iniciar la API (lo mismo que python -m music_analytics_api.app)
```

Music Analytics API (ejecutar desde la raíz del repositorio):

```sh
uv run flask --app music_analytics_api.app run          # ejecutar la API
uv run flask --app music_analytics_api.app --debug run  # el modo debug es opcional (desactivado por defecto)
uv run pytest                     # ejecutar todas las pruebas
uv run pytest tests/test_routes.py::test_name  # ejecutar una sola prueba
uv run python -m music_analytics_api.reporter --format json --top 5  # reporte de artistas (json o csv)
```

`uv run python -m music_analytics_api.app` y `uv run music-analytics-api` también inician la API (en el puerto 5000, con debug si `FLASK_DEBUG=1`); ambos usan `run_server()`.

`SECRET_KEY` se lee del entorno; si no está definida, se genera una clave aleatoria por proceso. `CHINOOK_DB_PATH` cambia la base que usan `/db` y `reporter.py`.

## Arquitectura (Music Analytics API)

Flujo de una petición: `create_app()` en `app.py` crea la app Flask, configura las sesiones y registra tres Blueprints: `api_bp` (`routes.py`, rutas en memoria, sin prefijo), `db_bp` (`db_routes.py`, bajo `/db`) y `ui_bp` (`ui.py`, la página `/ui`). Ningún módulo importa `app.py` ni existe una instancia global de la app: `flask --app music_analytics_api.app` encuentra `create_app()` solo, y las pruebas crean su propia app con `create_app()` en cada fixture. Antes, `routes.py` hacía `from app import app` y registraba las rutas en esa instancia; al ejecutar el módulo como `__main__` había dos instancias y el servidor solo servía `/db` (`tests/test_app.py` cubre ese caso). Los handlers de las rutas usan `models.music_store` para obtener datos y `analytics.py` para las funciones estadísticas puras, y luego devuelven `jsonify(...)`.

- `app.py`: la fábrica `create_app()` y `run_server()`, que usan `python -m music_analytics_api.app` y el script `music-analytics-api`. Cada llamada a `create_app()` devuelve una app nueva e independiente.
- `config.py`: configuración de Flask (`SECRET_KEY`, `SESSION_TYPE = "cachelib"`). El almacén de sesiones (`FileSystemCache`) no va aquí sino en `create_app()`, porque cachelib crea su carpeta al construirse: así importar el paquete no crea nada en disco y cada app tiene su propio almacén en `<instance_path>/flask_session` (`src/instance/` desde el repositorio). La app se crea con `Flask("music_analytics_api")`, no con `__name__`, para que la carpeta de instancia sea la misma con `python -m`.
- `models.py`: capa de datos en memoria. Contiene las clases `Artist`/`Album` y un `MusicStore` que se carga al importarse con datos de ejemplo fijos en el código (5 artistas, 8 álbumes). Una única instancia `music_store` a nivel de módulo es el almacén compartido que usan todas las rutas.
- `routes.py`: Blueprint `api_bp` con todos los handlers de rutas en memoria (`/artists`, `/artists/search`, `/artists/<id>`, `/artists/<id>/albums`, `/albums`, `/stats/albums`, `/stats/average-tracks`).
- `db_routes.py`: Blueprint `db_bp` (`url_prefix="/db"`) respaldado por `data/chinook.db`. `GET /db/artists/<id>/albums` devuelve los álbumes del artista ordenados por título, o un 404 `{"error": "Artist not found"}` si el artista no está en la tabla `Artist`; si el artista existe pero no tiene álbumes, responde 200 con `[]`. Cada fila se valida y serializa con el modelo Pydantic `AlbumOut`, que mapea las columnas de Chinook (`AlbumId`, `Title`, `ArtistId`) a las claves de la API (`album_id`, `title`, `artist_id`; como la API en memoria pero sin `track_count`) mediante `validation_alias`. Una fila inválida provoca un `ValidationError`, no una respuesta con datos incorrectos. Los manejadores del Blueprint (`@db_bp.errorhandler`) convierten `ValidationError` en `500 {"error": "Invalid data in database"}` y `sqlite3.Error` en `500 {"error": "Database unavailable"}`. Como Flask no registra las excepciones que se manejan, cada manejador registra la traza con `current_app.logger.exception`; el mensaje al cliente es genérico. Solo cubren las vistas de `/db`: los 404 de rutas inexistentes y los 405 siguen siendo HTML de Flask. Cada petición abre una conexión de solo lectura (`mode=ro`) con `get_db_connection()`, que acepta una ruta opcional (por defecto `CHINOOK_DB_PATH`), usa consultas parametrizadas y la cierra al terminar. Como `routes.py`, no importa `app`: es `create_app()` quien llama a `app.register_blueprint(db_bp)`. El prefijo `/db` existe para no chocar con la ruta en memoria `/artists/<id>/albums` de `routes.py`. Se prueba en `test_db_routes.py` contra el `chinook.db` real (las tablas de Chinook tienen nombres en singular: `Artist`, `Album`, `Track`, ...).
- `ui.py`: Blueprint `ui_bp` con `GET /ui`, una página HTML (`templates/ui.html`, con CSS y JavaScript sin librerías, en el mismo archivo) para probar la API desde el navegador. La lista de endpoints no se escribe a mano: `api_endpoints()` la arma desde `current_app.url_map` (todas las rutas GET salvo `static` y las de `ui.`), con la plantilla de ruta (`/db/artists/{artist_id}/albums`) y sus parámetros; los de query string salen de `QUERY_PARAMS` (hoy solo `q` de `api.search_artists`), así que un parámetro nuevo de query hay que agregarlo ahí. `PRESETS` son los casos de prueba rápidos; la etiqueta empieza con el código esperado y `test_ui.py` envía cada uno y lo comprueba. Los datos llegan a la página como JSON en `<script id="...-data" type="application/json">` (`|tojson`), incluido el límite de `q`, que es `routes.MAX_QUERY_LENGTH` y no una copia en el JavaScript, y el JavaScript inserta todo con `textContent`, nunca como HTML. Los filtros de la respuesta (búsqueda, columna numérica ≥ valor, orden) son locales, no parámetros de la API. `test_ui.py` también exige ids únicos en la página: el script busca los elementos por id.
- `analytics.py`: funciones puras (`calculate_album_stats`, `calculate_average_tracks`) que usan las rutas `/stats/*`. `calculate_album_stats` filtra por `min_tracks`, aplica un multiplicador de popularidad, clasifica los resultados en los niveles `platinum`/`gold` y devuelve solo los 5 primeros.
- `reporter.py`: CLI y módulo importable (no es un endpoint Flask) que genera estadísticas por artista desde `chinook.db` (`album_count`, `track_count`, `total_duration_ms`, `avg_track_duration_ms`, `revenue`, `units_sold`, `genres` y, con `--detail`, `albums`) y las exporta a JSON o CSV (con `--detail`, el CSV tiene una fila por álbum). Reutiliza `get_db_connection(path)` de `db_routes.py` (solo lectura); `--db` elige otra base, y las pruebas lo usan con archivos SQLite en `tmp_path` en lugar de `monkeypatch`. `--artist-contains` busca todos los artistas cuyo nombre contiene el texto con `find_artist_ids_containing`, que compara ambos lados con `normalize_for_search` (sin mayúsculas, acentos, espacios ni puntuación: "acdc" encuentra "AC/DC"), y filtra con `get_artist_stats(..., artist_ids=...)`. `--artist` busca por nombre exacto con `find_artist_id`, que compara con `casefold()` en Python porque `LOWER`/`NOCASE` de SQLite solo pliegan ASCII. Al abrir la base, `main()` llama a `validate_schema(connection)`, que lanza `SchemaError` con todas las tablas o columnas faltantes de `REQUIRED_SCHEMA` (consulta `pragma_table_info(?)`); así el CLI distingue "no se pudo abrir la base" (`sqlite3.Error`) de "no es una base Chinook válida". La salida pasa por `export(stats, file, fmt=..., detail=...)`; Los mensajes de error del CLI están en español; los de argparse se traducen en `_SpanishArgumentParser.error()` con plantillas de Python 3.12 (`_ARGPARSE_TRANSLATIONS`; un mensaje sin traducción se muestra tal cual). Los `ValueError` de las funciones de biblioteca siguen en inglés, como el resto del código. `write_output(path, stats, ...)` expande `~` (como `get_db_connection`; si no, `--output=~/...` crearía un directorio `./~`), valida antes de tocar el disco, crea los directorios que falten y escribe en UTF-8 con `newline=""` en un temporal que reemplaza al destino con `os.replace` (conserva permisos, sigue enlaces simbólicos y no reemplaza archivos de solo lectura), y deja propagar `OSError` para que `main()` lo convierta en código 1. La consulta agrega cada tabla (`Album`, `Track`, `InvoiceLine`) en su propia subconsulta por artista antes de unirlas, para que los JOIN no inflen los conteos; incluye a los artistas sin álbumes o sin ventas con valores en 0. `revenue` son ventas reales (`InvoiceLine.UnitPrice * Quantity`) sumadas en centavos enteros para evitar errores de punto flotante. `get_artist_stats(connection, ...)` no abre ni cierra la conexión; `ORDER BY` se arma desde la lista blanca `SORT_COLUMNS`. Pruebas: `test_reporter.py` (integración contra `chinook.db` y el CLI) y `test_reporter_unit.py` (exportadores, agregación con SQLite en memoria y el CLI de punta a punta con `--db` sobre una base pequeña).

Las nuevas rutas respaldadas por SQLite deben ir en el Blueprint `db_routes` (bajo `/db`), no en `routes.py`. Los hooks de petición y el middleware pertenecen a otra variante del ejercicio (`-with-hooks`), que no está en este repositorio.

Convenciones de código usadas en todo el proyecto: type hints en los parámetros de las funciones, docstrings en las funciones públicas y PEP 8.
