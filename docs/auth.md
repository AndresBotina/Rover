# Sesión y renovación de tokens (HU-1.5)

Cómo vive, se renueva y muere una sesión en Rover. Este documento es la
referencia para las **Épicas 3 (web)** y **4 (móvil)**: está escrito para que no
haya que volver a investigar el flujo cuando toque implementarlas.

Lo que hay que retener antes de nada:

> **El backend de Rover no renueva sesiones.** Valida el access token que le
> llega y responde `401` cuando ya no vale. Quien renueva es el **SDK de
> Supabase en el cliente**, hablando directamente con Supabase.

## Quién hace qué

| Pieza | Responsabilidad |
| --- | --- |
| **Supabase Auth (GoTrue)** | Emite el access token y el refresh token, los **rota**, los revoca y publica el JWKS con el que se verifican. |
| **SDK de Supabase (cliente)** | Guarda la sesión, la **renueva sola** antes de que expire, y avisa a la app cuando cambia o se pierde. |
| **Backend de Rover** | **Solo valida** el access token en cada petición (firma, expiración, issuer, audiencia) y resuelve el perfil local. No firma, no renueva, no revoca. |
| **App web / móvil** | Manda el access token vigente en `Authorization: Bearer …` y reacciona al `401` y a los eventos del SDK. |

## Ciclo de vida de una sesión

```
  ┌── login / registro ────────────────────────────────────────────┐
  │  el cliente obtiene { access_token, refresh_token }            │
  └────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌── uso normal ──────────────────────────────────────────────────┐
  │  cliente ──► Rover:  Authorization: Bearer <access_token>      │
  │              Rover valida el JWT en LOCAL (JWKS cacheado)      │
  │              → 200 con el recurso                              │
  └────────────────────────────────────────────────────────────────┘
                              │
             el access token está a punto de expirar (~1 h)
                              │
                              ▼
  ┌── renovación (SIN pasar por Rover) ────────────────────────────┐
  │  SDK ──► Supabase:  POST /auth/v1/token?grant_type=refresh_token│
  │          Supabase devuelve un access token NUEVO               │
  │          y (por rotación) normalmente un refresh token NUEVO   │
  │  El SDK guarda ambos. El usuario no se entera de nada.         │
  └────────────────────────────────────────────────────────────────┘
                              │
                 el refresh falla (expirado / revocado)
                              │
                              ▼
  ┌── fin de sesión ───────────────────────────────────────────────┐
  │  El SDK emite SIGNED_OUT. La app manda al usuario al login.    │
  └────────────────────────────────────────────────────────────────┘
```

Rover aparece en un solo punto de este dibujo: validando. Nunca en la flecha de
renovación.

## El rol del backend: validar y nada más

El middleware de auth (HU-1.6, `app/api/deps.py` → `get_current_user`) verifica
el access token **localmente** contra el JWKS de Supabase: firma ES256,
**expiración**, issuer y audiencia. Consecuencias que importan al cliente:

- **Un access token expirado es un `401` normal**, con el mismo cuerpo uniforme
  que cualquier otro fallo de autenticación:

  ```json
  { "error": { "code": "unauthenticated", "message": "No autenticado.",
               "details": null, "error_id": null } }
  ```

  El `401` **no dice** que el motivo fuera la expiración —el cuerpo es idéntico
  para token ausente, malformado, con firma inválida o caducado, a propósito, y
  el motivo real solo va al log del servidor—. Así que **el cliente no debe
  intentar deducir del `401` si "solo hace falta refrescar"**: esa decisión la
  toma el SDK, que sí sabe cuándo expira el token porque lo tiene guardado.
- Rover **no ve nunca el refresh token** después del login. No lo almacena, no
  lo valida, no lo revoca. La única vez que pasa por el backend es en la
  respuesta de `/v1/auth/register` y `/v1/auth/login`, que lo devuelven tal como
  lo entregó Supabase.
- Un `503` en una ruta protegida **no** significa que el token esté mal: es que
  Rover no pudo obtener el JWKS o hablar con su base. Reintentar con el mismo
  token es lo correcto; renovar la sesión no arregla nada.

