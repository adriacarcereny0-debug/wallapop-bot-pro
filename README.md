# LOT Bot

Aplicación de escritorio para gestionar y automatizar **varias cuentas de Wallapop**
desde un único programa, con un asistente de IA que interpreta órdenes en español.

> El uso de este software requiere la autorización de Wallapop para la automatización
> de las cuentas gestionadas. LOT Bot está diseñado para trabajar **exclusivamente**
> con los endpoints y permisos concedidos en esa autorización.

```
┌─────────────────────────────────────────────────────────────────┐
│  Usuario                                                        │
│     ↓                                                           │
│  Interfaz de escritorio (PySide6)                               │
│     ↓                                                           │
│  Agente IA  →  Herramientas registradas  →  Servicios           │
│     ↓                                                           │
│  WallapopService                                                │
│     ├── MockWallapopService     (MODO DEMO)                     │
│     └── ConnectWallapopService  (endpoints oficiales)           │
└─────────────────────────────────────────────────────────────────┘
```

## Qué hace

* **Multicuenta real.** Cada cuenta está aislada: anuncios, mensajes, inventario y
  credenciales nunca se mezclan.
* **Asistente en lenguaje natural.** «Cambia el precio de todos los canapés de
  135x190 a 269 €» → busca los anuncios, te enseña el plan, espera tu confirmación y
  los cambia.
* **Confirmación obligatoria.** Nada se publica, modifica ni elimina sin que el usuario
  pulse Confirmar. Hay tres barreras independientes que lo garantizan.
* **Catálogo con control de calidad.** Puntuación, errores bloqueantes y detección de
  duplicados por SKU, título, características e imágenes.
* **Plantillas de anuncio** con variables, para que todos los anuncios sean homogéneos.
* **Mensajería con asistente de ventas** que solo afirma datos reales. Si no sabe algo,
  responde «No dispongo de esa información».
* **Automatizaciones** programables, todas de revisión: ninguna publica por su cuenta.
* **Historial completo** de acciones y registro técnico sin secretos.
* **Modo DEMO** para probarlo todo sin tocar Wallapop.

## Principios de diseño

### No se inventan endpoints

LOT Bot **no contiene ninguna URL de Wallapop**. Las rutas, métodos y el mapeo de las
respuestas se declaran en un fichero YAML que se rellena con la documentación oficial:

```yaml
operations:
  update_item_price:
    method: PATCH
    path: "<ruta de la documentación oficial>"
    body:
      price: "{price}"
```

Una operación que no figure ahí **no existe** para la aplicación: se responde
`NOT_AVAILABLE_WITH_CURRENT_API` en lugar de simularla.

### La IA no puede salirse del guion

El agente solo puede invocar herramientas registradas. No accede a credenciales, no
hace peticiones HTTP, no ejecuta SQL. Si pide una función que no existe, se le
responde que no existe.

### Sin conexión real, no se finge

Si faltan credenciales o el fichero de endpoints, la aplicación **se queda en modo
DEMO y explica por qué**, en vez de aparentar estar conectada.

## Instalación (desarrollo)

```bash
git clone <url-del-repositorio> lot-bot
cd lot-bot

# Windows
powershell -ExecutionPolicy Bypass -File scripts\install_dev.ps1
.venv\Scripts\python.exe run_lot_bot.py

# Linux / macOS
./scripts/install_dev.sh
.venv/bin/python run_lot_bot.py
```

Sin configurar nada, arranca en **MODO DEMO** con cuatro cuentas simuladas.

## Generar el ejecutable para el cliente

```powershell
powershell -ExecutionPolicy Bypass -File build\build_windows.ps1
```

Resultado: `dist\LOT-Bot\LOT-Bot.exe`. El cliente descomprime la carpeta y hace doble
clic. No necesita instalar nada más.

## Configuración

Copia `.env.example` a `.env`:

```dotenv
LOT_BOT_DEMO_MODE=true          # false para la integración real
WALLAPOP_CLIENT_ID=
WALLAPOP_CLIENT_SECRET=
WALLAPOP_REDIRECT_URI=http://127.0.0.1:8723/callback
WALLAPOP_ENDPOINT_MAP=          # ruta al YAML con los endpoints oficiales
LOT_BOT_AI_PROVIDER=rules       # 'anthropic' para lenguaje natural libre
ANTHROPIC_API_KEY=
```

`.env` está en `.gitignore`. **Nunca se suben secretos al repositorio.**

Detalle completo: [`docs/dev/variables-entorno.md`](docs/dev/variables-entorno.md).

## Pruebas

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

Cubren: mock de Wallapop, mapa de endpoints, catálogo, control de calidad, duplicados,
plantillas, imágenes, seguridad y cifrado, agente IA y confirmaciones, asistente de
ventas, flujo de extremo a extremo en DEMO y humo de la interfaz.

## Estructura

```
lot_bot/
├── config/           ajustes, rutas, secretos cifrados
├── logs/             logging con redacción de secretos
├── database/         modelo SQLite (SQLAlchemy 2.0)
├── wallapop/         contrato, mock, integración real, OAuth, cuentas
├── catalog/          productos, calidad, duplicados
├── templates_engine/ plantillas de anuncio
├── images/           importación y deduplicación de fotos
├── publishing/       vista previa, publicación, espejo de anuncios
├── messages/         bandeja de entrada y asistente de ventas
├── market/           análisis de precios
├── automation/       tareas programadas
├── ai/               proveedores, herramientas y orquestador
├── core/             auditoría y eventos
├── ui/               ventana principal, tema y 12 pantallas
└── bootstrap.py      ensamblado de servicios
```

## Documentación

**Para desarrollo**

| Documento | Contenido |
|---|---|
| [Arquitectura](docs/dev/arquitectura.md) | Diseño, capas, agente IA, multicuenta |
| [Instalación](docs/dev/instalacion.md) | Entorno de desarrollo y pruebas |
| [Variables de entorno](docs/dev/variables-entorno.md) | Todas las opciones |
| [Conexión con Wallapop](docs/dev/conexion-wallapop.md) | Rellenar el mapa de endpoints |
| [Compilación](docs/dev/compilacion.md) | Generar el `.exe` |
| [Solución de errores](docs/dev/solucion-errores.md) | Problemas y causas |
| [Actualización](docs/dev/actualizacion.md) | Versiones, migraciones, ampliaciones |

**Para el cliente**

[`docs/cliente/`](docs/cliente/README.md) — ocho guías paso a paso, escritas sin
tecnicismos.

## Estado de las funciones

| Función | Estado |
|---|---|
| Multicuenta con aislamiento | ✅ |
| Asistente IA con herramientas y confirmación | ✅ |
| Catálogo, inventario y calidad | ✅ |
| Plantillas con variables | ✅ |
| Gestión y deduplicación de imágenes | ✅ |
| Publicación con vista previa | ✅ |
| Mensajería y asistente de ventas | ✅ |
| Automatizaciones programadas | ✅ |
| Historial y registro seguro | ✅ |
| Modo DEMO completo | ✅ |
| Empaquetado para Windows | ✅ |
| Integración real con Wallapop | ⚙️ Lista, a la espera de credenciales y endpoints oficiales |
| Generación de imágenes por IA | ⛔ Requiere un proveedor autorizado, no incluido |
| Datos de mercado externos | ⚙️ Solo con fuente autorizada; sin ella se avisa |

## Licencia

Software propietario. Ver [LICENSE](LICENSE).
