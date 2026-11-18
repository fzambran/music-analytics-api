---
name: commit-message-writer
description: Escribe mensajes de commit en formato Conventional Commits, en inglés y con los tipos y scopes de este proyecto, a partir de los cambios preparados en Git y, si el usuario lo pide, hace el commit. Úsala cuando el usuario quiera escribir un mensaje de commit con el formato adecuado. Se activa con "hace commit", "commitear", "confirma mis cambios", "escribe un mensaje de commit", resumir el staged diff, o cuando el usuario pregunte "¿qué pongo en el commit?". Para subir la rama y abrir el PR, usa la skill `pull-request`; para fusionarlo, `merge-pr`.
---

# Mensajes de commit (Conventional Commits)

Redacta el mensaje a partir de los cambios **preparados** (staged). No hagas preguntas antes de redactarlo: si tienes que suponer el tipo, el scope o la intención, hazlo y anota la suposición debajo del mensaje.

## 1. Reúne el contexto

```sh
git status --short --branch
git diff --staged --stat
git diff --staged -- . ':(exclude)uv.lock'
```

- **Nada preparado:** dilo y sugiere `git add` con los archivos concretos que muestra `git status`. Si el usuario pidió hacer el commit, prepara tú solo los archivos del cambio, uno por uno; nunca `git add -A` ni `git add .`.
- **Cambios sin preparar o sin seguimiento (`??`)** que parecen parte del mismo cambio (el test o la doc del código preparado): avisa que no entrarán en el commit.
- **`uv.lock`** queda fuera del diff porque es ruido (agregar `pydantic` sumó 156 líneas); el cambio real se ve en `pyproject.toml`.
- **`chinook.db`** aparece como binario: menciona que cambia la base, sin inventar qué cambió.
- **Rama `main`:** aquí no se hace commit directo a `main` (todo entra por PR). Avisa y sugiere `git switch -c <tipo>/<slug>`, con el mismo tipo del commit (p. ej. `feat/artist-contains-accents`).

## 2. Tipo

| Tipo | Cuándo |
|---|---|
| `feat` | Comportamiento nuevo visible: endpoint, parámetro, opción del CLI de `reporter.py`, campo nuevo en la salida JSON/CSV. |
| `fix` | Corrige un comportamiento incorrecto: respuesta, código de estado, código de salida, cálculo, mensaje de error. |
| `refactor` | Cambia la estructura sin cambiar el comportamiento observable (la "regla de oro" de la skill `refactor`). |
| `perf` | Más rápido o con menos memoria, sin cambiar el comportamiento. |
| `test` | Solo pruebas: `tests/` (`test_*.py`, `conftest.py`). |
| `docs` | Solo documentación: `README.md`, `CLAUDE.md`, `docs/` (`PLAN.md`), docstrings, comentarios. |
| `style` | Solo formato (`ruff format`), sin cambios de lógica. |
| `ci` | `.github/workflows/`. |
| `chore` | Dependencias (`pyproject.toml`, `uv.lock`), `.gitignore`, `.python-version` y `.claude/` (skills, agentes, settings). |

El tipo lo decide el cambio principal: las pruebas y la documentación que acompañan a un `feat` o un `fix` no lo convierten en `test` ni en `docs`.

## 3. Scope

El código está en `src/music_analytics_api/` y las pruebas en `tests/`; el scope sale del área, no del directorio:

| Scope | Código | Pruebas |
|---|---|---|
| `api` | `app.py`, `config.py`, `routes.py`, `models.py`, `analytics.py` | `test_routes.py` |
| `db` | `db_routes.py` (Blueprint `/db`) | `test_db_routes.py`, `test_db_routes_unit.py` |
| `reporter` | `reporter.py` | `test_reporter.py`, `test_reporter_unit.py` |
| `deps` | `chore(deps)`: dependencias en `pyproject.toml` y `uv.lock` | |
| `claude` | `chore(claude)`: `.claude/` | |

