"""Carga del system prompt de personalidad (HU-2.2).

El **texto** no vive aquí: vive en ``prompts/rover.md``, versionado en el repo.
Este módulo solo lo lee. La separación es deliberada — iterar la personalidad
es lo que más va a pasar en la vida de este producto, y debe ser *editar un
archivo de texto y mirar el diff*, sin abrir un módulo de Python, sin tocar
lógica y sin una migración de por medio. Lo que NO es: ni un campo en base de
datos (invisible en git, imposible de revisar en un PR, distinto por ambiente)
ni un string incrustado en el endpoint.


## Por qué se carga UNA vez, al importar

``DEFAULT_SYSTEM_PROMPT`` es una constante de módulo, no una función que lea el
archivo en cada llamada. Dos razones:

1. **Es la definición de "prefijo estable".** Leer en cada petición abre la
   puerta a que el prompt cambie a mitad de la vida del proceso; con una
   constante, todas las llamadas de un despliegue mandan exactamente los mismos
   bytes, que es de lo que vive el caché automático de DeepSeek.
2. **No se toca el disco en el camino de la petición.** ``read_text`` es una
   syscall bloqueante; hacerla dentro de un endpoint async por cada mensaje
   sería pagar E/S por algo que no cambia.

En desarrollo con ``--reload`` el cambio entra al guardar; en producción, con
el deploy. Que "editar el archivo" no sea instantáneo en caliente es el precio
—barato— de la estabilidad del prefijo.


## Por qué un fallo de carga TUMBA el arranque

Si el archivo falta o está vacío, esto levanta y la app **no arranca**. Es el
mismo criterio de fail-fast de los settings obligatorios (HU-0.8): un Rover sin
personalidad responde igual de bien a un ``curl`` que a un usuario, así que el
fallo sería invisible hasta que alguien leyera una conversación sosa en
producción. A propósito **no** se usa ``LLMNotConfigured`` (de ``errors.py``):
esa la capturan los llamadores para devolver un 503 por petición, y esto no es
un problema de una petición — es un despliegue mal construido.


## La regla del prefijo estable (la de verdad importante)

El contenido del archivo **no puede tener nada dinámico**: ni la fecha, ni el
nombre del usuario, ni datos de la conversación, ni marcadores de plantilla que
alguien rellene después. Un ``f"Hoy es {hoy}"`` aquí invalidaría el prefijo en
**cada** llamada y multiplicaría el costo de la entrada **sin que ningún test
se pusiera rojo** — la app seguiría respondiendo igual, solo que pagando de
más. Lo variable va DETRÁS, como un mensaje más del contexto.

La regla completa, con dónde va cada cosa, está en ``prompts/README.md``; la
señal de que se respeta es ``llm_cache_hit_ratio`` en la línea ``app.llm``
(``instrumentation.py``), y hay tests que la vigilan en ``tests/test_prompt.py``.
"""

from pathlib import Path

#: Directorio de los prompts versionados (ver su ``README.md``).
PROMPTS_DIR = Path(__file__).parent / "prompts"

#: Archivo con la personalidad de Rover. Cambiar de personalidad = editarlo.
PERSONALITY_PROMPT_PATH = PROMPTS_DIR / "rover.md"


def load_system_prompt(path: Path = PERSONALITY_PROMPT_PATH) -> str:
    """Lee un prompt del repo y lo devuelve listo para mandar al modelo.

    Normaliza dos cosas y ninguna más, para que el resultado dependa **solo**
    del contenido del archivo y no de con qué editor o en qué sistema se
    guardó: los finales de línea (CRLF → LF) y el espacio en blanco de los
    extremos. Sin eso, el mismo commit podría producir prefijos distintos —y
    por tanto cachés distintos— según el checkout.

    El parámetro ``path`` existe para los tests y para un futuro segundo prompt
    (la HU-2.6 puede querer uno propio para el loop de tools); el resto del
    backend usa ``DEFAULT_SYSTEM_PROMPT``.
    """
    try:
        texto = path.read_text(encoding="utf-8")
    except OSError as exc:  # falta, sin permisos, ilegible…
        raise RuntimeError(
            f"No se pudo leer el system prompt de {path}. "
            "Es un archivo versionado del repo: si falta, el despliegue está mal construido."
        ) from exc

    prompt = texto.replace("\r\n", "\n").strip()
    if not prompt:
        raise RuntimeError(
            f"El system prompt de {path} está vacío. "
            "Rover sin personalidad respondería igual pero sin ser Rover."
        )
    return prompt


#: System prompt que usa la capa de LLM cuando el llamador no pasa uno propio.
#: Constante del proceso: los mismos bytes en todas las llamadas (ver arriba).
DEFAULT_SYSTEM_PROMPT = load_system_prompt()
