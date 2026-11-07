---
name: refactor
description: Refactoriza el código existente para mejorar su legibilidad, estructura y mantenibilidad sin alterar su comportamiento. Verifica primero que las pruebas unitarias pasen (usa la skill unit-tests antes de tocar el código), aplica cambios pequeños e incrementales, por ejemplo: eliminar duplicación, extraer funciones, renombrar, simplificar condicionales, quitar código muerto; y vuelve a ejecutar las pruebas tras cada cambio hasta confirmar que pasan las pruebas. Úsala cuando el usuario pida refactorizar, limpiar, ordenar, simplificar o mejorar el código, reducir deuda técnica o resolver code smells (código que no huele bien). No la uses para agregar funcionalidades ni corregir bugs.
---

# Refactorización segura

Refactorizar es cambiar la estructura del código **sin cambiar lo que hace**. Las pruebas unitarias son la red de seguridad: sin pruebas en verde no se refactoriza, y cada paso termina con las pruebas en verde otra vez.

## Regla de oro

El comportamiento observable no cambia: mismas respuestas (código de estado y JSON) de cada endpoint, mismos valores de retorno, mismas excepciones y mismos efectos secundarios. Si un cambio altera algo de esto, no es una refactorización: detente y consúltalo con el usuario.

## Flujo de trabajo

### 1. Línea base: ejecuta las pruebas antes de tocar nada

```sh
uv run pytest -q
```

- **Todas pasan:** anota el número de tests; es la línea base. Continúa.
- **Alguna falla (o hay errores de importación):** no refactorices. Informa al usuario qué falla. Corregir un bug está fuera del alcance de esta skill.
- **Tests `xfail` existentes:** forman parte de la línea base; deben seguir como `xfail` al terminar.

### 2. Asegura la red de seguridad (skill `unit-tests`)

Lee el código que vas a refactorizar e identifica qué comportamiento está cubierto por los tests existentes. Si la zona que vas a tocar **no tiene pruebas suficientes** (ramas, casos de borde, errores 400/404, filtros con límites exactos), usa la skill `unit-tests` para escribir **tests de caracterización** antes de modificar el código:

- Deben fijar el comportamiento **actual**, aunque parezca raro. Si encuentras algo que parece un bug, no lo arregles: déjalo documentado (o en `xfail`) e infórmalo al usuario.
- Ejecútalos y confirma que pasan sobre el código **sin modificar**. Esa es la nueva línea base.

### 3. Planifica cambios pequeños

Lista los code smells que encontraste y ordénalos de menor a mayor riesgo. Cada paso debe ser una sola transformación que se pueda revertir fácilmente. Ejemplos:

| Code smell | Refactorización |
| --- | --- |
| Código duplicado | Extraer función o constante compartida |
| Función larga o con varias responsabilidades | Extraer funciones con nombres descriptivos |
| Nombres poco claros (`x`, `data2`, `tmp`) | Renombrar (actualiza todos los usos) |
| Condicionales anidados | Cláusulas de guarda / retorno temprano |
| Números o cadenas mágicas | Constantes con nombre a nivel de módulo |
| Bucles que acumulan en listas | Comprensiones o funciones integradas (`sum`, `max`, `any`) |
| Código muerto, imports sin uso | Eliminar (verifica antes con `grep` que no se usa) |
| Falta de type hints o docstrings | Añadirlos según las convenciones del proyecto |

### 4. Aplica un cambio a la vez y verifica

Para **cada** paso del plan:

1. Aplica un único cambio.
2. Ejecuta las pruebas: `uv run pytest -q`.
3. **Si pasan** (mismo número de tests que la línea base, o más): continúa con el siguiente paso.
4. **Si fallan:** el cambio alteró el comportamiento. Revierte ese paso (o corrígelo) y vuelve a ejecutar hasta volver a verde. **Nunca modifiques un test para que pase** después de una refactorización; el test define el comportamiento que debes preservar. La única excepción es un renombrado de una función interna que el test importa directamente: ahí se actualiza solo el nombre, no las aserciones.

No acumules varios cambios sin ejecutar las pruebas: si algo falla, debe ser obvio qué paso lo causó.

### 5. Verificación final

Ejecuta desde la raíz del repo:

```sh
uv run pytest -q                                   # suite completa en verde
uv run ruff check --fix <archivos> && uv run ruff format <archivos>
uv run pytest -q                                   # de nuevo tras ruff (puede reordenar imports)
```

La tarea solo está terminada cuando la suite completa pasa y ruff no reporta errores en los archivos tocados.

## Qué no hacer

- No añadir funcionalidades, endpoints, parámetros ni validaciones nuevas.
- No corregir bugs en silencio (eso cambia el comportamiento); infórmalos.
- No cambiar la API pública: rutas, nombres de campos JSON, códigos de estado, mensajes de error, firmas de funciones usadas por otros módulos.
- No cambiar dependencias ni la configuración del proyecto.
- En este repo: no romper el orden de importación entre `app.py` y `routes.py` (`app.py` importa `routes` **después** de crear `app`; ver `CLAUDE.md`). No muevas `import routes  # noqa: F401` al bloque de imports superior ni quites su `noqa`.
- No mutar el `music_store` global de forma que cambie los datos iniciales.

## Problemas del entorno

Si `uv run pytest` falla con `Failed to spawn: pytest` aunque pytest esté instalado (p. ej. porque el proyecto se movió de carpeta y los scripts de `.venv` apuntan a la ruta antigua), usa `uv run python -m pytest -q`, que es equivalente. Si aparece la advertencia `VIRTUAL_ENV ... does not match`, otro entorno virtual está activo; ejecuta `unset VIRTUAL_ENV` o ignórala.

## Al terminar

Informa brevemente:

- Resultado de las pruebas antes y después (p. ej. `9 passed` → `12 passed`), y los tests de caracterización que añadiste con `unit-tests`.
- Lista de refactorizaciones aplicadas, con `archivo:línea`.
- **Beneficios** de la refactorización: qué mejora concreta aporta cada cambio (menos duplicación, funciones más cortas, responsabilidades separadas, nombres más claros…). Cada beneficio debe corresponder a un cambio que de verdad aplicaste; no prometas mejoras de rendimiento o de diseño que no hayas hecho.
- Bugs o comportamientos dudosos que encontraste y **no** corregiste.
- Mejoras que descartaste por riesgo o porque cambiarían el comportamiento.

Ejemplo de la parte de beneficios (refactorización de `routes.py`):

```markdown
**Beneficios**
- Menos código duplicado: la respuesta 404 de artista (`_artist_not_found`) y la conversión de listas a JSON (`_jsonify_all`) se escriben una sola vez. Si cambian, se modifican en un solo sitio.
- Funciones de ruta (route handlers) más cortas y claras: cada una solo busca los datos y devuelve la respuesta. Por ejemplo, el cuerpo de `get_album_stats` pasó de 12 a 3 líneas.
- Preparación de datos centralizada: `_album_stats_input` define en un solo lugar qué diccionario recibe `calculate_album_stats` y cómo se calcula la popularidad.
- La API se comporta igual: misma suite de 51 tests en verde antes y después.
```
