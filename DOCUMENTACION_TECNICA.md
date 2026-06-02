# BarberSync - Documentación Técnica del Proyecto

## 1. Visión General y Objetivo
**BarberSync** es una plataforma SaaS (Software as a Service) multi-tenant diseñada para la gestión integral de barberías. Su objetivo principal es resolver la complejidad administrativa de los negocios de barbería que operan con una o múltiples sucursales bajo una misma organización. 

**Problemas que soluciona:**
- **Gestión Multi-Sucursal:** Permite administrar múltiples barberías desde una sola cuenta organizativa, facilitando la visión global del negocio.
- **CRM Centralizado:** Unifica la base de datos de clientes a nivel de organización, evitando duplicados y mejorando la experiencia del cliente en cualquier sucursal.
- **Gestión de Agendamiento Avanzada:** Administra horarios de trabajo, especialidades de los barberos, excepciones (vacaciones, recesos) y citas, con cálculos dinámicos de duración y precio.
- **Control Financiero y de Inventario:** Integra la facturación (servicios y productos) y un control estricto de inventario mediante un registro inmutable de movimientos de stock.
- **Recordatorios Automáticos:** Reduce el ausentismo (no-shows) mediante un sistema de notificaciones asíncronas para clientes y barberos.

## 1.1 Políticas de Seguridad en APIs y Control Multi-Tenant

Absolutamente todos los endpoints actuales y futuros que involucren la creación, extracción, actualización, eliminación o interacción general con datos sensibles deben implementar de manera nativa e inequívoca las capas de Rate Limiting y Verificación de Propiedad de Datos (Aislamiento Tenant) descritas en este estándar. Ningún endpoint de datos puede quedar expuesto sin estas dos directrices vigentes.

## 2. Arquitectura del Sistema
El sistema está construido con **Django 5.1+** y utiliza **PostgreSQL** como base de datos principal.

### 2.1 Componentes Principales
- **Arquitectura Multi-Tenant:** Basada en jerarquía lógica `Organization -> Barbershop -> Data`. La aislación de datos por sucursal se logra a través del `TenantMiddleware` y el modelo abstracto `TenantModel`.
- **Autenticación y Autorización:** Implementado con `django-allauth`, soporta inicio de sesión social (Google) y tradicional por correo electrónico. Roles de usuario a nivel de membresía (Owner, Admin, Barber).
- **Cola de Tareas (Task Queue):** Utiliza `django-q2` (usando el ORM de Django como broker) para procesar notificaciones y recordatorios asíncronos.
- **API Pública y PWA:** Soporta Cross-Origin Resource Sharing (CORS) para reservas públicas y cuenta con soporte para Progressive Web App (django-pwa).
- **Gestión de Correos:** En producción utiliza `django-anymail` con el proveedor Mailgun.

## 3. Estructura de Aplicaciones y Modelos de Datos

El proyecto se divide de forma modular en varias aplicaciones dentro del directorio `apps/`.

### 3.1 Core (`apps/core`)
Contiene utilidades transversales para todo el proyecto.
- **Modelos Base:** 
  - `AuditModel`: Modelo abstracto que provee estampas de tiempo (`created_at`, `updated_at`) y registro automático de auditoría.
  - `TenantModel`: Modelo abstracto que vincula obligatoriamente cualquier registro a una sucursal (`Barbershop`).
  - `OrganizationModel`: Modelo abstracto que vincula registros a nivel de organización.
- **Auditoría:** `AuditLog` mantiene un historial inmutable de cambios (creación/actualización) en los registros críticos.

### 3.2 Accounts (`apps/accounts`)
Maneja la jerarquía multi-tenant, usuarios y perfiles.
- **User:** Modelo de usuario personalizado que utiliza el correo como identificador principal.
- **Organization:** Inquilino principal (top-level tenant). Agrupa sucursales.
- **Barbershop:** Representa una sucursal física. Posee un `booking_uid` para su enlace público.
- **Membership:** Conecta a un `User` con una `Organization` y, opcionalmente, con una `Barbershop` específica. Define los roles (propietario, administrador, barbero).
- **BarberProfile:** Extiende la información para usuarios con rol de barbero. Soporta asignación a múltiples sucursales, tiempos de descanso (buffer) y horarios de almuerzo.

### 3.3 Clients (`apps/clients`)
CRM centralizado.
- **Client:** Almacenado a nivel de organización (`OrganizationModel`). Permite que un cliente sea reconocido en todas las sucursales del negocio. Puede estar vinculado a una cuenta de usuario (`User`) si se registra en el portal público.

### 3.4 Scheduling (`apps/scheduling`)
El núcleo operativo de BarberSync, gestionando servicios, horarios y citas.
- **Catálogo de Servicios:** `CategoriaServicio` y `Service`.
- **Historial de Precios:** `HistorialPrecioServicio` rastrea cambios de tarifas.
- **Especialización:** `BarberService` define qué servicios ofrece cada barbero y permite precios personalizados.
- **Horarios:** `WorkSchedule` define horarios regulares semanales y `ScheduleException` bloqueos puntuales (vacaciones, descansos).
- **Citas:** `Appointment` agrupa las reservas. Contiene la hora de inicio, el cliente, el barbero y el estado. Se vincula a múltiples `AppointmentService` que congelan el precio en el momento de la reserva.
- **Intervenciones:** `Intervencion`, `IntervencionServicio` y `IntervencionProducto` registran el trabajo real ejecutado y los productos de inventario consumidos durante la cita.