## La renovación, en el cliente

El SDK de Supabase (`supabase-js` en web, el mismo paquete en Expo/React Native)
trae `autoRefreshToken: true` **por defecto**: arranca un temporizador y renueva
el access token **antes** de que expire, de forma transparente. La app no llama
a ningún "refresh"; solo se asegura de leer el token vigente del SDK cada vez
que llama a Rover.

El access token dura **~1 hora** por defecto (configurable en el proyecto de
Supabase). El refresh token dura mucho más y es el que sostiene la sesión entre
aperturas de la app.

Para enterarse de los cambios, la app escucha `onAuthStateChange`:

- `TOKEN_REFRESHED` — hay un access token nuevo (y probablemente un refresh
  token nuevo). Si la app guarda el token en algún estado propio, **este es el
  evento que lo invalida**: guardar el access token en una variable al hacer
  login y no volver a mirarlo es el bug clásico de esta integración.
- `SIGNED_OUT` — la sesión se acabó (refresh fallido, revocada, logout). A la
  pantalla de login.

### Rotación: el refresh token **no** es fijo

Cada renovación puede emitir un **refresh token nuevo e invalidar el anterior**.
Es Supabase quien lo gestiona; el cliente no elige.

De ahí salen dos reglas para las Épicas 3 y 4:

1. **Nunca copiar el refresh token a un sitio propio** (una variable, un estado
   global, un segundo almacenamiento). La copia caduca en la siguiente
   renovación y deja al usuario con una sesión rota que el SDK ya no puede
   reparar. La fuente de verdad es el almacenamiento del SDK.
2. **No implementar reintentos propios de la llamada de refresh.** Reenviar un
   refresh token ya consumido es exactamente lo que Supabase detecta como reuso.
   Existe una **ventana corta de reutilización** —pensada justo para
   renovaciones concurrentes y reintentos de red— pero fuera de ella el reuso
   invalida la sesión. El SDK ya coordina esto (deduplica renovaciones
   simultáneas); duplicarlo desde fuera es la forma más rápida de desloguear
   usuarios sin querer.

### Cuando el refresh falla

Si el refresh token expiró, fue revocado (logout en otro dispositivo, cambio de
contraseña, revocación desde el panel) o se detectó reuso, **no hay recuperación
posible desde el cliente**: hay que volver a autenticarse.

El flujo correcto es:

1. El SDK intenta renovar y falla.
2. El SDK emite `SIGNED_OUT` y limpia la sesión que tenía guardada.
3. La app manda al usuario al login.

Rover **no participa**. Desde su lado lo único que se ve es que las peticiones
siguientes llegan sin token o con uno caducado, y responde `401` como siempre.
No hay nada que "avisar" desde el backend: la app se entera antes por el SDK.

## Almacenamiento de los tokens

Decisiones a tomar en cada épica; aquí quedan apuntadas, **no implementadas**.

**Web (Épica 3, Next.js).** El SDK persiste la sesión por su cuenta
(`persistSession: true` por defecto). El punto a decidir es **dónde**: por
defecto usa el almacenamiento del navegador, lo que basta para una SPA pero deja
al servidor sin ver la sesión. Para App Router con Server Components y
middleware, lo que corresponde es el paquete **`@supabase/ssr`**, que guarda la
sesión en **cookies** para que servidor y cliente compartan el mismo estado; ahí
es donde se decide `httpOnly`, `secure` y `sameSite`. Es una decisión de la
Épica 3, pero conviene tomarla **antes** de escribir la primera pantalla:
cambiarla después toca el layout, el middleware y cada punto de lectura.

**Móvil (Épica 4, Expo).** El SDK no trae almacenamiento en React Native: hay
que **inyectárselo** al crear el cliente. Tres cosas que hay que resolver ahí, y
que conviene verificar contra la documentación vigente al implementarlas:

- **Almacenamiento seguro.** Un refresh token de larga vida en almacenamiento
  plano es la credencial más valiosa de la app. Lo indicado es el almacén seguro
  del sistema (Keychain / Keystore, vía `expo-secure-store`), con una salvedad
  conocida: ese almacén tiene **límite de tamaño por valor** y una sesión de
  Supabase serializada puede acercarse a él, así que hay que comprobarlo (y, si
  hace falta, partir el valor) en vez de descubrirlo en producción.
