# Cómo conectar Wallapop

Para que LOT Bot trabaje con tus cuentas reales hace falta configurar una sola vez la
conexión con Wallapop. Normalmente esto lo dejamos hecho nosotros en la instalación.

## Antes de empezar

Necesitas los datos de acceso que Wallapop te ha facilitado al autorizar la
automatización de tus cuentas.

> **Importante:** LOT Bot **nunca te pide la contraseña de Wallapop** y no la guarda.
> Tú introduces tus datos en la página de Wallapop, como siempre, y Wallapop le da
> permiso al programa.

## Paso 1: abrir la configuración

Abre LOT Bot y entra en **Configuración → Wallapop**.

Ahí verás en qué estado está la conexión:

* **MODO DEMO** — estás con datos de prueba
* **Wallapop Connect** — estás conectado de verdad

Si estás en modo demostración, la propia pantalla te dice qué falta.

## Paso 2: el fichero de configuración

En la carpeta del programa hay un fichero llamado `.env.example`.

1. Haz una copia y llámala `.env` (sin nada delante del punto)
2. Ábrela con el Bloc de notas
3. Rellena los datos que te dio Wallapop
4. Cambia `LOT_BOT_DEMO_MODE=true` por `LOT_BOT_DEMO_MODE=false`
5. Guarda y cierra

> Si esto te resulta incómodo, dínoslo: lo dejamos configurado por ti.

## Paso 3: comprobar

Cierra LOT Bot y vuelve a abrirlo. En **Configuración → Wallapop** debe aparecer
**«Integración real activa»** y una lista de lo que se puede hacer:

* ✓ Lo que está disponible
* ✗ Lo que Wallapop no ha autorizado

Si algo aparece con ✗, el programa te lo dirá cuando lo intentes, en lugar de fingir
que lo ha hecho.

## Paso 4: conectar tus cuentas

Sigue la guía **«Cómo añadir una cuenta»**.

## Preguntas frecuentes

**¿Puedo seguir usando el modo demostración?**
Sí. Cambia `LOT_BOT_DEMO_MODE` a `true` y reinicia. Es útil para hacer pruebas.

**¿Es seguro?**
Tus permisos se guardan cifrados en tu ordenador. Tu contraseña de Wallapop nunca pasa
por el programa. En los registros técnicos no se guarda ninguna clave.

**¿Qué pasa si caduca el permiso?**
La cuenta aparecerá como «Sesión caducada» en la pantalla de Cuentas. Solo tienes que
seleccionarla y pulsar **Conectar** otra vez.