### 3.5 Finance (`apps/finance`)
Centraliza los ingresos.
- **Sale:** Representa una transacción económica. Puede originarse de un servicio (cita) o venta directa de productos.
- **SaleItem:** Líneas de la factura que refieren a servicios o productos, congelando su precio y cantidad al momento del cobro.

### 3.6 Inventory (`apps/inventory`)
Gestión del stock de productos.
- **Product & ProductCategory:** Catálogo físico de productos para venta o uso interno. Define cantidades límite de stock bajo.
- **StockMovement:** Registro inmutable (Append-only) para cada cambio de stock (reabastecimiento, venta, pérdida, ajuste). Este modelo actualiza automáticamente el `stock_quantity` del `Product` al guardarse.

### 3.7 Notifications (`apps/notifications`)
- **NotificationLog:** Registro inmutable de cada notificación (email) enviada o intentada, incluyendo recordatorios de 24h/1h para clientes y recordatorios para barberos.

### 3.8 Booking (`apps/booking`)
Módulo encargado de exponer las vistas e interfaces para que los clientes puedan agendar citas públicamente, conectando con `scheduling` y `clients`.

## 4. Notas Técnicas y Patrones de Diseño Relevantes
- **Inmutabilidad en Históricos:** Precios en citas (`AppointmentService`), registros financieros (`SaleItem`) y movimientos de inventario (`StockMovement`) utilizan estrategias de snapshot (fotografía de datos en el momento) para que cambios futuros en el catálogo no alteren datos históricos.
- **Soft Deletion / Is Active:** Se prefiere el uso de flags booleanos (e.g., `is_active=False`) sobre la eliminación dura en base de datos para preservar la integridad referencial y de auditoría en servicios, sucursales y usuarios.
- **Integridad y Validaciones:** Los modelos utilizan `UniqueConstraint` e índices (`db_index`) de forma extensiva en combinaciones como `[organization, slug]`, `[barber, start_time]`, previniendo solapamientos en bases de datos.
- **Datepickers (Flatpickr) – Regla obligatoria:** Todo datepicker del proyecto debe incluir el plugin `confirmDatePlugin` con el botón "Aceptar" siempre visible. La configuración estándar es:
  - **CDN requeridos:** `flatpickr/dist/plugins/confirmDate/confirmDate.css` y `flatpickr/dist/plugins/confirmDate/confirmDate.js`.
  - **Helper reutilizable:** Definir `function makeFpConfirmPlugin() { return confirmDatePlugin({ confirmText: 'Aceptar', showAlways: true }); }` en cada template que use Flatpickr.
  - **Uso:** Añadir `plugins: [makeFpConfirmPlugin()]` en toda inicialización `flatpickr(...)`.
  - **Estilos del botón:** `.flatpickr-confirm` con `background: #ff2301`, hover `#e01e00`, SVG oculto, `border-radius: 0 0 8px 8px`, `font-weight: 600`, texto blanco.
- **Formato de hora – 24 horas – Regla obligatoria:** Todo el proyecto usa formato de 24 horas (militar).
  - **Django Templates:** Usar `|date:"d/m/Y H:i"` o `|time:"H:i"`.
  - **Flatpickr:** Siempre `time_24hr: true` y `dateFormat` con `H:i`.
  - **FullCalendar:** Configurar `slotLabelFormat` y `eventTimeFormat` con `{ hour: '2-digit', minute: '2-digit', hour12: false }`.
  - **ag-Grid / JavaScript:** Usar `toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', hour12: false })` o `strftime("%H:%M")` en Python.
  - **APIs Python (strftime):** Usar `%H:%M` para formato display. Mantener ISO 8601 (`%Y-%m-%dT%H:%M`) para valores internos/API.
- **Tags unificados – Regla obligatoria:** Todos los tags (ej. conteo de visitas, estados, badges) deben usar el estilo unificado: fondo semitransparente del color correspondiente, texto contrastante, bordes redondeados (`border-radius: 9999px`) y padding compacto (`padding: 6px 10px`, `font-size: 11px`, `font-weight: 600`). Referencia CSS: `.estado-badge`, `.svc-tag`, `.prod-tag` en el módulo de Intervenciones.

## 5. Sistema de Facturación y Pagos (`apps/billing`)

### 5.1 Visión General

El sistema de facturación soporta **múltiples pasarelas de pago** mediante un patrón Strategy/Factory. Actualmente integrados:

- **Stripe** — Tarjeta de crédito internacional, suscripciones recurrentes.
- **Wompi** — Pagos locales colombianos (PSE, tarjeta débito/crédito, Nequi).

El enrutamiento entre pasarelas se determina por el país de la `Organization` del usuario, configurado en `BILLING_COUNTRY_PROVIDER_MAP`.

**Principios de diseño:**
- **Zero Trust Frontend**: El formulario de checkout solo envía `plan_code` y `chosen_provider`. Los montos nunca viajan al navegador.
- **Server-to-Server Validation**: Las suscripciones se activan **exclusivamente** mediante webhooks verificados, nunca por redirects del navegador.
- **Idempotencia**: `ProcessedWebhookEvent` con `select_for_update()` y `transaction.atomic()` evita procesamiento duplicado.
- **Versionado de precios**: Los registros `PlanPrice` nunca se sobreescriben; se marcan `is_current=False` y se crean nuevos.

### 5.2 Modelos de Datos

