# Ejemplos de mensajes de commit

Commits reales de este repositorio (entre paréntesis, el PR original) reescritos con las reglas de `SKILL.md`. Todas las primeras líneas miden 66 caracteres o menos.

## `feat` con pruebas y documentación: un solo commit (PR #10)

Preparado: `reporter.py`, `test_reporter.py`, `test_reporter_unit.py`, `README.md`, `CLAUDE.md`, `PLAN.md`.

```
feat(reporter): ignore accents and spaces in --artist-contains

find_artist_ids_containing now compares both sides with the new
normalize_for_search (NFKD, casefold, letters and digits only), so
"acdc" matches "AC/DC" and "nacao" matches "Nação Zumbi". A search
text without letters or digits is rejected with a Spanish usage error.

--artist (exact match) is unchanged, so names that differ only in
punctuation cannot collide.
```

Cinco de los seis archivos son pruebas o documentación, pero el cambio principal es una funcionalidad: el tipo es `feat` y no se sugiere dividir.

## `feat` que agrega una dependencia (PR #3)

Preparado: `db_routes.py`, `test_db_routes.py`, `pyproject.toml`, `uv.lock`, `README.md`, `CLAUDE.md`.

```
feat(db): validate /db album rows with a Pydantic model

- AlbumOut maps the Chinook columns (AlbumId, Title, ArtistId) to the
  API keys (album_id, title, artist_id) via validation_alias.
- An invalid row fails with a 500 instead of returning wrong data;
  404 "Artist not found" and 200 [] are unchanged.
- Add pydantic as a runtime dependency.
```

La dependencia existe para este cambio, así que va en el mismo commit. Las 156 líneas de `uv.lock` no se leen.

## `refactor` (PR #2)

Preparado: `db_routes.py`.

```
refactor(db): rename _connect to get_db_connection

Follows the common Flask + SQLite naming convention.

No behavior change.
```

## Fixes independientes: sugerir dividir (PR #9)

Preparado: siete correcciones de `reporter.py` encontradas en una revisión, con sus pruebas y su documentación. El historial lo registró como `Fix reporter issues found in code review`, una primera línea que no dice qué se corrigió. Lo esperado es sugerir un commit por corrección, por ejemplo:

```
fix(reporter): keep the previous report when writing output fails

write_output validates before touching the disk and writes to a
temporary file that replaces the target, so an invalid format, CSV
detail without albums or a failed export no longer empties the
previous report. It keeps the file mode, writes through symlinks and
does not replace read-only files.
```

```
fix(reporter): reject --top and --artist-id values above 2**63-1

They now fail with a Spanish usage error instead of an OverflowError
traceback.
```

## Cambios pequeños (PR #1, #12 y #11)

```
ci: run ruff and pytest on pushes to main and pull requests

- uv sync --locked (fails if uv.lock is out of date)
- ruff check and ruff format --check
- pytest
```

```
chore: ignore Quarto previews of README.md

quarto render/preview writes README.html and README_files/ next to
README.md. GitHub renders README.md directly, so they never belong in
the repository.
```

```
docs(reporter): sync PLAN.md with PRs #8, #9 and #10
```

El original era `Update PLAN.md after PRs #8, #9 and #10`: `update` no dice qué cambió, y `PLAN.md` documenta `reporter.py`, de ahí el scope.

## `BREAKING CHANGE` (hipotético)

```
feat(reporter)!: rename revenue to revenue_usd in JSON and CSV

BREAKING CHANGE: the revenue key (JSON) and column (CSV) are now
revenue_usd; scripts that read revenue must use the new name.
```
