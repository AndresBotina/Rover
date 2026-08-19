# Prompts versionados

Aquí vive el **texto** que define cómo habla Rover. Está en el repo, en archivos
sueltos, a propósito: iterar la personalidad debe ser **editar un archivo** y
mirar el diff en git, no una migración de base de datos ni un string perdido en
medio de la lógica de un endpoint.

| Archivo    | Qué es                                                            |
| ---------- | ----------------------------------------------------------------- |
| `rover.md` | System prompt de personalidad (HU-2.2). Lo carga `../prompt.py`.  |

## La regla que no se puede romper: esto es una CONSTANTE

El system prompt viaja **primero y siempre igual** en cada llamada al modelo
(ver `../base.py`). Ese prefijo idéntico es lo que hace que el **caché
automático de DeepSeek** acierte: los tokens de entrada que ya vio se cobran
mucho más barato. Un prefijo que cambia entre llamadas no acierta **nunca**.

Por eso, dentro de estos archivos **no puede entrar nada dinámico**:

- ❌ la fecha u hora de hoy,
- ❌ el nombre, el plan o las preferencias del usuario,
- ❌ el destino del viaje, el clima, ni ningún dato de la conversación,
- ❌ marcadores de plantilla (`{fecha}`, `%s`, `$destino`) que alguien rellene
  después.

**Dónde va lo dinámico:** DETRÁS del prefijo estable, como un mensaje más del
contexto (`Message(role=Role.SYSTEM | Role.USER, …)` al armar la petición). El
orden completo es `system prompt → tools (HU-2.6) → historial → mensaje nuevo`:
todo lo variable vive a la derecha, donde no arrastra al caché.

Esto importa porque romperlo **no pone nada rojo**: la app sigue respondiendo
igual, solo que pagando de más en cada petición. La señal de que está bien es
`llm_cache_hit_ratio` en la línea de log `app.llm` (ver
`../instrumentation.py`); si se queda en cero llamada tras llamada con el mismo
prefijo, hay algo invalidándolo.

## Cómo editarlo

1. Edita `rover.md` y ya: no hay que tocar código.
2. El archivo se lee **una vez, al importar** `../prompt.py`. En desarrollo con
   `--reload` basta con guardar; en producción, el cambio entra con el deploy.
3. Manténlo largo de verdad. El caché de DeepSeek trabaja en bloques de 64
   tokens: **un prompt más corto que eso no se cachea nunca**. Hay un test que
   vigila el mínimo (`tests/test_prompt.py`).
4. **El registro se cambia aquí, en dos sitios a la vez.** Hoy el prompt usa
   tuteo neutro (_tú_) y lo dice explícitamente ("tuteas"). Si se prefiere
   voseo (_vos_) o usted, hay que cambiar **la instrucción y la voz del propio
   texto**: el modelo imita el registro en que está escrito el prompt, así que
   pedirle "tutea" en un texto escrito de vos le manda señales contrarias.