#### `Plan` (`billing_plan`)
| Campo | Tipo | Descripción |
|---|---|---|
| `code` | `CharField(30, unique)` | Identificador del plan (`INDEPENDIENTE`, `LOCAL`, `CADENA`) |
| `name` | `CharField(80)` | Nombre visible en español |
| `description` | `TextField` | Descripción detallada |
| `features` | `JSONField` | Lista de características incluidas |
| `max_barbers` | `PositiveIntegerField(null)` | Límite de barberos (null = ilimitados) |
| `max_branches` | `PositiveIntegerField(null)` | Límite de sucursales (null = ilimitadas) |
| `is_active` | `BooleanField` | Solo los planes activos aparecen en la landing y checkout |

#### `PlanPrice` (`billing_plan_price`)
| Campo | Tipo | Descripción |
|---|---|---|
| `plan` | `FK → Plan` | Plan al que pertenece |
| `amount_minor` | `PositiveBigIntegerField` | Precio en la **unidad menor** de la moneda (centavos USD, centavos COP) |
| `currency` | `CharField(3)` | Código ISO 4217 (`USD`, `COP`, `MXN`) |
| `interval` | `CharField(10)` | `month` o `year` |
| `provider` | `CharField(20)` | `stripe` o `wompi` |
| `provider_price_id` | `CharField(100)` | ID del precio en Stripe, o identificador lógico para Wompi |
| `is_current` | `BooleanField` | Solo un price `True` por combinación (plan, provider, currency, interval) |
| `valid_from` / `valid_to` | `DateTimeField` | Periodo de vigencia del precio |

**Regla CRÍTICA de `amount_minor`:**
- USD: `$19.00/mes` → `amount_minor = 1900` (centavos)
- COP: `$29.900/mes` → `amount_minor = 2990000` (centavos: pesos × 100)
- Wompi recibe este valor directamente como `amount_in_cents` sin multiplicación adicional.

**Regla CRÍTICA de versionado:** Para cambiar un precio, **nunca** modificar el registro existente. Siempre:
1. `PlanPrice.objects.filter(...).update(is_current=False, valid_to=now())`
2. Crear un nuevo `PlanPrice` con el nuevo monto y `is_current=True`.

#### `Subscription` (`billing_subscription`)
| Campo | Tipo | Descripción |
|---|---|---|
| `organization` | `FK → Organization` | Organización suscrita (nullable durante registro) |
| `user` | `FK → User` | Usuario que pagó (nullable si se asocia por organization) |
| `plan` | `FK → Plan` | Plan contratado |
| `plan_price` | `FK → PlanPrice` | Snapshot del precio al momento de la suscripción |
| `provider` | `CharField(20)` | Pasarela que procesó el pago |
| `provider_subscription_id` | `CharField(100)` | ID de suscripción en Stripe, o reference en Wompi |
| `provider_customer_id` | `CharField(100)` | ID de customer en Stripe (vacío en Wompi) |
| `wompi_transaction_id` | `CharField(100)` | ID de transacción en Wompi (vacío en Stripe) |
| `status` | `CharField(15)` | `trialing`, `active`, `past_due`, `canceled`, `expired` |
| `trial_end` | `DateTimeField(null)` | Fin del periodo de prueba |
| `current_period_start/end` | `DateTimeField(null)` | Periodo de facturación actual |

**Restricción única:** Solo puede existir una suscripción activa/trialing/past_due por organización (`one_active_subscription_per_org`).

#### `Invoice` (`billing_invoice`)
Snapshot inmutable de cada cobro realizado. Referencia directa al `PlanPrice` (`plan_price_snapshot`) para auditoría.

#### `ProcessedWebhookEvent` (`billing_webhook_event`)
Registro idempotente de cada webhook recibido. Previene procesamiento duplicado mediante `UniqueConstraint(provider, event_id)` y `select_for_update()` dentro de `transaction.atomic()`.

### 5.3 Enrutamiento por País (`Organization.country_code`)

La `Organization` tiene un campo `country_code` (ISO 3166-1 alpha-2, default `"CO"`) que determina la pasarela y moneda por defecto.

**Configuración en `settings/base.py`:**

```python
BILLING_COUNTRY_PROVIDER_MAP = {
    "CO": {"default": "wompi", "allowed": ["wompi", "stripe"]},
}
BILLING_COUNTRY_CURRENCY_MAP = {
    "CO": "COP",
    "US": "USD",
    "MX": "MXN",
}
BILLING_DEFAULT_PROVIDER = "stripe"      # Fallback global
BILLING_DEFAULT_CURRENCY = "USD"          # Fallback global
```

**Lógica de resolución** (`_resolve_provider_and_price` en `views.py`):

1. Se lee `chosen_provider` del POST del usuario.
2. Se obtiene el `country_code` de la `Organization` del usuario autenticado.
3. Se busca la configuración del país en `BILLING_COUNTRY_PROVIDER_MAP`.
4. Si `chosen_provider` está en la lista de permitidos, se usa. Sino, se usa el default del país.
5. Se busca el `PlanPrice` que coincida con `(plan, provider, currency, is_current=True)`.
6. Fallbacks progresivos: sin moneda → sin provider → cualquier price activo.

**Para Colombia (`country_code="CO"`):** El usuario ve un toggle "PSE / Tarjeta local" vs "Tarjeta Internacional" en la landing. Por defecto se muestra Wompi con precios en COP. El usuario puede cambiar a Stripe para pagar en USD con tarjeta internacional.

**Para otros países o sin organización:** Se enruta directamente a Stripe con la moneda del país, o USD como fallback.

### 5.4 Patrón Strategy/Factory — Proveedores (`providers.py`)

