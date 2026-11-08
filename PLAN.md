# Plan: `reporter.py`, estadísticas por artista desde Chinook (JSON/CSV)

> Plan actualizado al estado de `main` después del PR #6 y de las correcciones de la revisión de código de `reporter.py`.
> Reemplaza al plan original aprobado en modo plan, que describía solo la primera versión (PR #5, commit `e58d374`).
> La sección [Historial de cambios respecto del plan original](#historial-de-cambios-respecto-del-plan-original) resume qué cambió y por qué.

## Contexto

La API Flask solo expone `GET /db/artists/<id>/albums` desde `chinook.db`.
`reporter.py` cubre otra necesidad: un reporte offline con una fila por artista (álbumes, pistas, duración, géneros, ingresos reales y unidades vendidas), exportable a JSON o CSV.
Se usa como módulo importable y como CLI.
No es un endpoint Flask: no modifica `routes.py` y de `db_routes.py` solo reutiliza `get_db_connection()`.

Datos de referencia verificados en `chinook.db` (solo lectura):

- 275 artistas, 347 álbumes; 71 artistas sin álbumes y 110 sin ventas; ningún nombre duplicado.
- 21 nombres de artista contienen comas o comillas y 25 títulos de álbum contienen comas (relevante para CSV).
- AC/DC (ID 1): 2 álbumes, 18 pistas, 4 853 674 ms, ingresos 15.84, 16 unidades, géneros `Rock`.
- Iron Maiden (ID 90): 21 álbumes, 213 pistas, 71 844 745 ms, ingresos 138.60, 140 unidades, géneros `Blues; Heavy Metal; Metal; Rock`.
- Artista 25: todo en 0 y sin géneros.
- Top 3 por ingresos: Iron Maiden (138.60), U2 (105.93), Metallica (90.09).
- Ingresos totales: 2328.60 = `SUM(UnitPrice * Quantity)` de `InvoiceLine`.
- Con `REAL`, U2 da `105.92999999999999`; por eso los montos se suman en centavos enteros.

## Diseño de `reporter.py`

### Modelos de datos

`dataclass(frozen=True, slots=True)`, sin Pydantic: los datos salen de SQL agregado con tipos controlados.
(Desde el PR #3, importar `db_routes` carga Pydantic de forma indirecta, pero el reporte no lo usa.)

**`ArtistStats`**, en este orden (es también el orden del JSON y de las columnas CSV):

| Campo | Tipo | Origen |
|---|---|---|
| `artist_id` | `int` | `Artist.ArtistId` |
| `name` | `str` | `Artist.Name` |
| `album_count` | `int` | álbumes del artista |
| `track_count` | `int` | pistas de sus álbumes |
| `total_duration_ms` | `int` | `SUM(Track.Milliseconds)` |
| `avg_track_duration_ms` | `int` | promedio redondeado; 0 sin pistas |
| `revenue` | `float` | `SUM(InvoiceLine.UnitPrice * Quantity)` en centavos, convertido con `round(c / 100, 2)` |
| `units_sold` | `int` | `SUM(InvoiceLine.Quantity)` |
| `genres` | `tuple[str, ...]` | géneros distintos de sus pistas, ordenados; `()` sin pistas |
| `albums` | `tuple[AlbumStats, ...] \| None` | solo con el detalle; `None` si no se pidió |

**`AlbumStats`**: `album_id`, `title`, `track_count`, `total_duration_ms`, `revenue`, `units_sold`.

Constantes derivadas:

- `FIELDS`: columnas del CSV por artista (todos los campos menos `albums`).
- `ALBUM_FIELDS`: columnas del CSV por álbum (`artist_id`, `artist_name` y los campos de `AlbumStats`).
- `GENRE_SEPARATOR = "; "`: separador de géneros en CSV.
- `SORT_COLUMNS`: lista blanca de órdenes (`ORDER BY` no admite parámetros).
  `name` y `artist_id` ascendentes, con `name` en `COLLATE NOCASE`; las métricas numéricas, descendentes.
  Los empates se desempatan por `ArtistId`.
- `REQUIRED_SCHEMA`: tablas y columnas que el reporte lee.

### Consultas SQL

Todas usan parámetros `?`; solo `ORDER BY` se arma desde `SORT_COLUMNS`.
Las listas de IDs se pasan como **un único parámetro JSON** (`IN (SELECT value FROM json_each(?))`), porque SQLite limita la cantidad de variables por consulta (32 766) y una base con más artistas pasada con `--db` fallaría.
Los valores que el esquema de Chinook permite en `NULL` (`Artist.Name`, `Album.Title`, `Track.Milliseconds`, `Genre.Name`) se convierten en `''` o `0`, o se omiten, para que ninguna métrica sea `None`.

1. **Métricas por artista** (`_STATS_SQL`, una sola consulta para todos los artistas).
   `Artist LEFT JOIN` tres subconsultas, cada una agregada por artista antes de unirse, para que ningún JOIN multiplique las filas de otro:
   álbumes (`Album`), pistas y duración (`Track` + `Album`), ventas en centavos y unidades (`InvoiceLine` + `Track` + `Album`).
   `COALESCE(..., 0)` deja en 0 a los artistas sin álbumes o sin ventas.
   Filtros opcionales: `WHERE ar.ArtistId = ?` o `WHERE ar.ArtistId IN (...)`; después, `ORDER BY` y `LIMIT ?`.
2. **Géneros** (`_GENRES_SQL`): `DISTINCT ArtistId, Genre.Name` solo para los artistas que devolvió la consulta 1.
3. **Detalle por álbum** (`_ALBUMS_SQL`, solo con el detalle): por álbum, pistas y duración, y ventas en centavos, con subconsultas agregadas por `AlbumId`; ordenado por título.
4. **Búsqueda por nombre** (solo con `--artist` o `--artist-contains`): lee `ArtistId, Name` y compara en Python.

Según las opciones se ejecutan entre 1 y 4 consultas (la 2 se omite si no hay resultados), más la validación del esquema, sin importar cuántos artistas haya.

### Funciones públicas

| Función | Responsabilidad |
|---|---|
| `validate_schema(connection)` | Comprueba `REQUIRED_SCHEMA` con `pragma_table_info(?)`, sin distinguir mayúsculas. Lanza `SchemaError` con **todas** las tablas y columnas que faltan. |
| `find_artist_id(connection, name) -> int \| None` | Nombre exacto con `casefold()` en Python (también pliega letras con acento, a diferencia de `LOWER`/`NOCASE` de SQLite). Ignora espacios externos. |
| `find_artist_ids_containing(connection, text) -> list[int]` | Todos los artistas cuyo nombre contiene el texto, con el mismo plegado, en orden de ID. Texto vacío → `[]`. |
| `get_artist_stats(connection, *, artist_id=None, artist_ids=None, top=None, sort_by="revenue", include_albums=False)` | Ejecuta las consultas 1 a 3. No abre ni cierra la conexión. `top` se aplica después del filtro. `ValueError` si `sort_by` no está en la lista blanca, si `top < 1` o si se pasan `artist_id` y `artist_ids` a la vez. |
| `to_json(stats, file)` | Lista de objetos, `ensure_ascii=False`, `indent=2`, salto de línea final. `albums` solo aparece si se pidió el detalle. |
| `to_csv(stats, file, *, detail=False)` | `csv.DictWriter`. Sin detalle: una fila por artista, `revenue` con 2 decimales y géneros unidos con `; `. Con detalle: una fila por álbum (los artistas sin álbumes no generan filas). |
| `export(stats, file, *, fmt, detail=False)` | Elige `to_json` o `to_csv` sobre un archivo ya abierto. `ValueError` con un formato desconocido. |
| `write_output(path, stats, *, fmt, detail=False)` | Valida los argumentos **antes** de tocar el disco, crea los directorios que falten y escribe en UTF-8 con `newline=""` en un archivo temporal del mismo directorio que después reemplaza al destino. Un error nunca deja el reporte vacío o a medias. Conserva los permisos de un archivo existente, escribe a través de un enlace simbólico y no reemplaza un archivo de solo lectura. Deja propagar `ValueError` y `OSError`. |
| `parse_args(argv=None)` / `main(argv=None) -> int` | CLI. `main` devuelve el código de salida en lugar de llamar a `sys.exit()`, para poder probarlo sin lanzar un proceso. |

Conexión: `get_db_connection(path=None)` de `db_routes.py`, siempre en modo de solo lectura (`?mode=ro`), con `row_factory = sqlite3.Row`.
Sin `path` usa `CHINOOK_DB_PATH`, así que la API Flask no cambia.

### CLI

```sh
uv run python reporter.py --format {json,csv} [--output RUTA] [--db RUTA]
    [--artist-id N | --artist NOMBRE | --artist-contains TEXTO]
    [--top N] [--sort-by CAMPO] [--detail]
```

| Opción | Comportamiento |
|---|---|
| `--format` | Obligatorio: `json` o `csv`. |
| `--output RUTA` | Archivo en UTF-8; crea los directorios que falten. Sin esta opción escribe a stdout. |
| `--db RUTA` | Base SQLite a leer, en solo lectura. Por defecto, `chinook.db` del repositorio. |
| `--artist-id N` | Un artista por ID (entero entre 1 y 2^63−1, el máximo que acepta SQLite). |
| `--artist NOMBRE` | Un artista por nombre exacto, sin distinguir mayúsculas. |
| `--artist-contains TEXTO` | Todos los artistas cuyo nombre contiene el texto (no vacío), sin distinguir mayúsculas. |
| `--top N` | Los primeros N según el orden (entero entre 1 y 2^63−1), después del filtro de artista. |
| `--sort-by CAMPO` | Un campo de `SORT_COLUMNS`; por defecto `revenue`. |
| `--detail` | Detalle por álbum: anidado en JSON, una fila por álbum en CSV. |

`--artist-id`, `--artist` y `--artist-contains` son mutuamente excluyentes.
Cuando todo sale bien, el CLI no imprime nada además del reporte, para que la salida a stdout se pueda redirigir o encadenar.
Si quien lee stdout cierra la tubería antes de tiempo (por ejemplo, `| head`), el CLI termina con código 1 sin mostrar un traceback.

Flujo de `main()`: parsear argumentos → abrir la conexión con `closing(...)` → `validate_schema` → resolver el filtro de artista y consultar (`_select_stats`) → escribir con `export` (stdout) o `write_output` (archivo).
Los errores al abrir o validar la base y los errores durante las consultas se informan por separado.

### Manejo de errores

Todos los mensajes del CLI están en español y tienen la forma `error: ...` en stderr.

| Caso | Mensaje | Código |
|---|---|---|
| Argumentos inválidos (formato, orden, enteros fuera de rango, texto vacío, opciones incompatibles, faltantes o desconocidas) | Línea `uso: ...` y, por ejemplo, `error: argumento --top: '0' debe ser mayor o igual que 1` | 2 |
| Base inexistente, dañada o ilegible (`sqlite3.Error` al abrir o validar) | `error: no se pudo abrir la base de datos: ...` | 1 |
| Error durante las consultas (`sqlite3.Error`, por ejemplo `database is locked`) | `error: no se pudo consultar la base de datos <ruta>: ...` | 1 |
| SQLite válido sin el esquema de Chinook (`SchemaError`) | `error: <ruta> no es una base Chinook válida: falta la tabla Artist; faltan columnas en Track: GenreId` | 1 |
| `--artist-id` inexistente | `error: no se encontró el artista con ID N` | 1 |
| `--artist` sin coincidencia | `error: no se encontró el artista 'X'` | 1 |
| `--artist-contains` sin coincidencias | `error: ningún artista contiene 'X' en el nombre` | 1 |
| `--output` no escribible (`OSError`: es un directorio, el padre es un archivo, permisos) | `error: no se pudo escribir <ruta>: ...` | 1 |
| stdout cerrado por quien lee (`BrokenPipeError`) | — (sin traceback) | 1 |
| Éxito | — | 0 |

Los errores de argparse se traducen en `_SpanishArgumentParser.error()` con las plantillas de Python 3.12 (`_ARGPARSE_TRANSLATIONS`).
Un mensaje que no esté en la lista se muestra tal cual en lugar de ocultarse.
No se traducen, a propósito: el texto de `--help`, los `ValueError` de las funciones de biblioteca (en inglés, como el resto del código) y el 404 `{"error": "Artist not found"}` de la API, que es parte de su contrato.

## Pruebas

132 pruebas del reporte, dentro de las 209 del repositorio.

**`test_reporter.py`** (78, integración contra el `chinook.db` real):

- Una fila por artista (275); ninguna métrica `None`; valores exactos de AC/DC, Iron Maiden y del artista 25.
- Totales iguales a los de las tablas originales (álbumes, pistas, duración, unidades, ingresos 2328.60): detectan conteos inflados.
- Géneros ordenados, distintos y existentes en `Genre`; solo los artistas sin pistas no tienen géneros.
- Detalle por álbum: para los 275 artistas, sus álbumes suman exactamente los totales del artista; orden por título.
- Órdenes (ingresos por defecto, nombre sin distinguir mayúsculas, métricas descendentes), `top`, filtros por ID y por lista de IDs, y errores de `ValueError`.
- Búsqueda exacta y parcial: mayúsculas, acentos (`"ANTÔNIO CARLOS JOBIM"`, `"NAÇÃO"`), espacios, sin coincidencias.
- `validate_schema` acepta el `chinook.db` real.
- CLI: JSON a stdout, CSV a archivo, `--artist`, `--artist-contains`, `--detail` en JSON y CSV, `--db` con base inexistente (sin crear el archivo), dañada o vacía, creación de directorios, salida no escribible, y los 8 errores de uso comparados con el texto exacto en español.

**`test_reporter_unit.py`** (54, sin `chinook.db`):

- Exportadores con datos armados a mano e `io.StringIO`: orden de claves, acentos sin escapar, nombres con comas y comillas, listas vacías, detalle anidado y una fila por álbum.
- Agregación sobre una base SQLite en memoria con datos conocidos: ventas repetidas que no inflan conteos, 0.99 × 3 = 2.97 exacto, géneros, detalle por álbum.
- `validate_schema`: todas las tablas o columnas que faltan, sin distinguir mayúsculas.
- `export` y `write_output`: formatos, directorios, UTF-8, fines de línea `\r\n` sin líneas en blanco extra, sobrescritura, errores de ruta; validación antes de escribir, archivo anterior intacto si la exportación falla, permisos conservados, enlaces simbólicos, archivos de solo lectura.
- Casos borde de la revisión de código: enteros mayores que 2^63−1, tubería cerrada (con un subproceso real), 40 000 artistas (más que el límite de variables de SQLite), valores `NULL` permitidos por el esquema y errores de consulta.
- CLI de punta a punta con `--db` sobre una base pequeña en `tmp_path`, sin `monkeypatch`; una prueba confirma que el CLI nunca escribe en la base.

## Documentación

- `README.md`: sección "Reporte de artistas" con ejemplos, tabla de opciones, campos, ejemplo JSON, validación del esquema, mensajes de error y códigos de salida.
- `CLAUDE.md`: comando del reporte en "Comandos" y descripción de `reporter.py` en "Arquitectura".

## Historial de cambios respecto del plan original

| PR | Cambio | Motivo |
|---|---|---|
| #5 | `--sort-by name` con `COLLATE NOCASE` | Con orden por bytes, "AC/DC" quedaba antes que "Aaron". |
| #5 | `--artist`, `find_artist_id` con `casefold()` | Buscar por nombre es más cómodo que por ID; `LOWER` de SQLite no pliega letras con acento. |
| #5 | Campo `genres` y `--detail` con `AlbumStats` | Información útil de la versión alternativa que se comparó; en CSV, una fila por álbum en lugar de mezclar dos tablas en un archivo. |
| #5 | `--db` y `get_db_connection(path=None)` | Permite usar otra base y reemplazar `monkeypatch` en las pruebas por bases reales en `tmp_path`. |
| #5 | `--output` crea los directorios | Evita un error común. |
| #3 + #5 | Conflicto en `db_routes.py` y `CLAUDE.md` resuelto conservando ambos cambios (`AlbumOut` + `get_db_connection(path)`) | El PR #3 se fusionó antes que el #5. |
| #6 | `write_output()` y `export()` como funciones propias | La escritura estaba dentro de `main()` y `_export` dependía de `argparse.Namespace`. |
| #6 | `validate_schema()` y `SchemaError` | Una base sin las tablas de Chinook mostraba un engañoso "no se pudo abrir la base de datos: no such table: Artist". |
| #6 | `--artist-contains` y `artist_ids=` | Búsqueda parcial además de la exacta. |
| #6 | Todos los mensajes del CLI en español | Los mensajes mezclaban español e inglés. |
| Revisión | Límite de 2^63−1 en `--top` y `--artist-id` | Un número mayor terminaba en un traceback `OverflowError`. |
| Revisión | `write_output` valida antes de escribir y reemplaza el archivo de forma atómica | Un formato inválido vaciaba el archivo anterior. |
| Revisión | `BrokenPipeError` manejado al escribir a stdout | `\| head` mostraba dos tracebacks. |
| Revisión | IDs como un parámetro JSON con `json_each(?)` | Más de 32 766 artistas superaban el límite de variables de SQLite. |
| Revisión | `NULL` en nombres, títulos, duraciones y géneros | Un `Artist.Name` en `NULL` rompía la búsqueda con `AttributeError`. |
| Revisión | Errores de consulta separados de los de apertura | Un `database is locked` se mostraba como "no se pudo abrir la base de datos". |

Partes del plan original que quedaron obsoletas: la sección "Rama" (`feat/artist-reporter` ya se fusionó y se borró), el riesgo "si el PR #3 se fusiona no cambia `get_db_connection`" y la prueba de base inexistente con `monkeypatch`.

## Riesgos y decisiones abiertas

- **Ingresos en JSON como número** (`138.6`, no `"138.60"`). Si algún consumidor necesita siempre 2 decimales, habría que emitir texto o centavos enteros.
- **Traducción de argparse atada a Python 3.12.** Si una versión futura cambia sus plantillas, esos mensajes aparecerán sin traducir (no se ocultan). Las pruebas de texto exacto lo detectarían.
- **Acoplamiento a `db_routes`.** `reporter.py` importa `db_routes`, que trae Flask y Pydantic. Si se quisiera usar el reporte sin esas dependencias, habría que mover `get_db_connection` a un módulo propio.
- **`--sort-by name`** usa `NOCASE`, que solo ignora mayúsculas en letras sin acento; la búsqueda por nombre sí pliega acentos. La diferencia solo afecta el orden de nombres que empiezan con una mayúscula acentuada.
- **Pistas sin álbum:** hoy no existen en Chinook (`Track.AlbumId` nunca es `NULL`); si aparecieran, no se atribuirían a ningún artista.
- **stdout en Windows:** `sys.stdout` no usa `newline=""`, así que el CSV por stdout podría tener líneas en blanco extra, y una consola que no use UTF-8 podría fallar con los acentos. No se pudo probar; con `--output` no ocurre.
- **Fuera de alcance:** filtro por fechas (`--since`/`--until` sobre `Invoice.InvoiceDate`; las facturas van de 2009 a 2013) y géneros por álbum en el detalle.

## Verificación

```sh
uv sync
uv run pytest                                   # 209 pruebas
uv run ruff check . && uv run ruff format --check .
uv run python reporter.py --format json --top 3              # Iron Maiden, U2, Metallica
uv run python reporter.py --format csv --artist-contains jobim --detail
uv run python reporter.py --format json --artist-id 999999; echo "exit=$?"   # 1, mensaje en español
uv run python reporter.py --format xml; echo "exit=$?"                       # 2, mensaje en español
uv run python reporter.py --format json | head -c 20                         # sin traceback
```

El checksum de `chinook.db` no debe cambiar después de ejecutar el reporte y las pruebas.