- **`detectSessionInUrl: false`.** Esa opción existe para el flujo de redirección
  del navegador; en móvil no aplica.
- **Auto-refresh y ciclo de vida de la app.** Los temporizadores no corren con la
  app en segundo plano, así que el auto-refresh debe **pararse y arrancarse**
  siguiendo el `AppState` (el SDK expone `startAutoRefresh`/`stopAutoRefresh`
  para esto). Sin ello, volver a la app tras un rato largo puede encontrarse el
  token caducado y una renovación que no se disparó.

En ninguno de los dos casos el access token debe guardarse a mano en estado de
la aplicación: se pide al SDK en el momento de usarlo (ver la regla de
`TOKEN_REFRESHED` más arriba).

## Decisión: **NO** hay un `POST /v1/auth/refresh` propio

Evaluado y **descartado**. Rover no expone un endpoint de refresh; los clientes
renuevan directamente contra Supabase a través del SDK.

**Por qué no:**

1. **Sería una reimplementación peor de algo ya resuelto.** El valor del refresh
   no está en la llamada HTTP —esa es trivial— sino en lo que la rodea: renovar
   *antes* de expirar, deduplicar renovaciones concurrentes, manejar la rotación
   y la ventana de reutilización, y reaccionar al ciclo de vida de la app. El SDK
   hace todo eso; un endpoint nuestro solo movería la llamada de sitio y
   dejaría esa lógica igualmente en el cliente.
2. **Un salto de red de más en el camino crítico de seguir logueado.** Pasaría de
   `cliente → Supabase` a `cliente → Rover → Supabase`, y convertiría a Rover en
   un punto único de fallo para *mantener la sesión*: hoy, si Rover está caído,
   el usuario no puede usar la app pero **sigue autenticado**; con el endpoint,
   una caída de Rover expulsaría a todo el mundo en cuanto caducara su access
   token.
3. **Ampliaría el radio de exposición de la credencial más sensible.** Hoy el
   refresh token toca el backend una sola vez (la respuesta de login/registro).
   Con un endpoint propio pasaría por nuestros logs de acceso, nuestro proxy y
   nuestro manejo de errores en **cada renovación**, durante toda la vida de la
   sesión. Menos sitios que lo ven es menos sitios donde puede filtrarse.
4. **La rotación lo hace activamente peligroso de proxiar.** Un proxy ingenuo que
   reintente ante un timeout puede reenviar un refresh token ya consumido y
   provocar la invalidación de una sesión perfectamente válida. Hacerlo bien
   significa reimplementar la coordinación que el SDK ya tiene.
5. **Contradice la decisión de arquitectura de la épica.** Delegamos la identidad
   precisamente para no ser dueños del ciclo de vida de las credenciales.

**Casos que se consideraron a favor, y por qué no bastan:**

- *"Un cliente sin SDK"* (una CLI, una integración de terceros, server-to-server).
  Hoy no existe, y cuando exista la respuesta correcta casi seguro no es un
  refresh token de usuario sino una credencial de servicio con su propio
  alcance. Construirlo ahora es especular.
- *"Controlar/revocar sesiones desde el backend"*. Legítimo, pero **no es
  refresh**: es cierre de sesión y revocación, y sería otro endpoint
  (`POST /v1/auth/logout` delegando en GoTrue). Queda como posible HU futura, no
  como razón para este.
- *"Que el cliente no conozca la URL ni la anon key de Supabase"*. No compra
  nada: la anon key está diseñada para vivir en clientes públicos y la URL es
  visible en cualquier petición. Ver más abajo la única versión de este
  argumento que sí sería coherente.

**Qué cambiaría esta decisión:** que se quisiera que los clientes **no hablaran
nunca** con Supabase —por ejemplo para poder cambiar de proveedor de identidad
sin tocar web y móvil—. Pero eso no es "añadir un endpoint de refresh": obliga a
proxiar **todo** el ciclo de sesión (login, refresh, logout, recuperación de
contraseña, login social) y a renunciar al SDK en los clientes, reimplementando
su gestión de sesión a mano. Es una decisión de arquitectura completa, de todo o
nada, y hoy no se toma. Si algún día se toma, este documento es el sitio donde
debe quedar registrada.

