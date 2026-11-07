---
name: unit-tests
description: Genera y ejecuta pruebas unitarias con pytest para código Python (funciones puras, clases y endpoints Flask). Úsala cuando el usuario pida escribir, añadir, completar o mejorar tests, aumentar la cobertura, o "probar" una función, módulo o ruta, aunque no mencione pytest explícitamente.
---

# Pruebas unitarias con pytest

## Flujo de trabajo

1. **Lee el código antes de escribir nada.** Identifica entradas, salidas, efectos secundarios (estado global, archivos, red) y los errores que la función lanza o devuelve. Revisa si ya existen tests (`test_*.py`) para seguir su estilo y no duplicarlos.
2. **Casos normales primero:** uno o dos tests que muestren el uso típico con valores esperados calculados a mano, no copiados de la implementación.
3. **Casos de borde y errores:** colecciones vacías, `None`, ceros (divisiones), límites exactos de los filtros (`>` frente a `>=`), cadenas vacías o solo con espacios, tipos no válidos, IDs inexistentes. Para excepciones usa `pytest.raises(TipoError, match="...")`.
4. **Ejecuta los tests** y luego ruff sobre el archivo nuevo (comandos abajo).
5. **Si un test falla por un bug real del código, no cambies el código ni ajustes el test para que pase.** Déjalo fallando o márcalo con `@pytest.mark.xfail(reason="...")` e informa del bug al usuario.

## Convenciones

- Archivo `test_<modulo>.py` junto al módulo probado (o en `tests/` si el proyecto ya tiene esa carpeta).
- Nombres que describan el comportamiento: `test_<funcion>_<escenario>_<resultado>`, p. ej. `test_calculate_average_tracks_empty_list_returns_zero`.
- Un comportamiento por test; patrón Arrange-Act-Assert sin lógica condicional dentro del test.
- `@pytest.mark.parametrize` para variaciones de la misma regla en vez de copiar tests.
- Fixtures para la preparación compartida; `tmp_path` para archivos y `monkeypatch` para variables de entorno o dependencias externas. Los tests no deben usar red ni depender del orden de ejecución.
- Floats: compara con `pytest.approx`.
- Estado global mutable (p. ej. un store en memoria a nivel de módulo): no lo modifiques sin restaurarlo; prefiere crear una instancia nueva en una fixture.

## Endpoints Flask

Usa el cliente de pruebas y verifica código de estado y cuerpo JSON:

```python
import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_get_artist_unknown_id_returns_404(client):
    response = client.get("/artists/999")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Artist not found"}
```

Cubre al menos: respuesta correcta, recurso inexistente (404) y parámetros no válidos (400).

## Comandos

Ejecuta desde la raíz del repo (ruff ordena los imports distinto si se corre desde un subdirectorio). Si pytest no está instalado, añádelo con `uv add --dev pytest`.

```sh
uv run pytest path/to/test_file.py -q              # tests del archivo
uv run pytest path/to/test_file.py::test_name      # un solo test
uv run ruff check --fix path/to/test_file.py && uv run ruff format path/to/test_file.py
```

En carpetas sin `__init__.py` (p. ej. `music-analytics-api/`), pytest añade el directorio del test a `sys.path`, así que los imports locales (`from app import app`) funcionan también desde la raíz.

## Al terminar

Informa brevemente: archivo creado, número de tests y resultado de la ejecución (pasan / fallan), qué casos de borde cubriste y cualquier bug que los tests hayan revelado.

Cierra con un **resumen de las pruebas realizadas** que liste los patrones clave aplicados. Cada punto debe describir lo que de verdad hacen los tests escritos: no menciones mocks, fixtures o validaciones que no se hayan usado. Ejemplo (tests de `routes.py` en `test_routes.py`):

```markdown
### Resumen de las pruebas

- 37 tests en `test_routes.py`, todos pasan.

**Patrones clave**
- Usa el cliente de pruebas de Flask (`app.test_client()`) para hacer peticiones HTTP realistas a cada endpoint.
- Aísla los datos con la fixture `custom_store`: con `monkeypatch` reemplaza `routes.music_store` por un `MusicStore` nuevo y vacío, de modo que el store compartido no se modifica. Las funciones de `analytics.py` no se simulan; se prueban de forma integrada a través de las rutas `/stats/*`.
- Prueba tanto los casos exitosos (happy paths) como los casos límite: store vacío, artista sin álbumes, el límite `min_tracks` (5 temas se excluye, 6 se incluye), el tope de 5 resultados y queries de longitud máxima con espacios alrededor.
- Cubre los errores: 404 para IDs inexistentes o no enteros, 400 para `q` vacío o de más de 100 caracteres, y 405 para métodos no permitidos.
- Valida el código de estado y también el formato y la estructura del JSON: claves, valores calculados a mano (comparados con `pytest.approx`) y mensajes de error exactos.
- Todos los tests son independientes del orden de ejecución gracias a las fixtures `client` y `custom_store`.
```