```
BaseBillingProvider (ABC)
├── StripeProvider
├── WompiProvider
└── (futuros: PayUProvider, PayPalProvider, MercadoPagoProvider)

BillingProviderFactory
├── get_provider(name) → instancia singleton del proveedor
├── get_default_provider_for_country(code) → "wompi" | "stripe"
└── get_allowed_providers_for_country(code) → ["wompi", "stripe"] | ["stripe"]
```

Cada proveedor implementa:
- `create_customer(user, organization)` → ID de customer en la pasarela
- `create_checkout_session(user, plan_price, success_url, cancel_url)` → dict con `checkout_url`
- `cancel_subscription(subscription)` → bool
- `validate_webhook_signature(request)` → bool
- `fetch_checkout_session(session_id)` → dict con estado
- `get_event_type(payload)` / `get_event_id(payload)` → string

### 5.5 Flujo de Pago — Stripe

```
1. [POST /billing/checkout/] → CheckoutView
   ├─ _resolve_provider_and_price() → provider="stripe", PlanPrice(provider="stripe", currency="USD")
   ├─ StripeProvider.create_checkout_session()
   │   ├─ _ensure_customer() → busca o crea Stripe Customer
   │   ├─ stripe.checkout.Session.create(mode="subscription", ...)
   │   └─ metadata: {plan_code, organization_id, user_id, provider}
   └─ redirect(session.url)

2. [Stripe] → Usuario completa pago en Checkout

3. [Stripe Webhook] POST /billing/webhook/stripe/
   ├─ validate_webhook_signature() → verifica HTTP_STRIPE_SIGNATURE
   ├─ Idempotencia: ProcessedWebhookEvent.select_for_update() + get_or_create()
   ├─ event_type == "checkout.session.completed"
   │   └─ _activate_subscription(payload, "stripe")
   │       ├─ Crea/retorna Subscription(status=ACTIVE)
   │       └─ Crea Invoice(status=PAID)
   ├─ event_type == "customer.subscription.updated" → actualiza status
   └─ event_type == "customer.subscription.deleted" → status=CANCELED
```

### 5.6 Flujo de Pago — Wompi

```
1. [POST /billing/checkout/] → CheckoutView
   ├─ _resolve_provider_and_price() → provider="wompi", PlanPrice(provider="wompi", currency="COP")
   ├─ WompiProvider.create_checkout_session()
   │   ├─ Genera referencia: "bs_LOCAL_1716...abcd"
   │   ├─ amount_in_cents = plan_price.amount_minor  (ya en centavos)
   │   ├─ integrity = SHA-256(reference + amount_in_cents + currency + integrity_secret)
   │   └─ URL: https://checkout.wompi.co/p/?public-key=...&amount-in-cents=...&reference=...&signature:integrity=...
   └─ redirect(checkout_url)

2. [Wompi] → Usuario paga con tarjeta/PSE/Nequi

3. [Wompi Webhook] POST /billing/webhook/wompi/
   ├─ validate_webhook_signature()
   │   └─ SHA-256(propiedades_concatenadas + timestamp + event_secret) vs payload.signature.checksum
   ├─ Idempotencia: ProcessedWebhookEvent.select_for_update() + get_or_create()
   ├─ event_type == "transaction.updated"
   │   └─ status in ("APPROVED", "PAYED")
   │       └─ _handle_transaction_updated(payload)
   │           ├─ Extrae plan_code de metadata o reference
   │           ├─ Crea Subscription(status=ACTIVE, wompi_transaction_id=...)
   │           └─ Crea Invoice(status=PAID)
   └─ Ignora otros estados (DECLINED, ERROR, etc.)
```

**Nota sobre Wompi:** Wompi no tiene concepto de "Products" ni "Prices" en su API. Cada checkout se genera dinámicamente con `reference`, `amount_in_cents`, `currency` y la firma de integridad. El campo `provider_price_id` en `PlanPrice` para Wompi es solo un identificador lógico interno, no un ID externo.

**URL del checkout de Wompi:** Wompi usa un dominio único `https://checkout.wompi.co/p/` tanto para sandbox como producción. La llave pública (`pub_test_` vs `pub_prod_`) determina el entorno. La URL antigua `https://checkout.wompi.co/checkout/` o `https://sandbox.wompi.co/checkout/` **no son válidas** y devuelven errores de página no disponible o accesos prohibidos.

### 5.7 Landing Page — Checkout UX

La landing (`templates/landing.html`) es un template standalone (no extiende `base.html`).

**Para usuarios autenticados con `Organization.country_code = "CO"`:**
- Se muestra un toggle de proveedores: "PSE / Tarjeta local" (Wompi) vs "Tarjeta Internacional" (Stripe).
- Los precios cambian dinámicamente según la pasarela seleccionada (COP para Wompi, USD para Stripe).
- JavaScript (`selectProvider()`) actualiza los inputs ocultos `chosen_provider` y el display de precios.

**Para usuarios no autenticados o sin Colombia:**
- Se muestran precios en USD con link a registro.
- No se muestra el toggle de proveedores.

**El formulario POST envía exclusivamente:**
- `plan_code`: `INDEPENDIENTE`, `LOCAL` o `CADENA`
- `chosen_provider`: `wompi` o `stripe`
- `csrfmiddlewaretoken`: Token CSRF

Los montos **nunca** viajan al navegador.

### 5.8 Configuración de Credenciales

Variables de entorno en `.env`:

