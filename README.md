# Music Analytics API

API REST en Flask para analítica musical. Sirve artistas, álbumes y estadísticas a partir de datos de ejemplo en memoria, y expone dos endpoints adicionales que consultan la base de datos [Chinook](https://github.com/lerocha/chinook-database) en SQLite.

## Requisitos

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

## Instalación

```sh
git clone git@github.com:fzambran/music-analytics-api.git
cd music-analytics-api
uv sync
```

`uv sync` crea el entorno virtual `.venv` e instala las dependencias, incluidas las de desarrollo (`pytest` y `ruff`).

## Uso

```sh
uv run flask --app music_analytics_api.app run           # inicia la API en http://localhost:5000
uv run flask --app music_analytics_api.app --debug run   # inicia la API en modo debug
uv run python -m music_analytics_api.app                 # alternativa sin la CLI de flask (FLASK_DEBUG=1 para debug)
uv run music-analytics-api                               # lo mismo, con el script de consola del paquete
```

En macOS, el puerto 5000 suele estar ocupado por AirPlay; usa otro con `run --port 5001`.

Variables de entorno:

| Variable | Uso |
|---|---|
| `SECRET_KEY` | Clave de sesión. Si no está definida, se genera una clave aleatoria cada vez que arranca el proceso. |
| `CHINOOK_DB_PATH` | Ruta de la base Chinook que usan los endpoints `/db` y el reporte. Por defecto, `data/chinook.db` del repositorio. Acepta rutas relativas al directorio actual y `~`. Es obligatoria si instalas el paquete como wheel, porque la base no viene incluida. |

### Explorador en el navegador

Con la API en marcha, abre `http://127.0.0.1:5000/ui` (o el puerto que uses) para probar los endpoints con un formulario:

- Eliges el endpoint y completas sus parámetros (`artist_id`, `q`, `limit`, `offset`). Los parámetros de query vacíos no se envían, así que la API usa sus valores por defecto. El formulario muestra la URL que se enviará y puede copiarla como comando `curl`.
- "Validar antes de enviar" revisa los parámetros en el navegador: los de la ruta según su tipo (por ejemplo, `artist_id` debe ser un entero), `q` (obligatorio, máximo 100 caracteres), `limit` (de 1 a 100) y `offset` (entero); desmárcalo para mandar valores inválidos y ver cómo responde la API.
- Los casos de prueba rápidos envían peticiones que responden 200, 400 y 404, incluido un 404 en HTML de Flask.
- La respuesta muestra el código de estado, el `Content-Type`, el tiempo y el número de resultados, como tabla o como JSON. La búsqueda, el filtro por columna numérica y el orden por columna se aplican en el navegador sobre la respuesta recibida, no son parámetros de la API.
- Con una respuesta paginada (`/db/artists`), los botones "Anterior" y "Siguiente" piden la página vecina con el mismo `limit`, y el texto entre ellos indica el rango ("21–40 de 275").
- `/artists` no está paginado: devuelve los 5 artistas de ejemplo de una vez. Al consultarlo, una nota lo indica y ofrece el botón "Ir a /db/artists" para recorrer los 275 artistas de Chinook por páginas.

La página usa la misma API, así que no necesita CORS ni dependencias adicionales.

Las sesiones se guardan en la carpeta de instancia de Flask (`src/instance/flask_session/` al trabajar desde el repositorio), no en el directorio desde donde se inicia la API.

## Endpoints

Todos los endpoints aceptan solo `GET`. `/ui` es la página HTML del explorador; no es parte de la API. Las respuestas y los errores de la API (400, 404 y los 500 de `/db`, con la forma `{"error": "..."}`) son JSON. Los errores que genera Flask por su cuenta siguen siendo páginas HTML: un 404 por una ruta que no existe y un 405 por otro método. Un `<artist_id>` debe estar formado solo por dígitos ASCII (se aceptan ceros a la izquierda: `/artists/0003` es el artista 3); cualquier otro valor, como `abc`, `-1` o `٣`, no coincide con la ruta y recibe ese 404 HTML. Un ID enorme sí coincide y responde `404 {"error": "Artist not found"}`.

### Datos en memoria

Usan un conjunto fijo de ejemplo: 5 artistas y 8 álbumes.

| Endpoint | Descripción |
|---|---|
| `/artists` | Lista todos los artistas. |
| `/artists/search?q=<texto>` | Busca artistas cuyo nombre contenga el texto (sin distinguir mayúsculas). `q` es obligatorio y tiene un máximo de 100 caracteres; si no, responde 400. |
| `/artists/<artist_id>` | Devuelve un artista. Responde 404 si no existe. |
| `/artists/<artist_id>/albums` | Devuelve los álbumes de un artista. Responde 404 si no existe. |
| `/albums` | Lista todos los álbumes. |
| `/stats/albums` | Devuelve los 5 álbumes más populares con más de 5 pistas, clasificados en los niveles `platinum` o `gold`. |
| `/stats/average-tracks` | Devuelve el promedio de pistas por álbum. |

### Base de datos Chinook

Están agrupados en un Blueprint con el prefijo `/db` y leen `data/chinook.db` en modo de solo lectura.

| Endpoint | Descripción |
|---|---|
| `/db/artists?limit=<n>&offset=<n>` | Lista los 275 artistas de Chinook por páginas, ordenados por `artist_id`. `limit` es el tamaño de la página (de 1 a 100; por defecto 20) y `offset`, cuántos artistas saltar (de 0 a 2⁶³−1, el mayor entero de SQLite; por defecto 0). Se aceptan ceros a la izquierda (`005` vale 5). Responde `{"items": [{"artist_id", "name"}, ...], "total", "limit", "offset"}`; con un `offset` mayor o igual que `total`, `items` es `[]`. Un `limit` u `offset` inválido (incluido un valor vacío) responde 400. |
| `/db/artists/<artist_id>/albums` | Devuelve los álbumes del artista ordenados por título (`album_id`, `title`, `artist_id`). Responde 404 si el artista no existe y `[]` si existe pero no tiene álbumes. Si la base no se puede abrir o consultar, responde 500 con `{"error": "Database unavailable"}`; si una fila no es válida, 500 con `{"error": "Invalid data in database"}`. El detalle del error queda en el log del servidor, no en la respuesta. |

### Ejemplos

```sh
curl localhost:5000/artists/3
# {"album_count": 1, "artist_id": 3, "name": "Aerosmith"}

curl localhost:5000/db/artists/1/albums
# [{"album_id": 1, "artist_id": 1, "title": "For Those About To Rock We Salute You"},
#  {"album_id": 4, "artist_id": 1, "title": "Let There Be Rock"}]

curl 'localhost:5000/db/artists?limit=2&offset=20'
# {"items": [{"artist_id": 21, "name": "Various Artists"}, {"artist_id": 22, "name": "Led Zeppelin"}],
#  "limit": 2, "offset": 20, "total": 275}

curl 'localhost:5000/db/artists?limit=0'
# {"error": "Query parameter 'limit' must be an integer from 1 to 100"}   (HTTP 400)

curl localhost:5000/db/artists/999999/albums
# {"error": "Artist not found"}   (HTTP 404)

# Con CHINOOK_DB_PATH apuntando a una base que no existe:
curl localhost:5000/db/artists/1/albums
# {"error": "Database unavailable"}   (HTTP 500)
```

## Reporte de artistas

`reporter.py` genera estadísticas por artista a partir de `data/chinook.db` y las exporta a JSON o CSV. Incluye a todos los artistas, también a los que no tienen álbumes ni ventas (con valores en 0).

```sh
uv run python -m music_analytics_api.reporter --format json --top 5                # los 5 con más ingresos, a stdout
uv run python -m music_analytics_api.reporter --format csv --output artistas.csv   # todos los artistas a un archivo
uv run python -m music_analytics_api.reporter --format json --artist-id 90         # un solo artista por ID
uv run python -m music_analytics_api.reporter --format csv --artist-contains orchestra   # todos los que contienen el texto
uv run python -m music_analytics_api.reporter --format json --artist "iron maiden" --detail   # por nombre, con detalle por álbum
uv run python -m music_analytics_api.reporter --format csv --detail --output reportes/albumes.csv   # una fila por álbum
```

| Opción | Descripción |
|---|---|
| `--format {json,csv}` | Formato de salida (obligatorio). |
| `--output RUTA` | Archivo de salida en UTF-8. Crea los directorios que falten. Acepta `~`. Si se omite, escribe a stdout. |
| `--db RUTA` | Base SQLite a leer, siempre en modo de solo lectura. Acepta `~`. Por defecto, `CHINOOK_DB_PATH` o, si no está definida, `data/chinook.db` del repositorio. |
| `--artist-id N` | Solo el artista con ese ID. |
| `--artist NOMBRE` | Solo el artista con ese nombre exacto, con sus espacios y signos de puntuación (`acdc` no encuentra a `AC/DC`, `ac/dc` sí), sin distinguir mayúsculas, también en letras con acento (`"ANTÔNIO CARLOS JOBIM"` encuentra a `Antônio Carlos Jobim`). No se puede combinar con `--artist-id` ni con `--artist-contains`. |
| `--artist-contains TEXTO` | Todos los artistas cuyo nombre contiene el texto, sin distinguir mayúsculas, acentos, espacios ni signos de puntuación (`acdc` encuentra a `AC/DC`, `guns n roses` a `Guns N' Roses` y `antonio` a `Antônio Carlos Jobim`). El texto debe tener al menos una letra o un número. Con textos cortos puede haber más coincidencias, porque la puntuación ya no separa las palabras. Se puede combinar con `--top` y `--sort-by`. No se puede combinar con `--artist-id` ni con `--artist`. |
| `--top N` | Solo los primeros N según el orden elegido. |
| `--detail` | Agrega el detalle por álbum: en JSON, una lista `albums` dentro de cada artista; en CSV, una fila por álbum. |
| `--sort-by CAMPO` | `revenue` (por defecto), `units_sold`, `album_count`, `track_count`, `total_duration_ms`, `avg_track_duration_ms` (de mayor a menor), `name` o `artist_id` (ascendente). Los empates se ordenan por `artist_id`. |

Cada fila tiene `artist_id`, `name`, `album_count`, `track_count`, `total_duration_ms`, `avg_track_duration_ms`, `revenue` (ventas reales, `InvoiceLine.UnitPrice × Quantity`), `units_sold` y `genres` (géneros de sus pistas, ordenados; en CSV, separados por `; `). En CSV, `revenue` siempre tiene 2 decimales.

Con `--detail`, cada álbum tiene `album_id`, `title`, `track_count`, `total_duration_ms`, `revenue` y `units_sold`, ordenados por título. El CSV con `--detail` tiene las columnas `artist_id`, `artist_name` y las del álbum; los artistas sin álbumes no generan filas.

```json
[
  {
    "artist_id": 90,
    "name": "Iron Maiden",
    "album_count": 21,
    "track_count": 213,
    "total_duration_ms": 71844745,
    "avg_track_duration_ms": 337299,
    "revenue": 138.6,
    "units_sold": 140,
    "genres": ["Blues", "Heavy Metal", "Metal", "Rock"]
  }
]
```

Antes de consultar, el reporte comprueba que la base tenga las tablas y columnas de Chinook que necesita (`Artist`, `Album`, `Track`, `Genre`, `InvoiceLine`). Si faltan, el error indica cuáles, por ejemplo: `error: otra.db no es una base Chinook válida: falta la tabla Artist`.

Todos los mensajes de error están en español, también los de argumentos inválidos (por ejemplo, `error: argumento --top: '0' debe ser mayor o igual que 1`). `--top` y `--artist-id` aceptan solo dígitos, con las mismas reglas que `limit` y `offset` de la API: `005` vale 5, pero `+5`, `1_000` o un valor con espacios no son números enteros. Si no hay resultados para el artista pedido, el mensaje es `error: no se encontró el artista 'X'`, `error: no se encontró el artista con ID N` o `error: ningún artista contiene 'X' en el nombre`.

Si falla una consulta después de abrir la base (por ejemplo, porque está bloqueada), el mensaje es `error: no se pudo consultar la base de datos <ruta>: ...`.
Si se escribe a un archivo, un error nunca deja el reporte anterior vacío o a medias: el archivo se reemplaza solo cuando el nuevo está completo.

Códigos de salida: `0` si todo salió bien; `1` si no se pudo abrir o consultar la base de datos, la base no tiene el esquema de Chinook, el artista no existe o no se pudo escribir el archivo; `2` si los argumentos son inválidos.

## Estructura del proyecto

```
music-analytics-api/
├── src/music_analytics_api/   código de la aplicación (el paquete que se instala)
├── tests/                     pruebas con pytest
├── data/chinook.db            base de datos de ejemplo Chinook (SQLite)
└── docs/                      documentación de diseño (PLAN.md)
```

| Módulo (`src/music_analytics_api/`) | Contenido |
|---|---|
| `app.py` | `create_app()`: crea la app Flask, configura las sesiones, registra el conversor de IDs (`AsciiIntConverter`) y los Blueprints de rutas. |
| `config.py` | Configuración de Flask (`SECRET_KEY` y el tipo de sesión). `create_app()` crea el almacén de sesiones en la carpeta de instancia. |
| `models.py` | Clases `Artist` y `Album` y el almacén en memoria con los datos de ejemplo. |
| `routes.py` | Blueprint con los endpoints que usan los datos en memoria. |
| `db_routes.py` | Blueprint `/db` con los endpoints que consultan `data/chinook.db` y los modelos Pydantic `AlbumOut` y `ArtistOut` que validan sus respuestas. |
| `analytics.py` | Funciones puras de estadísticas usadas por `/stats/*`. |
| `validation.py` | Validación de enteros compartida por la API (IDs de las rutas, `limit` y `offset`) y el reporte. |
| `ui.py` y `templates/ui.html` | Blueprint `/ui`: el explorador de la API en el navegador. |
| `reporter.py` | CLI que genera estadísticas por artista desde `data/chinook.db` en JSON o CSV. |

Las pruebas de `tests/` siguen el nombre del módulo que prueban (`test_routes.py`, `test_db_routes.py`, `test_reporter.py`, ...).

## Desarrollo

```sh
uv run pytest                 # ejecutar las pruebas
uv run ruff check .           # lint
uv run ruff format .          # formatear el código
```

Con `PYTEST_RESULTS_LOG=<ruta>`, cada ejecución de pytest agrega una línea con el resultado a ese archivo; sin la variable no escribe nada.
