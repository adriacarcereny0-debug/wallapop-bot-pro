# Integración por navegador, cola de publicación e imágenes FLUX.2 Pro

## Alcance y autorización

La integración por navegador existe para el **uso personal autorizado del
titular de LOT Bot**: Wallapop España le ha autorizado a publicar sus
anuncios con este bot, desde el navegador, sin API key ni OAuth y con un
mínimo de 60 segundos entre anuncios. No es una integración oficial de
Wallapop ni una autorización transferible, y la aplicación lo dice en las
pantallas de Cuentas y Configuración.

Lo que **no** hace, por diseño:

* No usa ninguna API de Wallapop ni endpoints internos: repite en la web
  pública (es.wallapop.com) los pasos que haría el usuario.
* No pide, ve ni guarda contraseñas: el usuario inicia sesión él mismo.
* No intenta resolver CAPTCHA ni verificaciones, ni ocultar que el navegador
  está automatizado. Si Wallapop pide algo, la cola se pausa y el usuario lo
  completa a mano (Cuentas → «Abrir navegador»).
* No baja nunca de 60 segundos entre publicaciones.

## Arquitectura

```
Chat «Publica 10 canapés» ─► publish_master_ad (plan + confirmación)
                                   │
                                   ▼
                     PublishQueue (publishing/queue.py)
            por anuncio: imagen única ─► espera ≥ intervalo ─► publicar
                  │                                   │
                  ▼                                   ▼
   ImageGenerationService               MasterAdService.publish_single
   (images/generation/)                          │
   ├─ FluxImageService  (real)                    ▼
   └─ DemoImageGenerator (DEMO)          WallapopService
                                          ├─ MockWallapopService (DEMO)
                                          └─ BrowserWallapopService
                                               │  pasos de wallapop_browser.yaml
                                               ▼
                                     Playwright ─► Chrome/Edge (perfil por cuenta)
```

| Pieza | Fichero |
|---|---|
| Servicio de Wallapop por navegador | `lot_bot/wallapop/browser/service.py` |
| Conexión de cuentas (inicio de sesión del usuario) | `lot_bot/wallapop/browser/auth.py` |
| Perfiles aislados por cuenta | `lot_bot/wallapop/browser/profiles.py` |
| Control del navegador (Playwright) | `lot_bot/wallapop/browser/driver.py` |
| **Selectores y pasos de la web (único sitio)** | `lot_bot/resources/wallapop_browser.yaml` |
| Cola de publicación | `lot_bot/publishing/queue.py` |
| Cliente FLUX.2 Pro | `lot_bot/images/generation/flux.py` |
| Prompts | `lot_bot/images/generation/prompts.py` |
| Registro y detección de repetidas | `lot_bot/images/generation/registry.py` |
| Clave de API cifrada | `lot_bot/config/api_keys.py` |

## Selectores de la web de Wallapop

Todos los selectores, direcciones y pasos del formulario están en
`lot_bot/resources/wallapop_browser.yaml`. El código no contiene ninguno.

**Se escribieron a partir de los textos visibles de la web y no se han
podido comprobar con una sesión real** (`verificado: false`). La primera vez:

1. Conecta una cuenta y lanza una cola de **1** anuncio.
2. Mira la ventana del navegador: si un paso falla, la cola se pausa, el
   error dice qué paso y se guarda una captura en `<datos>/logs/navegador/`.
3. Copia el YAML a `<datos>/config/wallapop_browser.local.yaml` (la ruta
   exacta aparece en Configuración → Wallapop), corrige el paso y pon
   `verificado: true`. No hay que recompilar.

Cada objetivo admite varias alternativas (CSS, `text=`, `role=...`); se usa
la primera visible. Acciones: `ir`, `pulsar`, `escribir`, `elegir`,
`subir_archivos`. Valores: `{titulo}`, `{descripcion}`, `{precio}`,
`{categoria}`, `{subcategoria}`, `{estado}`.

El controlador real se ha probado contra una página local que imita el
formulario (rellenar, elegir categoría, subir la foto a un `input` oculto,
detectar la confirmación y extraer la URL del anuncio).

## Sesiones

* Un perfil de Chromium por cuenta en `<datos>/browser_profiles/<cuenta>/`
  (en Windows, `%LOCALAPPDATA%\LOT Bot\browser_profiles`). Cookies, caché e
  historial nunca se comparten. Las cookies las cifra el propio navegador
  (DPAPI en Windows).
* Se rechaza cualquier carpeta de perfiles dentro de un repositorio Git.
* «Desconectar» y «Eliminar cuenta» borran el perfil de esa cuenta.
* `.gitignore` bloquea además `browser_profiles/`, `Cookies`, `Login Data`,
  `storage_state*.json`, `*.har`, `*.local.yaml`.

Navegador: se prueba en orden Chrome, Edge (siempre presente en Windows) y
el Chromium de Playwright. `LOT_BOT_BROWSER_EXECUTABLE` fuerza una ruta.

## Cola de publicación

* `minimum_publish_interval_seconds` = 60 por defecto; valores inferiores se
  rechazan (también si alguien los escribe a mano en la base de datos).
* El intervalo cuenta entre **cualquier** par de publicaciones, también de
  cuentas distintas y también tras un intento fallido. Es un mínimo: si
  generar la imagen tarda más, no se espera extra.
* Por anuncio se registra: inicio, publicación, cuenta, anuncio, resultado,
  error, intentos, imagen, id/URL de Wallapop. Todo pasa también por el
  Historial.
* Fallos: verificación, sesión caducada, límite de peticiones, sin clave o
  sin créditos → **pausa** sin reintentar. Otros errores → un reintento
  automático esperando el doble del intervalo. Dos fallos seguidos → pausa.
* Iniciar, pausar, reanudar, cancelar y reintentar desde la pantalla
  «Publicación automática» o el chat («¿cómo va la cola?», «pausa la cola»,
  «reintenta los fallidos»).
* Si LOT Bot se cierra con una cola en marcha, al abrirlo queda en pausa.
* Las pruebas usan `FakeClock`; con un servicio que no sea el DEMO, la cola
  se niega a usarlo.

## Imágenes (FLUX.2 Pro)

Flujo documentado por Black Forest Labs: `POST https://api.bfl.ai/v1/flux-2-pro`
con cabecera `x-key` → `polling_url` → consultar hasta `"Ready"` →
descargar `result.sample` (caduca a los 10 minutos). Saldo:
`GET /v1/credits`. Cualquier estado distinto de `Pending`/`Ready` es un
fallo y se muestra tal cual.

* El prompt se construye con los datos del anuncio (tipo, color, material,
  medida si la hay, colchón si la descripción lo menciona); lo que no se sabe
  clasificar se pasa literal. Solo varían encuadre, luz y escena. Siempre:
  fotorrealista, sin personas, sin texto, logos, marcas ni precios.
* Cada imagen se registra (SHA-256, dHash de 64 bits, prompt, semilla,
  fecha, anuncio, cuenta). Si sale igual o casi igual a otra, se descarta y
  se genera otra variación (hasta 3 intentos).
* La imagen generada es la portada del anuncio; las del anuncio principal van
  detrás.
* La clave se introduce en Configuración → IA / Imágenes, se guarda cifrada
  con la clave maestra del sistema y se tacha en los registros.
* En DEMO se generan imágenes de prueba locales: ni red ni créditos.