```bash
# Stripe
STRIPE_SECRET_KEY=sk_test_...          # Clave privada (test o live)
STRIPE_PUBLISHABLE_KEY=pk_test_...     # Clave pública (test o live)
STRIPE_WEBHOOK_SECRET=whsec_...        # Secreto del webhook endpoint

# Wompi
WOMPI_PUBLIC_KEY=pub_test_...          # Llave pública (sandbox) o pub_prod_... (producción)
WOMPI_PRIVATE_KEY=prv_test_...         # Llave privada (sandbox) o prv_prod_... (producción)
WOMPI_EVENT_SECRET=test_events_...     # Secreto de eventos (sandbox) o prod_events_... (producción)
WOMPI_SANDBOX=True                      # True para sandbox, False para producción

# Enrutamiento
BILLING_DEFAULT_PROVIDER=stripe         # Proveedor fallback global
BILLING_DEFAULT_CURRENCY=USD            # Moneda fallback global (ver nota abajo)
BILLING_BASE_URL=https://abc123.ngrok-free.app  # URL pública para redirects (ngrok en dev, dominio en prod)
```

**Nota sobre `BILLING_DEFAULT_CURRENCY`:** Este valor se usa como fallback cuando el país del usuario no está en `BILLING_COUNTRY_CURRENCY_MAP`. Para Colombia, la moneda se resuelve como COP por el map, sin importar el valor por defecto.

**Nota sobre `BILLING_BASE_URL`:** Obligatorio para que Wompi funcione. Wompi requiere URLs de redirect públicas y HTTPS. Para desarrollo local, usa tu URL de ngrok (ej: `https://abc123.ngrok-free.app`). En producción, usa tu dominio (ej: `https://barbersync.app`). Si está vacío, el sistema usa `request.build_absolute_uri()` como fallback (solo funciona para Stripe en desarrollo local).

**Dónde encontrar las credenciales en cada pasarela:**
- **Stripe:** Dashboard → Developers → API keys (para secret/publishable keys) → Webhooks (para webhook secret).
- **Wompi:** Dashboard → Configuración → Llaves de integración (para public/private keys) → Eventos (para event secret y registro de URL de webhook).

### 5.9 Cambio de Precios — Procedimiento

Los precios **nunca** se actualizan in-place. Siempre se crea un nuevo `PlanPrice`:

```python
from django.utils import timezone
from apps.billing.models import Plan, PlanPrice

plan = Plan.objects.get(code="LOCAL")

# 1. Desactivar precio viejo
PlanPrice.objects.filter(
    plan=plan, provider="wompi", currency="COP", is_current=True
).update(is_current=False, valid_to=timezone.now())

# 2. Crear nuevo precio
PlanPrice.objects.create(
    plan=plan,
    amount_minor=8900000,           # $89.000 COP = 8.900.000 centavos
    currency="COP",
    interval="month",
    provider="wompi",
    provider_price_id="wompi_cop_local_month",
    is_current=True,
)
```

Para Stripe, adicionalmente debe crearse el Price en el Dashboard de Stripe y actualizar `provider_price_id` con el ID real (`price_1XXXX`).

### 5.10 Diagrama de Tablas

```
billing_plan
  └── billing_plan_price (FK → plan)
        └── billing_subscription (FK → plan, FK → plan_price)
              └── billing_invoice (FK → subscription, FK → plan_price_snapshot)

billing_webhook_event (idempotencia, sin FK)
```

```
accounts_organization (country_code)
  └── billing_subscription (FK → organization)
  └── billing_invoice (FK → organization)

accounts_user
  └── billing_subscription (FK → user, nullable)
  └── billing_invoice (FK → user, nullable)
```

## 6. Pruebas Locales de Webhooks

Los webhooks requieren que la pasarela pueda enviar un HTTP POST a tu servidor local. Dado que `localhost:8000` no es accesible desde Internet, se necesita un túnel.

### 6.1 Opción A: ngrok (Recomendada para Wompi y Stripe)

```bash
# 1. Instalar ngrok (https://ngrok.com/download)
# 2. Iniciar el servidor Django
venv\Scripts\python.exe manage.py runserver

# 3. En otra terminal, crear túnel
ngrok http 8000
```

ngrok mostrará una URL como `https://a1b2c3d4.ngrok-free.app`. Esa es tu URL pública.

**IMPORTANTE: Configura `BILLING_BASE_URL` en `.env` con la URL de ngrok:**
```bash
BILLING_BASE_URL=https://a1b2c3d4.ngrok-free.app
```

Sin esta variable, Wompi recibirá `http://127.0.0.1:8000/...` como redirect-url y bloqueará la petición (requiere HTTPS público). Reinicia Django después de cambiar `.env`.

**Configurar en Stripe:**
1. Ir a Dashboard → Developers → Webhooks → Add endpoint
2. URL: `https://a1b2c3d4.ngrok-free.app/billing/webhook/stripe/`
3. Seleccionar eventos: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
4. Copiar el `whsec_...` y colocarlo en `.env` como `STRIPE_WEBHOOK_SECRET`
5. Reiniciar Django (para que lea la nueva variable de entorno)

**Configurar en Wompi:**
1. Ir al Dashboard → Configuración → Eventos
2. URL del webhook: `https://a1b2c3d4.ngrok-free.app/billing/webhook/wompi/`
3. Marcar el evento `transaction.updated`
4. Copiar el secreto de eventos (`test_events_...` o `prod_events_...`) y colocarlo en `.env` como `WOMPI_EVENT_SECRET`

**Verificar que ngrok funciona:**
```bash
# En otra terminal, simular un request:
curl https://a1b2c3d4.ngrok-free.app/billing/webhook/stripe/ -X POST
# Debería devolver 403 (signature validation failed) = está llegando
```

### 6.2 Opción B: Stripe CLI (Solo para Stripe)