## El punto ambiguo que las Épicas 3 y 4 se van a encontrar

Rover **ya** expone `/v1/auth/register` y `/v1/auth/login`, que hablan con
Supabase por dentro. Entonces, ¿el cliente hace login contra Rover o contra el
SDK? Importa, porque **el SDK solo renueva las sesiones que él conoce**: una
sesión obtenida por `/v1/auth/login` y guardada a mano en la app **no se
renovará sola**.

Los dos patrones válidos:

1. **SDK primero** — `supabase.auth.signInWithPassword(...)`. El SDK posee la
   sesión desde el minuto uno y el auto-refresh funciona sin más. A cambio, los
   errores llegan con la forma de Supabase, no con el catálogo de `code` propio
   de Rover ([formato de errores](../apps/backend/README.md#formato-de-errores)).
2. **Rover primero, y se la pasas al SDK** — llamar a `/v1/auth/login` y
   entregarle la sesión al SDK con
   `supabase.auth.setSession({ access_token, refresh_token })`, que a partir de
   ahí la posee y la renueva.

**Recomendado: el patrón 2.** Conserva lo que el proyecto construyó a propósito
—mensajes y `code` de dominio, sin filtrar los códigos crudos del proveedor, y
el mismo contrato de error para toda la API— y no renuncia a nada del
auto-refresh, porque el SDK acaba siendo el dueño de la sesión igual. El paso
extra es una línea (`setSession`) y hay que darlo **inmediatamente** después del
login: entre recibir la sesión y entregársela al SDK no debe haber nada.

El registro tiene además su propio motivo para ir por Rover: `/v1/auth/register`
distingue `active` de `pending_email_confirmation` con un `status` explícito, que
es lo que decide si la app muestra "revisa tu correo".

## Qué tiene que hacer cada épica

**Épica 3 — Web (Next.js)**

- [ ] Decidir el almacenamiento de sesión **antes** de la primera pantalla:
      `@supabase/ssr` con cookies si hay Server Components o middleware.
- [ ] Inicializar el cliente de Supabase con `autoRefreshToken` y
      `persistSession` activos (son el defecto; el trabajo es no desactivarlos).
- [ ] Login/registro contra Rover y `setSession(...)` acto seguido (patrón 2).
- [ ] Suscribirse a `onAuthStateChange`: en `TOKEN_REFRESHED`, usar el token
      nuevo; en `SIGNED_OUT`, mandar al login.
- [ ] Pedir el access token al SDK **en cada llamada** a Rover, y mandarlo en
      `Authorization: Bearer …`.
- [ ] Tratar el `401` de Rover como "la sesión no sirve": no intentar deducir si
      basta con refrescar (el `401` es uniforme por diseño).

**Épica 4 — Móvil (Expo)**

- [ ] Todo lo anterior, más:
- [ ] Inyectar almacenamiento **seguro** al crear el cliente, verificando el
      límite de tamaño por valor del almacén del sistema.
- [ ] `detectSessionInUrl: false`.
- [ ] Enganchar `startAutoRefresh` / `stopAutoRefresh` al `AppState`, para que
      volver a la app tras horas en segundo plano renueve en vez de expulsar.
- [ ] Sesión persistente entre aperturas de la app (es consecuencia de los tres
      puntos anteriores, no trabajo aparte).

## Referencias en el código

- Validación del token: `apps/backend/app/core/security.py` y
  `apps/backend/app/api/deps.py`.
- Integración con el proveedor: `apps/backend/app/services/auth.py` (único
  módulo que habla con Supabase).
- Contrato de la sesión que devuelven login y registro: `SessionOut` en
  `apps/backend/app/api/v1/auth.py`, y `AuthSession` en `@rover/shared`.
- Contexto de la decisión de delegar la identidad: `docs/backlog.md`, nota de
  arquitectura al inicio de la Épica 1.