- `test` y `docs` usan el scope del módulo probado o documentado: `test(reporter): ...`, `docs(db): ...`. `PLAN.md` documenta `reporter.py`.
- Si el cambio toca dos áreas, usa la principal; si toca tres o más, o no pertenece a ninguna (CI, `.gitignore`), omite el scope.
- Un solo scope: nada de `feat(db,reporter)`.

## 4. Mensaje

```
<tipo>(<scope>): <descripción>

<body opcional>

<footers opcionales>
```

**Primera línea**

- En inglés, como el código y todo el historial. Verbo en imperativo y en minúscula tras los dos puntos (`add`, `fix`, `reject`, `rename`), sin punto final.
- **66 caracteres como máximo**, contando `tipo(scope): `: al fusionar el PR con squash, GitHub agrega ` (#NN)` y la línea debe quedar bajo 72. Mídela con un comando, no a ojo:
  ```sh
  python3 -c 'import sys; print(len(sys.argv[1]))' "fix(reporter): reject --top values above 2**63-1"
  ```
- Nombra lo concreto: el endpoint (`/db/artists/<id>/albums`), la opción (`--artist-contains`), la función (`get_db_connection`). Prohibido `update`, `change`, `modify`, `improve`, `various`, `misc`: di qué cambió.
- No agregues `(#N)`; lo pone GitHub.

**Body** (omítelo si la primera línea basta)

- Qué cambia y por qué, no cómo. Una viñeta (`- `) por cambio lógico, o un párrafo si es uno solo. Líneas de 72 columnas como máximo.
- Describe el efecto observable con ejemplos: método, ruta y código de estado (`404 {"error": "Artist not found"}`); opción del CLI, mensaje de error en español y código de salida; claves o columnas de la salida. Por ejemplo: `"acdc" now matches "AC/DC"`.
- En un `refactor`, termina con `No behavior change.`
- No enumeres archivos ni líneas: eso ya lo muestra el diff.

**Footers**

- `BREAKING CHANGE: <qué se rompe y cómo migrar>`, más `!` antes de los dos puntos (`feat(reporter)!: ...`), si el commit rompe a quien usa el proyecto: quita o renombra un endpoint, una clave del JSON o un código de estado; quita o renombra una opción del CLI, o una clave o columna de la salida de `reporter.py`; cambia la firma de una función pública de `reporter.py` (se importa como módulo) o un código de salida.
- `Closes #N` solo si el usuario menciona el issue; nunca inventes números.
- Si el commit lo hace Claude, `Co-Authored-By:` va al final, en el mismo párrafo que los demás footers.

## 5. ¿Uno o varios commits?

El código, sus pruebas y la documentación que lo describe (`README.md`, `CLAUDE.md`, `PLAN.md`) son **un solo cambio**, aunque sumen 5 o 6 archivos: no sugieras dividirlos. Sugiere dividir solo cuando hay cambios independientes entre sí (un fix en `reporter.py` y un ajuste del CI, o varios fixes sin relación) y da un mensaje para cada parte:

> Quizás convenga dividir esto en commits independientes: [lista]. Para sacar archivos del commit actual: `git restore --staged <archivo>`.

## 6. Entrega

Muestra el mensaje en un bloque de código listo para copiar y, debajo, solo las suposiciones que hiciste.

Si el usuario pidió **hacer el commit**:

1. En `main`, crea primero la rama (paso 1).
2. Ejecuta `uv run ruff check . && uv run ruff format --check .`: el CI lo exige y el hook del proyecto no lo revisa. Si falla, avisa y no hagas el commit.
3. Pasa el mensaje por un heredoc, no con un archivo creado con Write (el hook `PostToolUse` de `.claude/settings.json` correría toda la suite de pytest) ni con varios `-m`:
   ```sh
   git commit -F - <<'EOF'
   fix(reporter): reject --top values above 2**63-1

   ...
   EOF
   ```
4. No hagas `--amend` ni `--no-verify` salvo que te lo pidan.
5. Después del commit, continúa sin preguntar con la skill `pull-request` para subir la rama y abrir el PR.

Si el usuario solo pidió el mensaje, no hagas el commit.

Ejemplos tomados del historial del proyecto: [references/examples.md](references/examples.md).
