# Arquitectura de LOT Bot

## Visión general

```
Usuario
   ↓
Interfaz de escritorio (PySide6/Qt)          lot_bot/ui
   ↓
Agente IA / orquestador                      lot_bot/ai
   ↓
Herramientas (tools) registradas             lot_bot/ai/tools
   ↓
Servicios de dominio                         lot_bot/catalog, publishing, messages, market…
   ↓
Capa de integración con Wallapop             lot_bot/wallapop
   ↓
MockWallapopService  |  ConnectWallapopService
```

Reglas que sostienen el diseño:

1. **Un único punto de contacto con Wallapop.** Solo `lot_bot/wallapop` hace peticiones.
   Ningún otro módulo importa `httpx` para hablar con Wallapop.
2. **La IA no toca nada directamente.** No ve credenciales, no hace peticiones, no
   ejecuta SQL. Solo puede invocar herramientas registradas.
3. **Nada se publica sin confirmación.** Las herramientas de escritura devuelven un
   plan; la ejecución real requiere un segundo paso confirmado por el usuario.
4. **No se inventan endpoints.** Las rutas de Wallapop se declaran en un fichero YAML
   que se rellena con la documentación oficial.

## Mapa de módulos

| Carpeta | Responsabilidad |
|---|---|
| `lot_bot/config` | Ajustes (.env), rutas por sistema operativo, almacén cifrado de secretos |
| `lot_bot/logs` | Logging con filtro que elimina secretos antes de escribir |
| `lot_bot/database` | Modelo SQLite (SQLAlchemy 2.0) y gestión de sesiones |
| `lot_bot/wallapop` | Contrato `WallapopService`, mock, integración real, OAuth, cuentas |
| `lot_bot/catalog` | Productos, inventario, control de calidad, duplicados |
| `lot_bot/templates_engine` | Plantillas de anuncio con variables |
| `lot_bot/images` | Importación, validación y deduplicación de fotografías |
| `lot_bot/publishing` | Vista previa, publicación y espejo local de anuncios |
| `lot_bot/messages` | Bandeja de entrada y asistente de ventas |
| `lot_bot/market` | Análisis de precios con fuentes autorizadas |
| `lot_bot/automation` | Tareas programadas (APScheduler) |
| `lot_bot/ai` | Proveedores de IA, herramientas y orquestador |
| `lot_bot/core` | Auditoría, eventos y utilidades transversales |
| `lot_bot/ui` | Ventana principal, tema y pantallas |
| `lot_bot/bootstrap.py` | Ensamblado de todos los servicios (`Application`) |

## La capa de Wallapop en detalle

### El contrato

`lot_bot/wallapop/service.py` define `WallapopService`: unas veinte operaciones
(listar anuncios, crear, cambiar precio, mensajes, categorías…). Cada implementación
declara en `capabilities()` qué sabe hacer de verdad.

```python
service.require(Capability.DELETE_ITEM)   # lanza NotAvailableWithCurrentAPIError
```

### Por qué no hay URLs en el código

LOT Bot **no incluye ninguna URL de Wallapop**. `ConnectWallapopService` es un motor
HTTP genérico gobernado por `config/endpoint_map.local.yaml`:

```yaml
api:
  base_url: "…"                 # de la documentación oficial
operations:
  update_item_price:
    method: PATCH
    path: "/…/{item_id}"
    body:
      price: "{price}"
    response:
      fields:
        item_id: "id"
```

Consecuencias prácticas:

* Una operación que no figure en el fichero **no existe** para la aplicación: se
  responde `NOT_AVAILABLE_WITH_CURRENT_API`, nunca se simula.
* Si Wallapop cambia su API, se edita el YAML. No hay que recompilar.
* El repositorio se puede publicar sin exponer detalles de la integración.

### Selección del backend

`lot_bot/wallapop/factory.py` decide:

| Situación | Backend |
|---|---|
| `LOT_BOT_DEMO_MODE=true` | `MockWallapopService` |
| Faltan credenciales | `MockWallapopService` (avisando del motivo) |
| Falta el fichero de endpoints | `MockWallapopService` (avisando del motivo) |
| Todo configurado | `ConnectWallapopService` |

