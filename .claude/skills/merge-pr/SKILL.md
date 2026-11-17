---
name: merge-pr
description: Fusiona un pull request con squash en GitHub usando gh y deja main local al día. Úsala solo cuando el usuario pida fusionar o actualizar main, por ejemplo "fusiona el PR", "mergea el PR 15", "haz squash" o "actualiza main". Ninguna otra skill la invoca: subir la rama y abrir el PR es tarea de pull-request.
---

# Fusionar un PR con squash

En este proyecto todo entra a `main` por un PR fusionado con squash. Fusionar cambia la rama compartida y deshacerlo exige un commit de revert, así que comprueba todo antes. `gh` ya tiene la sesión iniciada; si no está en el PATH, usa `~/.local/bin/gh`.

## 1. Identifica el PR

Usa el número que indique el usuario o, si no indica ninguno, el de la rama actual (`gh pr view --json number`). Si no hay PR, dilo y detente.

## 2. Comprueba antes de fusionar

```sh
git status --short --branch
gh pr view <N> --json state,mergeable,headRefName,title,statusCheckRollup
```

- **Cambios sin commit** en archivos del PR: quedarían fuera de la fusión. Pregunta si se incluyen (commit con `commit-message-writer`) o se fusiona sin ellos.
- **`state`** debe ser `OPEN`.
- **`mergeable`** debe ser `MERGEABLE`. Con `CONFLICTING`, detente y avisa.
- **CI** ("Lint and test"): si está pendiente, espera con `gh pr checks <N> --watch --interval 10`; si falla, muestra qué paso falló y no fusiones.

## 3. Fusiona con squash

Escribe tú la primera línea y el cuerpo. Si no, con varios commits GitHub arma una lista de `* ` con todos los mensajes.

```sh
gh pr merge <N> --squash --delete-branch --subject "<título del PR> (#N)" --body-file - <<'EOF'
<cuerpo>

<línea de atribución>
EOF
```

- **Primera línea:** el título del PR seguido de ` (#N)`. Debe seguir las reglas de `commit-message-writer` (tipo, scope, inglés) y no pasar de 72 caracteres en total.
- **Cuerpo:** qué cambia y por qué, en inglés, con líneas de 72 columnas como máximo. Con varios commits, resúmelos en un solo texto, no los copies uno tras otro.
- **Atribución:** si Claude escribió los commits, termina con la línea `Co-authored-by` que indique el sistema para los commits. No escribas a mano el nombre del modelo.

## 4. Deja `main` al día

Si la rama del PR estaba activa, `gh pr merge --delete-branch` ya cambia a `main`, hace pull y borra la rama local. Completa y verifica:

```sh
git switch main && git pull --ff-only && git fetch --prune
git status -sb && git log --oneline -3 && git branch -a
```

`main` debe quedar igual a `origin/main`, sin cambios pendientes y sin la rama fusionada; si la rama local sigue, bórrala con `git branch -D <rama>` (con squash, `-d` no la reconoce como fusionada).

Si el usuario solo pidió **actualizar main** (por ejemplo, tras fusionar desde la web), haz solo este paso.
