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
| `/db/artists/<artist_id>/albums` | Devuelve los álbumes del artista ordenados por título (`album_id`, `title`, `artist_id`). Responde 404 si el artista no existe y `[]` si existe pero no tiene álbumes. |

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

## Estructura del proyecto

| Archivo | Contenido |
|---|---|
| `app.py` | Crea la app Flask, configura las sesiones y registra las rutas. |
| `config.py` | Configuración de Flask-Session (sesiones guardadas en `flask_session/`). |
| `models.py` | Clases `Artist` y `Album` y el almacén en memoria con los datos de ejemplo. |
| `routes.py` | Endpoints que usan los datos en memoria. |
| `db_routes.py` | Blueprint `/db` con los endpoints que consultan `chinook.db` y el modelo Pydantic `AlbumOut` que valida sus respuestas. |
| `analytics.py` | Funciones puras de estadísticas usadas por `/stats/*`. |
| `chinook.db` | Base de datos de ejemplo Chinook (SQLite). |
| `test_routes.py`, `test_db_routes.py` | Pruebas con pytest. |

## Desarrollo

```sh
uv run pytest                 # ejecutar las pruebas
uv run ruff check .           # lint
uv run ruff format .          # formatear el código
```