```bash
# 1. Instalar Stripe CLI (https://stripe.com/docs/stripe-cli)
# 2. Login
stripe login

# 3. Reenviar eventos de prueba al servidor local
stripe listen --forward-to localhost:8000/billing/webhook/stripe/

# 4. En otra terminal, disparar un evento de prueba
stripe trigger checkout.session.completed
```

El CLI imprime el `whsec_...` que debes poner en `STRIPE_WEBHOOK_SECRET`. Usa `--skip-verify` si no quieres validar la firma durante desarrollo.

### 6.3 Probar el Checkout Completo Localmente

```bash
# 1. Levantar el servidor
venv\Scripts\python.exe manage.py runserver

# 2. Levantar ngrok
ngrok http 8000

# 3. Crear un usuario de prueba con organización
venv\Scripts\python.exe manage.py shell
```

```python
from apps.accounts.models import User, Organization, Membership
from apps.billing.models import Plan

# Crear usuario
user = User.objects.create_user(email="test@example.com", password="test1234")

# Crear organización colombiana
org = Organization.objects.create(
    name="Barbería Test",
    slug="barberia-test",
    owner=user,
    country_code="CO",
)

# Crear membresía
Membership.objects.create(
    user=user,
    organization=org,
    role=Membership.Role.OWNER,
    is_active=True,
)

# Verificar que los planes existen
for p in Plan.objects.filter(is_active=True):
    print(p.code, p.name)
    for pp in p.prices.filter(is_current=True):
        print(f"  {pp.provider}: {pp.amount_minor} {pp.currency}")
```

```bash
# 4. Iniciar sesión en http://localhost:8000/ con test@example.com / test1234
# 5. Click en "Ver planes" → Elegir plan → Seleccionar proveedor → Submit
# 6. Completar pago en Stripe/Wompi sandbox
# 7. Verificar webhook en consola de Django (mira los logs)
# 8. Verificar en shell que se crearon Subscription e Invoice
```

### 6.4 Testing con Stripe Sandbox (Tarjetas de Prueba)

Stripe provee tarjetas de prueba para cada escenario:

| Escenario | Número de Tarjeta | Resultado |
|---|---|---|
| Pago exitoso | `4242 4242 4242 4242` | Suscripción activada |
| Pago rechazado | `4000 0000 0000 0002` | Falla |
| Requiere autenticación 3D | `4000 0027 0000 3220` | Flujo 3DS |
| Disputa / Chargeback | `4000 0000 0000 3220` | Disputa después de pago |

Cualquier CVC, fecha futura y código postal funcionan con estas tarjetas.

### 6.5 Testing con Wompi Sandbox

Wompi Sandbox acepta tarjetas de prueba colombianas:

| Escenario | Número | Resultado |
|---|---|---|
| Tarjeta aprobada | `4242 4242 4242 4242` | Transacción APPROVED |
| PSE aprobado | Seleccionar banco y completar flujo | Transacción APPROVED |

En sandbox, la mayoría de transacciones se aprueban automáticamente. El webhook `transaction.updated` llega con `status: "APPROVED"` o `status: "PAYED"`.

### 6.6 URLs de Webhook por Entorno

| Entorno | Stripe URL | Wompi URL |
|---|---|---|
| Local (ngrok) | `https://{id}.ngrok-free.app/billing/webhook/stripe/` | `https://{id}.ngrok-free.app/billing/webhook/wompi/` |
| Staging | `https://staging.barbersync.app/billing/webhook/stripe/` | `https://staging.barbersync.app/billing/webhook/wompi/` |
| Producción | `https://barbersync.app/billing/webhook/stripe/` | `https://barbersync.app/billing/webhook/wompi/` |

## 7. Servicio Unificado de Notificaciones (Multicanal Asíncrono)

### 7.1 Visión General

BarberSync implementa un motor de notificaciones centralizado y multicanal en `apps/notifications/notifications.py`. Todo envío de correo o SMS pasa por la función `send_notification()`, garantizando:

- **Asíncrono**: Ningún envío bloquea el hilo HTTP. Se despacha vía `django_q.async_task`.
- **Multicanal**: Soporta `email` y `sms` simultáneamente. Los canales se especifican como lista.
- **Registro inmutable**: Cada notificación (exitosa o fallida) se registra en `NotificationLog` con canal, tipo, destinatario y error.
- **Plantillas dinámicas**: Email renderiza HTML corporativo; SMS trunca y adapta a texto plano ≤160 caracteres.

### 7.2 Firma de la Función Principal

```python
from apps.notifications.notifications import send_notification

send_notification(
    recipient,           # dict {"email", "phone", "name"} o objeto Django (User/Client)
    notif_type,          # str: "reminder_24h", "reschedule_client", etc.
    context=None,        # dict con variables de plantilla
    channels=None,        # list[str]: ["email"], ["sms"], o ["email", "sms"]
    appointment_id=None,  # int|None: FK para el log
    subject=None,         # str|None: asunto override (auto-generado si None)
    html_template=None,    # str|None: path de plantilla override
)
```

### 7.3 Parámetros

| Parámetro | Tipo | Default | Descripción |
|---|---|---|---|
| `recipient` | `dict` o objeto | *requerido* | Diccionario con claves `email`, `phone`, `name`, o un modelo con esos atributos |
| `notif_type` | `str` | *requerido* | Tipo de notificación. Valores: `reminder_24h`, `reminder_1h`, `barber_reminder`, `cancellation`, `confirmation`, `reschedule_client`, `reschedule_barber` |
| `context` | `dict` | `{}` | Variables de contexto para renderizar plantillas HTML y generar mensajes SMS |
| `channels` | `list[str]` | `["email"]` | Lista de canales a los que despachar. Valores: `"email"`, `"sms"` |
| `appointment_id` | `int` | `None` | ID de la cita asociada (para el `NotificationLog`) |
| `subject` | `str` | `None` | Asunto del correo. Si es `None`, se genera automáticamente según `notif_type` y `context` |
| `html_template` | `str` | `None` | Path de plantilla Django (ej: `"notifications/reschedule_client.html"`). Si es `None`, usa `"notifications/{notif_type}.html"` |

