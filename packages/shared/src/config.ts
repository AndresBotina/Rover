/**
 * Configuración compartida de Rover.
 *
 * ÚNICA fuente de verdad para el nombre de MARCA visible al usuario.
 * A propósito está desacoplado de los nombres técnicos: los paquetes usan el
 * scope "@rover/*" y NO deben depender de este valor. Cambiar la marca debe
 * implicar tocar SOLO este archivo, nunca imports ni nombres de paquetes.
 */
export const APP_NAME = "Rover";
