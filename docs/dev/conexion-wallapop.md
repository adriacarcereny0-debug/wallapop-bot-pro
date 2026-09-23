# Conectar LOT Bot con Wallapop

Esta es la parte que depende de la autorización que Wallapop haya concedido al
cliente. Léela entera antes de tocar nada.

## Principio: no se inventa nada

LOT Bot **no contiene ninguna URL, endpoint ni parámetro de Wallapop**. Todo se
declara en un fichero YAML que se rellena copiando la documentación oficial que
Wallapop entrega junto a las credenciales.

Si una operación no está en ese fichero, no existe para la aplicación: se responde
`NOT_AVAILABLE_WITH_CURRENT_WALLAPOP_ACCESS` en vez de simularla.

## Pasos

### 1. Reunir lo que da Wallapop

De la autorización deberías tener:

* `client_id` y `client_secret`
* URI(s) de redirección registradas
* URL de autorización y URL de token (flujo OAuth 2.0)
* URL base de la API
* Documentación de los endpoints concedidos y de los permisos (*scopes*)

### 2. Crear el fichero de endpoints

```bash
cp config/endpoint_map.example.yaml config/endpoint_map.local.yaml
```

`*.local.yaml` está en `.gitignore`: no se sube al repositorio.

Rellena:

```yaml
api:
  base_url: "<la URL base de la documentación oficial>"
  auth_header: "Authorization"
  auth_scheme: "Bearer"

oauth:
  authorize_url: "<URL de autorización oficial>"
  token_url: "<URL de token oficial>"
  use_pkce: true
  scopes: ["<los scopes concedidos>"]

operations:
  list_items:
    method: GET
    path: "<ruta oficial>"
    query:
      limit: "{limit}"
      offset: "{offset}"
    response:
      collection_path: "<ruta al array en la respuesta>"
      fields:
        item_id: "<campo del id>"
        title: "<campo del título>"
        price: "<campo del precio>"
        status: "<campo del estado>"
```

**Declara solo lo que te hayan concedido.** Deja el resto comentado o vacío.

### 3. Completar el .env

```dotenv
LOT_BOT_DEMO_MODE=false
WALLAPOP_CLIENT_ID=...
WALLAPOP_CLIENT_SECRET=...
WALLAPOP_REDIRECT_URI=http://127.0.0.1:8723/callback
WALLAPOP_ENDPOINT_MAP=C:\ruta\a\config\endpoint_map.local.yaml
WALLAPOP_SCOPES=scope1 scope2
```

### 4. Comprobar

Arranca LOT Bot y ve a **Configuración → Wallapop**. Debe decir
«Integración real activa (N operaciones autorizadas)» y listar con ✓ y ✗ qué se puede
hacer. Si sigue en DEMO, ahí mismo se explica qué falta.

### 5. Conectar una cuenta

**Cuentas Wallapop → Añadir cuenta → Conectar**. Se abre el navegador en el dominio de
Wallapop, el usuario introduce allí sus credenciales y autoriza. LOT Bot recibe un
código, lo canjea por tokens y los guarda cifrados.

LOT Bot **nunca ve ni guarda la contraseña de Wallapop**.

## Operaciones que LOT Bot sabe usar

| Nombre en el YAML | Para qué | Sin ella |
|---|---|---|
| `account_profile` | Datos de la cuenta | No se muestra el usuario de Wallapop |
| `list_items` | Listar anuncios | No hay sincronización: el resto de pantallas quedan vacías |
| `get_item` | Detalle de un anuncio | Se usa lo sincronizado |
| `search_items` | Búsqueda en servidor | Se filtra en local sobre lo sincronizado |
| `create_item` | Publicar | No se puede publicar desde LOT Bot |
| `update_item` | Modificar título/descripción | No se pueden editar anuncios |
| `update_item_price` | Cambiar precio | Se intenta con `update_item`; si tampoco está, no se puede |
| `update_item_images` | Cambiar fotografías | No se pueden actualizar fotos |
| `delete_item` | Eliminar anuncio | No se puede eliminar |
| `upload_image` | Subir fotografía | Se publica sin subir imágenes previamente |
| `list_categories` | Categorías oficiales | La categoría la escribe el usuario a mano |
| `list_conversations` | Bandeja de entrada | La pantalla de Mensajes queda desactivada |
| `get_conversation` | Leer una conversación | Solo se ve el resumen |
| `send_message` | Responder a compradores | Se pueden preparar borradores, no enviarlos |
| `market_data` | Datos de mercado | El análisis usa solo tus propios anuncios |

## Sustituciones disponibles

En `path`, `query` y `body` puedes usar marcadores que LOT Bot rellena:

`{item_id}`, `{conversation_id}`, `{limit}`, `{offset}`, `{price}`, `{title}`,
`{description}`, `{currency}`, `{category}`, `{condition}`, `{images}`, `{text}`,
`{body}`, `{query}`, `{min_price}`, `{max_price}`, `{status}`.

Si una operación de escritura no define `body`, LOT Bot envía un cuerpo JSON estándar
con los campos del anuncio.

## Mapeo de respuestas

`response.collection_path` es la ruta al array dentro de la respuesta
(`"data"`, `"data.items"`, `"results.0.list"`…). Se deja vacío si la respuesta ya es
un array o un objeto único.

`response.fields` traduce la respuesta al modelo de LOT Bot:

```yaml
response:
  collection_path: "data"
  fields:
    item_id: "id"
    title: "attributes.title"
    price: "attributes.price.amount"
```

## Qué hacer si algo falla

| Síntoma | Causa habitual |
|---|---|
| Sigue en MODO DEMO | Falta una credencial o el fichero de endpoints. El motivo aparece en Configuración → Wallapop |
| `NOT_AVAILABLE_WITH_CURRENT_WALLAPOP_ACCESS` | Esa operación no está declarada en el YAML |
| 401 al sincronizar | Token caducado: vuelve a conectar la cuenta |
| 403 | La cuenta no tiene el permiso (*scope*) necesario |
| Los anuncios llegan sin título o sin precio | El `response.fields` no apunta a los campos correctos |
| 429 | Límite de peticiones: baja la frecuencia de las automatizaciones |

Todos los errores quedan en **Logs y errores** con el detalle técnico (sin tokens).

## Cambio de API por parte de Wallapop

Si Wallapop cambia rutas o formatos, se edita `endpoint_map.local.yaml`. No hace falta
recompilar el `.exe` ni tocar el código.