### 7.4 Canales Soportados

| Canal | Clave | Implementación |
|---|---|---|
| Email | `"email"` | `django.core.mail.send_mail` con HTML renderizado. Proveedor: Mailgun (vía `django-anymail`) en producción, consola en desarrollo |
| SMS | `"sms"` | Twilio (si `TWILIO_ACCOUNT_SID` y `TWILIO_AUTH_TOKEN` están configurados). Si no, el SMS se logge pero no se envía (modo desarrollo) |

### 7.5 NotificationLog – Modelo de Registro

| Campo | Tipo | Descripción |
|---|---|---|
| `appointment` | FK → Appointment | Cita asociada (nullable) |
| `recipient_email` | EmailField | Correo del destinatario (blank para SMS-only) |
| `recipient_phone` | CharField(20) | Teléfono del destinatario (blank para email-only) |
| `recipient_name` | CharField(150) | Nombre del destinatario |
| `channel` | CharField(10) | `"email"` o `"sms"` |
| `notif_type` | CharField(25) | Tipo de notificación |
| `subject` | CharField(200) | Asunto (vacío para SMS) |
| `body` | TextField | Cuerpo completo (HTML para email, texto para SMS) |
| `sent_at` | DateTimeField | Marca temporal automática |
| `success` | BooleanField | `True` si el envío fue exitoso |
| `error_message` | TextField | Mensaje de error (blank si exitoso) |

### 7.6 Variables de Entorno para SMS (Twilio)

```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+1234567890
```

### 7.7 Ejemplos de Uso

**Notificar al cliente de reprogramación (email + SMS):**

```python
from apps.notifications.notifications import send_notification

send_notification(
    recipient={"email": appointment.client.email, "phone": appointment.client.phone, "name": appointment.client.name},
    notif_type="reschedule_client",
    context={
        "recipient_name": appointment.client.name,
        "barbershop_name": appointment.barbershop.name,
        "barber_name": str(appointment.barber),
        "service_names": service_names,
        "start_time": appointment.start_time,
        "new_start_time": appointment.start_time.strftime("%d/%m/%Y %H:%M"),
    },
    channels=["email", "sms"],
    appointment_id=appointment.pk,
)
```

**Notificar al barbero (solo si el cambio fue hecho por un admin):**

```python
send_notification(
    recipient={"email": barber.user.email, "phone": barber.phone or "", "name": str(barber)},
    notif_type="reschedule_barber",
    context={...},
    channels=["email", "sms"] if barber.phone else ["email"],
    appointment_id=appointment.pk,
)
```

**Programar recordatorios de cita (24h, 1h cliente, 1h barbero):**

```python
from apps.notifications.notifications import send_appointment_reminders

send_appointment_reminders(appointment.pk)
```

### 7.8 Plantillas HTML de Notificación

Las plantillas se encuentran en `templates/notifications/`:

| Plantilla | Canal | Descripción |
|---|---|---|
| `reminder_24h.html` | Email | Recordatorio 24 horas antes |
| `reminder_1h.html` | Email | Recordatorio 1 hora antes |
| `barber_reminder.html` | Email | Recordatorio 1 hora antes (barbero) |
| `reschedule_client.html` | Email | Cita reprogramada (cliente) |
| `reschedule_barber.html` | Email | Agenda modificada (barbero) |
| `invitation.html` | Email | Invitación a organización |

### 7.9 Refactorización de Código Existente

- **`apps/notifications/tasks.py`**: Ahora delega a `apps/notifications.notifications.send_appointment_reminders()` y `_send_reminder_task()`. La signatura de `send_reminder()` y `schedule_appointment_reminders()` se mantienen como shim para compatibilidad con tareas `django_q` ya agendadas.
- **`apps/accounts/tasks.py`**: `send_invitation_email_task()` refactorizado para usar `send_notification()` con canal `["email"]` y plantilla `notifications/invitation.html`.

### 7.10 Reglas de Despacho de Notificaciones en Reprogramación

Cuando un administrador o barbero reprograma una cita vía `AppointmentRescheduleAPI`:

1. **Al Cliente**: Se envía **email + SMS** al cliente notificando el nuevo horario (`notif_type="reschedule_client"`).
2. **Al Barbero (condicional)**: Si el cambio fue hecho por un **administrador** (rol owner/admin) y no por el propio barbero asignado, se envía **email + SMS** al barbero notificando que su agenda fue modificada (`notif_type="reschedule_barber"`).
3. **Ambas notificaciones** se despachan de forma asíncrona vía `django_q` sin bloquear la respuesta HTTP.
4. Los **recordatorios agendados** (24h/1h) de la cita original se eliminan y se recrean con la nueva fecha/hora.

## 8. Módulo Agenda – Reprogramación de Citas

### 8.1 Endpoint de Reprogramación

**URL**: `POST /app/schedule/api/appointments/<int:pk>/reschedule/`

**Permisos**: Solo administradores de organización (owner/admin) o el barbero asignado originalmente a la cita.

**Payload**:
```json
{
    "new_start_time": "2025-06-15T14:30:00"
}
```

