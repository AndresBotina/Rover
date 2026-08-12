"""System prompt por defecto. **Placeholder mínimo hasta la HU-2.2.**

La personalidad de Rover se escribe en la HU-2.2, en un archivo versionado del
repo (ni en base de datos ni incrustado en el endpoint), y aterriza AQUÍ:
cambiarla será editar este módulo —o el archivo que cargue— sin tocar ni el
proveedor ni el agente.

Lo que esta HU deja resuelto es la ESTRUCTURA que ese prompt necesita: se
manda como prefijo estable, primero e invariable entre llamadas, para que el
caché automático de DeepSeek muerda (ver ``base.py``). Por eso el texto de
abajo, aunque sea provisional, ya cumple la única regla que importa para el
caché: **es una constante**, no se interpola con la fecha, el nombre del
usuario ni nada que cambie entre peticiones. Un ``f"Hoy es {hoy}"`` aquí
invalidaría el prefijo en cada llamada y multiplicaría el costo de la entrada
sin que ningún test se pusiera rojo.
"""

DEFAULT_SYSTEM_PROMPT = "Eres Rover, un asistente de viajes. Responde en el idioma del usuario."