Nunca se "simula" una conexión real: si falta algo, la aplicación lo dice en el panel
y en la barra de estado.

## Aislamiento multicuenta

* Cada cuenta tiene un `internal_ref` único (`acc-xxxxxxxx`).
* Toda entidad que pertenece a una cuenta lleva `account_id` **obligatorio**:
  `Listing`, `Conversation`, `ProductAssignment`.
* Las consultas filtran siempre por cuenta. `ListingFilter` y `ProductFilter` aceptan
  `account_ref`; sin él, se devuelven datos de todas las cuentas **etiquetados** con su
  cuenta de origen, nunca mezclados.
* Los tokens se guardan cifrados por cuenta y se descifran solo en el momento de la
  petición, dentro de `AccountManager.get_access_token()`.
* `UniqueConstraint("account_id", "wallapop_item_id")`: el mismo identificador de
  anuncio en dos cuentas distintas son dos filas distintas.

## El agente IA

### Ciclo de una orden

```
"Cambia el precio de los canapés de 135x190 a 269 €"
   ↓  Agent.ask()
Proveedor de IA  →  tool_call: update_price(precio=269, medida="135x190")
   ↓  ToolRegistry.execute(confirmed=False)
La herramienta BUSCA los anuncios afectados y devuelve un PLAN (no ejecuta)
   ↓
La interfaz muestra:  "Voy a modificar 6 anuncios · Cuenta 1: 1 · Cuenta 2: 2 …"
                      [Cancelar] [Confirmar]
   ↓  Agent.confirm(token)
ToolRegistry.execute(confirmed=True)  →  PublishingService.update_prices()
   ↓
WallapopService.update_item_price()  por cada anuncio
   ↓
Resultado + entrada en el historial
```

### Tres barreras de seguridad

1. **La herramienta**: comprueba `context.confirmed` y devuelve un plan si es `False`.
2. **El registro** (`ToolRegistry.execute`): si una herramienta marcada
   `requires_confirmation` devolviera éxito sin confirmación, se bloquea el resultado.
3. **El servicio de dominio**: `PublishingService.publish(confirmed=False)` lanza
   `ConfirmationRequiredError`. Aunque alguien llamara al servicio saltándose la IA.

### Proveedores

| Proveedor | Cuándo | Qué hace |
|---|---|---|
| `AnthropicProvider` | Hay `ANTHROPIC_API_KEY` y `LOT_BOT_AI_PROVIDER=anthropic` | Lenguaje natural libre con function calling |
| `RuleBasedProvider` | Por defecto | Interpreta órdenes concretas en español, sin conexión externa |

El proveedor local existe para que el cliente pueda usar el programa sin contratar ni
configurar ningún servicio de IA, y para que la aplicación siga siendo útil sin internet.

## Persistencia

SQLite en la carpeta de datos del usuario. Once tablas: `accounts`, `products`,
`product_images`, `product_assignments`, `templates`, `listings`, `conversations`,
`messages`, `automations`, `audit_log`, `settings`.

* `PRAGMA foreign_keys=ON` y `journal_mode=WAL`.
* Los `datetime` se guardan en UTC sin zona.
* El esquema se crea solo al arrancar (`create_all`). Para cambios con datos en
  producción, ver `docs/dev/actualizacion.md`.

## Concurrencia

* La interfaz nunca bloquea: `TaskRunner` (QThreadPool) ejecuta en segundo plano
  las llamadas a la IA, las sincronizaciones y las publicaciones.
* Las automatizaciones corren en `BackgroundScheduler` (APScheduler).
* Las sesiones de base de datos son de vida corta (`session_scope`), una por operación.

## Errores

`lot_bot/wallapop/errors.py` define la jerarquía. Cada error lleva:

* `user_message`: frase entendible que ve el cliente.
* `detail`: texto técnico que va al log (redactado).
* `retryable`: si reintentar es seguro.

La interfaz muestra el `user_message` y ofrece el detalle técnico plegado. Los errores
de Wallapop **nunca** se ocultan ni se convierten en un éxito falso.
