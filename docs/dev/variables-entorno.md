# Variables de entorno

Se leen del fichero `.env` de la raíz del proyecto (o del que esté junto al `.exe`).
`.env` está en `.gitignore`: **nunca se sube al repositorio**.

Copia `.env.example` a `.env` y rellena lo que necesites.

## Funcionamiento

| Variable | Valores | Por defecto | Para qué |
|---|---|---|---|
| `LOT_BOT_DEMO_MODE` | `true` / `false` | `true` | `true` usa datos simulados; `false` intenta la integración real |
| `LOT_BOT_ENV` | `development` / `production` | `development` | Entorno de ejecución |
| `LOT_BOT_LOG_LEVEL` | `DEBUG`…`ERROR` | `INFO` | Detalle del registro |
| `LOT_BOT_LANGUAGE` | `es` / `en` | `es` | Idioma de la interfaz |
| `LOT_BOT_DATA_DIR` | ruta | (según el sistema) | Carpeta de datos alternativa |

## Wallapop

| Variable | Obligatoria | Para qué |
|---|---|---|
| `WALLAPOP_CLIENT_ID` | sí (modo real) | Identificador de cliente de la integración autorizada |
| `WALLAPOP_CLIENT_SECRET` | sí (modo real) | Secreto de cliente. **Nunca se muestra ni se registra** |
| `WALLAPOP_REDIRECT_URI` | sí (modo real) | URI de retorno del flujo OAuth (p. ej. `http://127.0.0.1:8723/callback`) |
| `WALLAPOP_ENDPOINT_MAP` | sí (modo real) | Ruta al YAML con los endpoints oficiales |
| `WALLAPOP_SCOPES` | no | Permisos solicitados, separados por espacios |

> **Importante:** aunque pongas `LOT_BOT_DEMO_MODE=false`, si falta cualquiera de las
> tres credenciales o el fichero de endpoints, LOT Bot **se queda en modo DEMO** y
> explica por qué. Nunca finge una conexión real.

## IA

| Variable | Valores | Por defecto | Para qué |
|---|---|---|---|
| `LOT_BOT_AI_PROVIDER` | `rules` / `anthropic` | `rules` | `rules` funciona sin conexión externa |
| `ANTHROPIC_API_KEY` | clave | (vacío) | Necesaria para `anthropic` |
| `LOT_BOT_AI_MODEL` | id de modelo | `claude-sonnet-5` | Modelo a usar |
| `LOT_BOT_AI_MAX_TOKENS` | entero | `4096` | Longitud máxima de respuesta |

## Seguridad

| Variable | Para qué |
|---|---|
| `LOT_BOT_MASTER_KEY` | Clave de cifrado de los tokens. Si se deja vacía, LOT Bot genera una y la guarda en el llavero del sistema (recomendado) |

Si defines `LOT_BOT_MASTER_KEY` a mano y luego la cambias, los tokens guardados dejan
de poder descifrarse y hay que volver a conectar las cuentas. La aplicación lo detecta
y lo dice con un mensaje claro.

## Negocio

| Variable | Para qué |
|---|---|
| `LOT_BOT_BUSINESS_WHATSAPP` | WhatsApp del negocio (valor inicial; luego se edita en Ajustes) |
| `LOT_BOT_BUSINESS_NAME` | Nombre del negocio |

El resto de datos comerciales (precios de oferta, condiciones de envío, montaje, pago)
se configuran desde **Configuración → Negocio** y se guardan en la base de datos local,
no en variables de entorno.

## Comprobar la configuración cargada

Dentro de la aplicación: **Configuración → Wallapop**. Muestra qué hay configurado
(enmascarado) y qué operaciones están autorizadas.
