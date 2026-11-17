---
name: pull-request
description: Sube la rama actual a GitHub, abre el pull request con gh y espera el CI. Úsala cuando el usuario diga "sube la rama", "haz push", "abre el PR", "¿pasó el CI?" o necesite el título de un PR. También la usa commit-message-writer después de hacer un commit. No escribe mensajes de commit (commit-message-writer) ni fusiona PR (merge-pr).
---

# Pull requests con gh

En este proyecto todo entra a `main` por un PR fusionado con squash. `gh` ya tiene la sesión iniciada; si no está en el PATH, usa `~/.local/bin/gh`.

## 1. Subir la rama

```sh
git status --short --branch
git push -u origin <rama>
```

- Nunca subas `main`. Si estás en `main` con commits locales, detente y avisa: esos commits debían ir en una rama.
- Nunca uses `--force`. Si el usuario pide reescribir la rama (p. ej. tras un `--amend`), usa `--force-with-lease=<rama>:<sha remoto anterior>`, para no borrar commits que no viste.
- Si el push falla (rechazo, sin red, sin permisos), avisa y deja el commit local.
- Si hay cambios sin commit, avisa: no se suben.

## 2. Abrir el PR

Si la rama ya tiene PR (`gh pr view --json url` funciona), muestra su URL y no abras otro. Si no:

```sh
gh pr create --base main --head <rama> --title "<título>" --body-file - <<'EOF'
<cuerpo>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

- **Título:** al fusionar con squash, GitHub lo usa como primera línea del commit en `main`, así que sigue las reglas de la skill `commit-message-writer` (tipo, scope, inglés, 66 caracteres como máximo). Con un solo commit, es su primera línea. Con varios, resume el cambio común sin `various` ni `misc`.
- **Cuerpo:** en inglés, en Markdown. Qué cambia y por qué, con una viñeta por cambio lógico; con un solo commit, su body basta.
- El cuerpo no lleva `Co-Authored-By` (eso va en los commits) y no lleva `(#N)` (lo pone GitHub).

## 3. Esperar el CI

```sh
gh pr checks <N> --watch --interval 10
```

El CI ("Lint and test") ejecuta `uv sync --locked`, `ruff check`, `ruff format --check` y `pytest`. Si falla, muestra qué paso falló.

## 4. Entrega

Muestra la URL del PR y el resultado del CI, y termina ahí. Fusionar es otra tarea: solo se hace cuando el usuario lo pide, con la skill `merge-pr`.
