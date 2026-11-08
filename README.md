# Music Analytics API

API REST en Flask para analítica musical. Sirve artistas, álbumes y estadísticas a partir de datos de ejemplo en memoria, y expone un endpoint adicional que consulta la base de datos [Chinook](https://github.com/lerocha/chinook-database) en SQLite.

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
uv run flask run                     # inicia la API en http://localhost:5000
FLASK_DEBUG=1 uv run python app.py   # inicia la API en modo debug
```

La clave de sesión se lee de la variable de entorno `SECRET_KEY`. Si no está definida, se genera una clave aleatoria cada vez que arranca el proceso.

## Endpoints

Todos los endpoints responden en JSON y aceptan solo `GET`.

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

Están agrupados en un Blueprint con el prefijo `/db` y leen `chinook.db` en modo de solo lectura.

| Endpoint | Descripción |
|---|---|
| `/db/artists/<artist_id>/albums` | Devuelve los álbumes del artista ordenados por título. Responde 404 si el artista no existe. |

### Ejemplos

```sh
curl localhost:5000/artists/3
# {"album_count": 1, "artist_id": 3, "name": "Aerosmith"}

curl localhost:5000/db/artists/1/albums
# [{"album_id": 1, "artist_id": 1, "title": "For Those About To Rock We Salute You"},
#  {"album_id": 4, "artist_id": 1, "title": "Let There Be Rock"}]

curl localhost:5000/db/artists/999999/albums
# {"error": "Artist not found"}   (HTTP 404)
```

## Reporte de artistas

`reporter.py` genera estadísticas por artista a partir de `chinook.db` y las exporta a JSON o CSV. Incluye a todos los artistas, también a los que no tienen álbumes ni ventas (con valores en 0).

```sh
uv run python reporter.py --format json --top 5                # los 5 con más ingresos, a stdout
uv run python reporter.py --format csv --output artistas.csv   # todos los artistas a un archivo
uv run python reporter.py --format json --artist-id 90         # un solo artista por ID
uv run python reporter.py --format json --artist "iron maiden" --detail   # por nombre, con detalle por álbum
uv run python reporter.py --format csv --detail --output reportes/albumes.csv   # una fila por álbum
```

| Opción | Descripción |
|---|---|
| `--format {json,csv}` | Formato de salida (obligatorio). |
| `--output RUTA` | Archivo de salida en UTF-8. Crea los directorios que falten. Si se omite, escribe a stdout. |
| `--db RUTA` | Base SQLite a leer, siempre en modo de solo lectura. Por defecto, `chinook.db` del repositorio. |
| `--artist-id N` | Solo el artista con ese ID. |
| `--artist NOMBRE` | Solo el artista con ese nombre exacto, sin distinguir mayúsculas, también en letras con acento (`"ANTÔNIO CARLOS JOBIM"` encuentra a `Antônio Carlos Jobim`). No se puede combinar con `--artist-id`. |
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

Códigos de salida: `0` si todo salió bien; `1` si no se pudo abrir la base de datos, el artista no existe o no se pudo escribir el archivo; `2` si los argumentos son inválidos.

## Estructura del proyecto

| Archivo | Contenido |
|---|---|
| `app.py` | Crea la app Flask, configura las sesiones y registra las rutas. |
| `config.py` | Configuración de Flask-Session (sesiones guardadas en `flask_session/`). |
| `models.py` | Clases `Artist` y `Album` y el almacén en memoria con los datos de ejemplo. |
| `routes.py` | Endpoints que usan los datos en memoria. |
| `db_routes.py` | Blueprint `/db` con los endpoints que consultan `chinook.db`. |
| `analytics.py` | Funciones puras de estadísticas usadas por `/stats/*`. |
| `reporter.py` | CLI que genera estadísticas por artista desde `chinook.db` en JSON o CSV. |
| `chinook.db` | Base de datos de ejemplo Chinook (SQLite). |
| `test_routes.py`, `test_db_routes.py`, `test_reporter.py`, `test_reporter_unit.py` | Pruebas con pytest. |

## Desarrollo

```sh
uv run pytest                 # ejecutar las pruebas
uv run ruff check .           # lint
uv run ruff format .          # formatear el código
```
