"""Tests del system prompt de personalidad (HU-2.2).

Aquí no se llama a ningún modelo: se vigila el **archivo** y su carga. Que el
prompt viaje en cada petición al proveedor se prueba en ``test_llm.py``
(sección "Prefijo estable"), contra el cuerpo HTTP real.

Lo que se defiende en este módulo es la propiedad que **no falla ruidosamente**
si se rompe: que el prompt sea una CONSTANTE. Un prompt interpolado con la
fecha —o cualquier otro dato que cambie entre llamadas— seguiría dando
respuestas correctas, solo que invalidando el caché automático del proveedor en
cada petición y multiplicando el costo de la entrada. Sin estos tests, el
síntoma sería una factura, no un fallo.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services.llm import DEFAULT_SYSTEM_PROMPT
from app.services.llm.prompt import (
    PERSONALITY_PROMPT_PATH,
    PROMPTS_DIR,
    load_system_prompt,
)

# El caché de DeepSeek trabaja en bloques de 64 tokens: lo que no llegue a un
# bloque NO se cachea nunca. En español un token ronda los 3–4 caracteres, así
# que 64 tokens son ~250; el mínimo se pone en 400 para dejar margen y porque
# una personalidad que quepa en menos difícilmente dice algo. Este test es el
# que evita que un recorte "de limpieza" mate el caché en silencio.
MINIMO_DE_CARACTERES = 400

# Marcadores de plantilla: si aparecen, alguien piensa rellenarlos en runtime.
MARCADORES_DE_PLANTILLA = ("{", "}", "%s", "%d", "%(", "${")


def test_el_prompt_esta_versionado_en_el_repo() -> None:
    """Iterar la personalidad debe ser editar un archivo, no tocar código."""
    assert PERSONALITY_PROMPT_PATH.is_file()
    assert PERSONALITY_PROMPT_PATH.parent == PROMPTS_DIR
    assert (PROMPTS_DIR / "README.md").is_file(), "las reglas de edición viven junto al prompt"


def test_lo_que_se_manda_al_modelo_es_exactamente_el_archivo() -> None:
    """Sin nada añadido por código: el archivo ES el prompt."""
    contenido = PERSONALITY_PROMPT_PATH.read_text(encoding="utf-8")

    assert DEFAULT_SYSTEM_PROMPT == contenido.replace("\r\n", "\n").strip()


def test_cargarlo_dos_veces_da_lo_mismo() -> None:
    """Función pura del contenido: ni azar, ni reloj, ni entorno."""
    assert load_system_prompt() == load_system_prompt() == DEFAULT_SYSTEM_PROMPT


def test_no_lleva_marcadores_de_plantilla() -> None:
    """Un ``{destino}`` aquí es un prefijo distinto por llamada = cero caché."""
    encontrados = [m for m in MARCADORES_DE_PLANTILLA if m in DEFAULT_SYSTEM_PROMPT]

    assert not encontrados, (
        f"el system prompt lleva marcadores de plantilla {encontrados}: "
        "lo dinámico va DETRÁS del prefijo estable, como un mensaje más"
    )


def test_no_lleva_la_fecha_de_hoy() -> None:
    """Canario contra el error clásico: interpolar la fecha en el prefijo.

    Un ``f"Hoy es {hoy}"`` es la forma más común de romper el caché, y además
    envejece mal si se escribe a mano. Si este test se pone rojo, la pregunta
    no es "cómo lo silencio" sino "por qué hay una fecha en el prefijo".
    """
    hoy = datetime.now(UTC)

    assert str(hoy.year) not in DEFAULT_SYSTEM_PROMPT
    assert hoy.strftime("%Y-%m-%d") not in DEFAULT_SYSTEM_PROMPT


def test_es_lo_bastante_largo_para_que_el_cache_muerda() -> None:
    assert len(DEFAULT_SYSTEM_PROMPT) >= MINIMO_DE_CARACTERES, (
        "un prefijo por debajo de un bloque de 64 tokens no se cachea NUNCA: "
        "el ahorro de la HU-2.2 desaparecería sin que nada más se pusiera rojo"
    )


def test_los_finales_de_linea_no_cambian_el_prompt(tmp_path: Path) -> None:
    """El prefijo depende del commit, no de con qué editor se guardó."""
    unix = tmp_path / "unix.md"
    unix.write_text("Eres Rover.\nViajas.\n", encoding="utf-8", newline="")
    windows = tmp_path / "windows.md"
    windows.write_text("Eres Rover.\r\nViajas.\r\n", encoding="utf-8", newline="")

    assert load_system_prompt(unix) == load_system_prompt(windows) == "Eres Rover.\nViajas."


def test_un_archivo_que_falta_tumba_el_arranque(tmp_path: Path) -> None:
    """Fail-fast, como una variable obligatoria ausente (HU-0.8).

    Un Rover sin personalidad responde igual de bien a un ``curl``: el fallo
    sería invisible hasta que alguien leyera una conversación sosa en
    producción.
    """
    with pytest.raises(RuntimeError, match="No se pudo leer el system prompt"):
        load_system_prompt(tmp_path / "no-existe.md")


def test_un_archivo_vacio_tumba_el_arranque(tmp_path: Path) -> None:
    vacio = tmp_path / "vacio.md"
    vacio.write_text("   \n\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="está vacío"):
        load_system_prompt(vacio)