**Flujo**:
1. Validar permisos RBAC → 403 si no autorizado
2. Validar estado de cita (no cancelada, no completada, no no_show) → 409 si inválido
3. Verificar disponibilidad del horario nuevo contra la agenda del barbero → 409 si conflicto
4. `transaction.atomic()`: Actualizar `start_time` y `end_time` de Appointment + sincronizar Intervencion en cascada
5. Cancelar recordatorios agendados previos y recrear con nueva fecha
6. Despachar notificaciones asíncronas al cliente (email+SMS) y al barbero si es admin
7. Retornar `{ "message": "Horario actualizado", "new_start_time": "...", "new_end_time": "..." }`

**Códigos de respuesta**:
| Código | Significado |
|---|---|
| 200 | Horario actualizado exitosamente |
| 400 | Falta `new_start_time` o formato inválido |
| 403 | Usuario sin permisos (no es admin ni barbero asignado) |
| 404 | Cita no encontrada |
| 409 | Horario no disponible o cita en estado inválido |

### 8.2 Endpoint de Horarios Disponibles para Reprogramación

**URL**: `GET /app/schedule/api/appointments/<int:pk>/reschedule-slots/`

**Parámetros**:
| Parámetro | Requerido | Descripción |
|---|---|---|
| `date` | No | Fecha en formato `YYYY-MM-DD`. Si se omite, retorna solo `available_dates` y metadatos. |

**Respuesta sin `date`** (inicialización del picker):
```json
{
    "available_dates": ["2025-06-15", "2025-06-16", "..."],
    "intervalo_apertura_dias": 15,
    "total_duration": 60
}
```

**Respuesta con `date`** (slots para una fecha):
```json
{
    "slots": [
        {"start": "2025-06-15T09:00:00-03:00", "end": "2025-06-15T10:00:00-03:00"},
        "..."
    ],
    "available_dates": ["2025-06-15", "..."],
    "intervalo_apertura_dias": 15,
    "total_duration": 60
}
```

Las `available_dates` se calculan usando `get_available_dates()` que verifica únicamente horarios de trabajo (WorkSchedule) y días cerrados de la barbería, sin computar disponibilidad completa de slots por cada día.

### 8.3 Componente de UI – Modal de Detalle de Cita

El botón **"Modificar horario"** aparece en el modal de detalle únicamente para citas en estado `pending`. Al activarse:

1. Se consulta `RescheduleSlotsAPI` sin `date` para obtener `available_dates` y `intervalo_apertura_dias`
2. Se inicializa **Flatpickr** para fecha con `minDate: today`, `maxDate: today + intervalo_apertura_dias`, y `disable` función que deshabilita fechas fuera de `available_dates`
3. Al seleccionar una fecha, se llama `loadRescheduleSlots(date)` que consulta `RescheduleSlotsAPI?date=YYYY-MM-DD`
4. Los slots se renderizan como **chips horizontales scrolleables** con `snap-x snap-mandatory` / `snap-center`, paleta oscura, y estado seleccionado con `#ff2301`
5. Al seleccionar un slot, se establece el valor del campo oculto `reschedule-time` y se habilita el botón "Confirmar cambio"
6. POST al endpoint de reprogramación con `new_start_time`
7. Modal de confirmación: **"Horario actualizado. Se notificará a los implicados automáticamente."**

### 8.4 Intervalo de Apertura (`intervalo_apertura_dias`)

Campo añadido a `BarberProfile` (`apps/accounts/models.py`):
- **Campo**: `intervalo_apertura_dias` (PositiveIntegerField, default=15)
- **Propósito**: Limita cuántos días hacia adelante puede un cliente agendar o reprogramar citas con un barbero específico
- **Configuración**: Se edita desde el modal de horarios del barbero junto con los WorkSchedules
- **Validación backend**: `HorarioSaveAPI` guarda este valor y valida que los horarios de trabajo (`start_time`/`end_time`) estén dentro del rango operativo de las sucursales asignadas al barbero
- **Uso en calendario**: `CalendarView` inyecta `barbers_data` JSON (id, nombre, intervalo, buffer) en el contexto para uso frontend

### 8.5 Validación de Horarios de Trabajo contra Horarios de Sucursal

`_get_branch_hours()` en `apps/accounts/views_barberos.py` calcula el rango horario más restrictivo entre todas las sucursales asignadas a un barbero:
- **open**: Mínimo `open_hour` entre todas las sucursales
- **close**: Máximo `close_hour` entre todas las sucursales

`HorarioSaveAPI` valida que `start_time >= branch_open` y `end_time <= branch_close`, retornando 400 con mensaje descriptivo si un horario de trabajo excede el rango operativo.

### 8.6 Datos Inyectados en Contexto del Calendario

`CalendarView` inyecta `barbers_data` como lista JSON en el contexto:
```json
[
    {"id": 1, "name": "Carlos", "intervalo_apertura_dias": 15, "buffer_minutes": 10},
    "..."
]
```

Este dato se serializa con `json_script` y se carga en `window._barbersData` para uso en el frontend, evitando llamadas adicionales al backend.

### 8.7 Eventos del Calendario con ID de Barbero

El campo `barber_id` now se incluye en `extendedProps` de cada evento del calendario (API `/api/events/`), permitiendo al frontend identificar al barbero de cada cita sin consultas adicionales.

### 8.8 AvailableSlotsAPI con intervalo

El endpoint `GET /app/schedule/api/slots/` ahora retorna también `intervalo_apertura_dias` del barbero:
```json
{
    "slots": [...],
    "intervalo_apertura_dias": 15
}
```
