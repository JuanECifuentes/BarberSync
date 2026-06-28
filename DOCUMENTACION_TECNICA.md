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
- **Tooltips unificados – Regla obligatoria:** Todo tooltip de ayuda en la interfaz debe utilizar la estructura estandarizada `.tooltip-help` con el icono SVG estándar y seguir las directrices de alineación posicional para evitar recortes por `overflow` en el sidebar o barra de navegación.
  - **Estructura HTML Estándar:**
    ```html
    <div class="tooltip-help [variantes_de_alineacion]">
        <svg class="w-3.5 h-3.5 text-neutral-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
            <circle cx="12" cy="12" r="10" stroke-width="2"/>
        </svg>
        <span class="tooltip-text [wide]">Texto descriptivo del tooltip.</span>
    </div>
    ```
  - **Variantes de Posicionamiento (definidas en global.css):**
    - Sin variante (por defecto): Se muestra centrado por encima del icono.
    - `.bottom-aligned`: Se muestra por debajo del icono. Obligatorio para elementos en el tope de la pantalla (como filtros de cabeceras pegajosas) para evitar recortarse con la barra de navegación superior.
    - `.left-aligned`: Alinea el globo a la izquierda del icono (el texto se despliega hacia la derecha). Obligatorio para tooltips cercanos al sidebar o al borde izquierdo del viewport.
    - `.right-aligned`: Alinea el globo a la derecha del icono (el texto se despliega hacia la izquierda). Obligatorio para tooltips cercanos al borde derecho del viewport.
    - Se pueden combinar de forma aditiva: ej. `.bottom-aligned.left-aligned`.
  - **Gestión de Stacking Context:** El contenedor de tooltip `.tooltip-help` cambia a `z-index: 50` al recibir `:hover` (elevando su contexto por encima de cabeceras y paneles), y el globo interno `.tooltip-text` utiliza un `z-index: 9999` para asegurar el dibujado sobre librerías de terceros (gráficos, tablas).
- **Componente Loading Overlay (Carga Estándar) – Regla obligatoria:** Para mostrar estados de carga sobre KPIs, gráficos u otros paneles relativos, se debe incluir el componente reutilizable `loading_overlay.html`.
  - **Uso en Django Templates:**
    ```html
    <div class="relative min-h-[200px]">
        {% include "components/loading_overlay.html" with loading_text="Cargando datos..." %}
        <!-- Contenido que se cubre al cargar -->
    </div>
    ```
  - **Parámetros configurables:**
    - `loading_var`: La variable de estado de Alpine.js que controla la visibilidad (por defecto `"loading"`).
    - `loading_text`: El texto descriptivo mostrado debajo del spinner (por defecto `"Cargando..."`).

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
| `interval_count` | `PositiveIntegerField (default=1)` | **Cantidad de intervalos por ciclo.** Valores usados: `1` (mensual), `3` (trimestral), `12` (anual). |
| `provider` | `CharField(20)` | `stripe` o `wompi` |
| `provider_price_id` | `CharField(100)` | ID del precio en Stripe (`price_1…`), o identificador lógico para Wompi |
| `is_current` | `BooleanField` | Solo un price `True` por combinación (plan, provider, currency, interval, interval_count) |
| `valid_from` / `valid_to` | `DateTimeField` | Periodo de vigencia del precio |

**Regla CRÍTICA de `amount_minor`:**
- USD: `$19.00/mes` → `amount_minor = 1900` (centavos)
- COP: `$29.900/mes` → `amount_minor = 2990000` (centavos: pesos × 100)
- Wompi recibe este valor directamente como `amount_in_cents` sin multiplicación adicional.

**Regla CRÍTICA de versionado:** Para cambiar un precio, **nunca** modificar el registro existente. Siempre:
1. `PlanPrice.objects.filter(...).update(is_current=False, valid_to=now())`
2. Crear un nuevo `PlanPrice` con el nuevo monto y `is_current=True`.

**Matriz de intervalos soportados (`interval` × `interval_count`):**
| `interval` | `interval_count` | Significado | Implementación |
|---|---|---|---|
| `month` | `1` | Mensual | Stripe nativo – Wompi pago único 1 mes |
| `month` | `3` | Trimestral | Stripe nativo – Wompi pago único por 3 meses por adelantado |
| `month` | `12` | Anual | Stripe nativo – Wompi pago único por 12 meses por adelantado |

Helper `PlanPrice.months_in_cycle` retorna el total de meses del ciclo (12 para year×1, 3 para month×3, etc.), usado por Wompi para calcular `current_period_end`.

**UniqueConstraint ampliada:** `unique_active_price_per_plan_provider_interval` ahora incluye `interval_count`, garantizando que solo exista **un** `PlanPrice` vigente por combinación `(plan, provider, currency, interval, interval_count)`.

#### `Subscription` (`billing_subscription`)
| Campo | Tipo | Descripción |
|---|---|---|
| `organization` | `FK → Organization` | Organización suscrita (nullable durante registro) |
| `user` | `FK → User` | Usuario que pagó (nullable si se asocia por organization) |
| `plan` | `FK → Plan` | Plan contratado |
| `plan_price` | `FK → PlanPrice` | Snapshot del precio al momento de la suscripción |
| `provider` | `CharField(20)` | Pasarela que procesó el pago |
| `provider_subscription_id` | `CharField(100)` | ID de suscripción en Stripe, o reference en Wompi, o `session_id` mientras `status=pending` |
| `provider_customer_id` | `CharField(100)` | ID de customer en Stripe (vacío en Wompi) |
| `wompi_transaction_id` | `CharField(100)` | ID de transacción en Wompi (vacío en Stripe) |
| `status` | `CharField(15)` | `pending`, `trialing`, `active`, `past_due`, `canceled`, `expired` |
| `trial_end` | `DateTimeField(null)` | Fin del periodo de prueba |
| `current_period_start/end` | `DateTimeField(null)` | Periodo de facturación actual. En **Wompi** se calcula sumando `plan_price.months_in_cycle` desde el instante del pago (`current_period_end = now + months_in_cycle months`). En **Stripe** se sincroniza desde `data.object.current_period_start/end` (timestamps unix). |
| `canceled_at` | `DateTimeField(null)` | Marca temporal de cancelación |

**Estados:**
- `pending` — checkout iniciado, webhook aún no recibido (creado en `CheckoutView`, sirve de ancla para la reconciliación).
- `trialing` / `active` / `past_due` — activos a los fines del middleware.
- `canceled` / `expired` — históricos.

**Restricción única:** Solo puede existir una suscripción `trialing`/`active`/`past_due` por organización (`one_active_subscription_per_org`). La excepción `pending` permite arrastrar el checkout sin caer en el bloque unique.

**Helper `Subscription.compute_period_end(start=None)`:** retorna `start + relativedelta(months=plan_price.months_in_cycle)`. Usado por Wompi y por la reconciliación.

**Helper `Subscription.is_active()`:** shortcut para validar estados activos.

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

## 9. Control de Concurrencia, Reconciliación y Caché de Suscripción

Esta sección documenta la **fase 2** del módulo de facturación: prevención de cobros dobles, planes multi-intervalo (1/3/12 meses), reconciliación ante pérdida de webhooks y optimización de middleware con caché distribuida.

### 9.1 Restricción de Compras Duplicadas (Exclusión Mutua)

**Objetivo:** impedir que un usuario con membresía activa vuelva a ejecutar checkout en Stripe o Wompi.

**Flujo (`apps/billing/views.py::CheckoutView`):**

1. Tras resolver `(provider, plan_price, organization)` se consulta el estado cachedo de suscripción:
   ```python
   if _has_active_subscription(request.user, organization):
       return JsonResponse({"error": "Ya tienes una suscripción activa.",
                            "code": "ACTIVE_SUBSCRIPTION_EXISTS"}, status=400)
   ```
   Para navegadores no-AJAX, redirect a `/?already_subscribed=true#planes`.

2. **Bloque transaccional SQL** con `transaction.atomic()` y validación de "ya existe activa" vía `Subscription.objects.filter(...).exclude(status__in=[canceled, expired, pending]).first()`. Si existe, se bloquea también aquí (concurrencia a nivel de BD).

3. Se invoca al proveedor (`StripeProvider.create_checkout_session` o `WompiProvider.create_checkout_session`) **únicamente** tras pasar los dos bloqueos.

4. Tras la creación exitosa del checkout externo, se crea un `Subscription(status=PENDING)` con `provider_subscription_id = reference|session_id`. Este registro es la **ancla** para la reconciliación síncrona (ver §9.3).

5. El resultado se invalida en caché (`invalidate_subscription(pending)`) para reflejar el cambio de estado.

**Endpoint AJAX de validación previa:**
- `GET /billing/subscription-status/` → `{"has_active_subscription": bool, "organization_id": int|null}`. Usado por la landing para deshabilitar botones de compra.
- `GET /billing/plans/` → matriz JSON pública con todos los `PlanPrice` vigentes, agrupada por `plan_code + provider + interval_count`. La landing puede usarla para pintar la matriz de precios sin enviar montos por formulario.

**Códigos HTTP relevantes:**

| Código | Significado |
|---|---|
| 200 | (planes, subscription-status) OK |
| 302 | (checkout no-AJAX) ya tiene suscripción → redirect `/?already_subscribed=true#planes` |
| 400 | (checkout AJAX) ya tiene suscripción o falta `plan_code` |
| 502 | (checkout AJAX) la pasarela externa rechazó la creación del checkout |

### 9.2 Planes Multi-Intervalo (1, 3 y 12 meses)

**Cambios en modelos (`apps/billing/models.py`):**
- `PlanPrice.interval_count` (PositiveIntegerField, default=1) — cantidad de intervalos por ciclo.
- `PlanPrice.INTERVAL_COUNT_MONTHS` — choices `[1, 3, 12]` para uso en formularios.
- `PlanPrice.months_in_cycle` (property) — calcula los meses totales del ciclo:
  - `month × 1 → 1`, `month × 3 → 3`, `month × 12 → 12`, `year × 1 → 12`.
- `UniqueConstraint unique_active_price_per_plan_provider_interval` ahora incluye `interval_count`.

**Migraciones:**
- `0004_subscription_pending_and_interval_count.py` — añade `interval_count`, estado `pending` en `Subscription`, índices y nueva constraint.
- `0005_plan_prices_multi_interval.py` — **data migration** que genera los precios trimestral y anual a partir del mensual vigente, aplicando:
  - 3 meses → **5% dcto** sobre `mes × 3`.
  - 12 meses → **15% dcto** sobre `mes × 12`.
  - COP se redondea a múltiplos de $1.000; USD a centavos.
  - `provider_price_id` Stripe trimestral/anual queda con placeholder `price_replace_me_<plan>_<currency>_<quarter|year>` que el admin debe sustituir por los IDs reales creados en el Dashboard de Stripe.

**Lógica por pasarela:**

| Pasarela | 1 mes | 3 meses | 12 meses |
|---|---|---|---|
| **Stripe** | `Subscription` nativa con `interval=month, interval_count=1`. | `Subscription` nativa con `interval=month, interval_count=3`. | `Subscription` nativa con `interval=month, interval_count=12` (Stripe soporta hasta 12 para `month`). El `subscription_data.metadata` lleva `interval` e `interval_count` para auditoría. |
| **Wompi** | Pago único por 1 mes. | Pago único por **3 meses por adelantado**. | Pago único por **12 meses por adelantado**. |

**Cálculo de `current_period_end` en Wompi:**
```python
now = timezone.now()
period_end = now + relativedelta(months=plan_price.months_in_cycle)
```
Tras confirmación del webhook (`transaction.updated` con `status in ("APPROVED", "PAYED")`) se actualiza el `Subscription` PENDING (o se crea inexistente) con `current_period_start=now`, `current_period_end=period_end`. El acceso del tenant permanece garantizado hasta ese `expires_at`.

**Cálculo en Stripe:**
- En `checkout.session.completed`: si la pasarela envía `data.object.current_period_start/end` se sincronizan desde los timestamps Unix.
- En `customer.subscription.updated`: se sincronizan en cada renovación.

**Matriz de precios posterior a la migración 0005 (ejemplo):**

```
INDEPENDIENTE  stripe  USD month×1   1900       (price_1... nativo)
INDEPENDIENTE  stripe  USD month×3   5415       (placeholder)
INDEPENDIENTE  stripe  USD month×12  19380      (placeholder)
INDEPENDIENTE  wompi   COP month×1   2990000
INDEPENDIENTE  wompi   COP month×3   8522000
INDEPENDIENTE  wompi   COP month×12  30498000
LOCAL          ...     ...           ...
CADENA         ...     ...           ...
```

### 9.3 Reconciliación Ante Fallos de Webhooks (Pulling)

**Objetivo:** si un webhook de Stripe o Wompi no llega (red caída, configure mal el endpoint, caída de la pasarela, etc.), el sistema observa la pérdida y sincroniza la suscripción consultando **directamente** la API externa.

**Mecanismo de resiliencia pasiva (`apps/billing/tasks.py`):**

```
reconcile_subscriptions(max_age_seconds=300)
├── Itera Subscription.objects.filter(status=pending, created_at__lte=cutoff)
├── Para cada sub, llama al reconciler de su provider:
│   ├── Stripe: provider.fetch_customer_active_subscription(customer_id)
│   │     → GET /v1/subscriptions?customer=...&status=active
│   │     → si status=="active", activa la sub con periodos de Stripe.
│   └── Wompi : provider.fetch_transaction_by_reference(reference)
│         → GET /v1/transactions?reference=...
│         → si status in ("APPROVED","PAYED"), activa con period_end = now + months_in_cycle.
├── _activate_subscription_from_remote():
│   ├── transaction.atomic() con select_for_update (anti race con webhook)
│   ├── Si la sub ya está activa (webhook llegó entre iteración y commit) → no-op.
│   ├── Cancela otras suscripciones activas del mismo tenant (one_active_subscription_per_org).
│   ├── UPDATE Subscription(status=active, ..., current_period_start, current_period_end).
│   └── Invoice.objects.update_or_create(provider_invoice_id=...) marcando raw_webhook_data={"reconciled": True}.
└── Devuelve summary {checked, activated, still_pending, errors}.
```

**Invocación:**
- Manual (síncrona): `python manage.py reconcile_subscriptions --min-age 300`
- Asíncrona en django_q: `python manage.py reconcile_subscriptions --async` (encola la tarea `apps.billing.tasks.reconcile_subscriptions`).
- Programada: añadir un cron cada N minutos:
  ```cron
  */10 * * * * cd /app && venv/bin/python manage.py reconcile_subscriptions --async
  ```

**Variables de entorno nuevas:**

| Variable | Default | Descripción |
|---|---|---|
| `BILLING_RECONCILE_MIN_AGE_SECONDS` | `300` | Antigüedad mínima (segundos) de una suscripción `pending` para ser reconciliada. Da margen al webhook normal. |

**Métodos añadidos a los proveedores (`apps/billing/providers.py`):**
- `StripeProvider.fetch_customer_active_subscription(customer_id) → dict` — usa `stripe.Subscription.list(customer=..., status=active, limit=5)` y retorna la primera suscripción activa con `subscription_id`, `status`, `current_period_start/end`, `customer`, `metadata`.
- `WompiProvider.fetch_transaction_by_reference(reference) → dict` — `GET {api_url}/transactions?reference=...`, retorna `transaction_id`, `status`, `reference`, `amount_in_cents`, `currency`, `metadata`.

**Comportamiento ante duplicidad:** si tanto el webhook como la reconciliación llegan casi simultáneamente, el segundo ejecuta su comprobación dentro de `transaction.atomic()` + `select_for_update()` y aborta si `status` ya es `active`. Esto garantiza la idempotencia.

### 9.4 Middleware de Acceso Optimizado con Caché

**Problema original:** `apps/billing/middleware.py::SubscriptionAccessMiddleware` ejecutaba dos consultas SQL por cada página interna request.session, golpeando PostgreSQL con cada navegación.

**Solución (`apps/billing/cache_utils.py` + `apps.billing.signals`):**

- Funciones públicas:
  - `get_user_subscription_status(user)` → bool cacheado por usuario.
  - `get_org_subscription_status(org)` → bool cacheado por organización.
  - `invalidate_user(user_id)`, `invalidate_org(org_id)`, `invalidate_subscription(sub)`.
- Claves usadas:
  - `barbersync:sub:active:user:{user_id}`
  - `barbersync:sub:active:org:{organization_id}`
- **TTL dinámico:** `seconds_until_end_of_day()` calcula los segundos hasta `23:59:59` del día en curso (max 86_400 s, min 60 s). La caché se reinicia automáticamente al cambiar de día calendario, garantizando que cualquier activación / cancelación impacte en menos de 24 h incluso si las señales de invalidación fallan.
- **Invalidación automática:** señales `post_save` y `post_delete` de `Subscription` (`apps/billing/signals.py`, cargadas desde `BillingConfig.ready()`) borran la clave correspondiente. Garantiza que activaciones por webhook y cancelaciones administrativas afecten al middleware en la próxima petición.

**Backends de caché (`barbersync/settings/base.py`):**
| Entorno | Variable | Backend |
|---|---|---|
| `LOCAL=True` (dev) | — | `django.core.cache.backends.locmem.LocMemCache` (`location=barbersync-local-mem`) |
| `LOCAL=False` (prod) | `REDIS_URL` | `django_redis.cache.RedisCache` (clave `REDIS_URL` obligatoria) |

**Variable de entorno nueva:**

```bash
# Cache distribuida (solo se usa si LOCAL=False)
REDIS_URL=redis://127.0.0.1:6379/1
```

**Pseudocódigo del middleware optimizado:**
```python
if get_user_subscription_status(request.user):
    return self.get_response(request)
org = getattr(request, "organization", None)
if org is not None and get_org_subscription_status(org):
    return self.get_response(request)
return redirect("/?expired=true#planes")
```

### 9.5 Endpoints Afectados / Resumen

| Endpoint | Método | Cambio |
|---|---|---|
| `/billing/checkout/` | POST | Validación pre-compra; json 400 si ya activa; crea `Subscription(pending)` |
| `/billing/success/` | GET | sin cambios |
| `/billing/cancel/` | GET | sin cambios |
| `/billing/subscription-status/` | GET (LoginRequiredMixin) | **NUEVO** – validación previa AJAX |
| `/billing/plans/` | GET (público) | **NUEVO** – matriz de precios 1/3/12 meses |
| `/billing/webhook/stripe/` | POST | Activación reutiliza `Subscription(pending)` por `subscription_id`; sincroniza `current_period_start/end` |
| `/billing/webhook/wompi/` | POST | Calcula `current_period_end = now + plan_price.months_in_cycle`; reutiliza PENDING; `Invoice.update_or_create` |

**Comando de gestión nuevo:**
- `python manage.py reconcile_subscriptions [--min-age N] [--async]`

**Archivos nuevos / modificados:**
- `apps/billing/models.py` (interval_count, helpers, PENDING status)
- `apps/billing/migrations/0004_subscription_pending_and_interval_count.py` (schema)
- `apps/billing/migrations/0005_plan_prices_multi_interval.py` (data seed)
- `apps/billing/providers.py` (fetch_customer_active_subscription, fetch_transaction_by_reference)
- `apps/billing/views.py` (validación pre-compra, PENDING, expires_at Wompi, novos endpoints)
- `apps/billing/urls.py` (routes de `/billing/subscription-status/` y `/billing/plans/`)
- `apps/billing/cache_utils.py` (NUEVO)
- `apps/billing/signals.py` (NUEVO)
- `apps/billing/middleware.py` (caché + TTL dinámico)
- `apps/billing/tasks.py` (NUEVO – reconciliación)
- `apps/billing/apps.py` (carga `signals`)
- `apps/billing/management/commands/reconcile_subscriptions.py` (NUEVO)
- `barbersync/settings/base.py` (BILLING_RECONCILE_MIN_AGE_SECONDS)
- `.env` y `.env.example` (REDIS_URL, BILLING_RECONCILE_MIN_AGE_SECONDS, blocs de billing)
- `apps/core/views.py` (`plan_prices` anidado por intervalo, `billing_intervals`)
- `templates/landing.html` (toggle Mensual/Trimestral/Anual + inputs ocultos `interval_count`)

### 9.6 Toggle de Intervalo en la Landing Page

La landing ahora expone, además del toggle de proveedor (Wompi/Stripe), un segundo toggle de intervalos con tres botones:

| Botón | `interval_count` | Sufijo mostrado | Badge |
|---|---|---|---|
| Mensual | `1` | `/mes` | — |
| Trimestral | `3` | `/3 meses` | `-5%` |
| Anual | `12` | `/año` | `-15%` |

**Estructura JSON inyectada por `LandingPageView` (`apps/core/views.py`):**
```json
{
  "INDEPENDIENTE": {
    "stripe": {
      "1":  {"amount_minor": 1900,  "currency": "USD", "months_in_cycle": 1},
      "3":  {"amount_minor": 5415,  "currency": "USD", "months_in_cycle": 3},
      "12": {"amount_minor": 19380, "currency": "USD", "months_in_cycle": 12}
    },
    "wompi": {
      "1":  {"amount_minor": 2990000,  "currency": "COP", "months_in_cycle": 1},
      "3":  {"amount_minor": 8522000,  "currency": "COP", "months_in_cycle": 3},
      "12": {"amount_minor": 30498000, "currency": "COP", "months_in_cycle": 12}
    }
  },
  "LOCAL":    { "...": "..." },
  "CADENA":    { "...": "..." }
}
```

**Comportamiento JS:**
- `selectProvider(provider)` y `selectInterval(months)` actualizan variables de estado `currentProvider` / `currentInterval`, reescriben los inputs hidden `chosen_provider` e `interval_count` de los tres formularios, y disparan `renderPrices()`.
- `renderPrices()` recalcula cada `span.plan-price-display` con `formatPrice(amount_minor, currency)` y actualiza el sufijo `span.plan-price-suffix` entre `/mes`, `/3 meses` y `/año`.
- Si la combinación `(provider, interval)` no existe en BD, hace fallback al precio mensual del mismo provider.

### 9.7 Guía Paso a Paso — Crear Productos y Precios en Stripe

Stripe maneja dos entidades: el **Product** (el concepto: "Barbero Independiente") y los **Prices** (cada variación de cobro: mensual, trimestral, anual). Necesitas **3 Products** y **9 Prices** (3 por plan × los 3 intervalos).

> ⚠️ **Importante:** esta guía es para la instancia en la que vas a probar/cobrar. Usa el **modo Test** durante desarrollo y el **modo Live** al salir a producción. Los `price_1...` que obtengas son distintos entre test y live — actualiza `provider_price_id` en la BD con los valores del entorno correcto.

#### Requisitos previos
- Cuenta Stripe verificada (es suficiente con modo Test para desarrollo).
- Tu URL de webhook ya registrada en **Developers → Webhooks → Add endpoint** apuntando a `https://<tu-dominio>/billing/webhook/stripe/` con los eventos `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted` (ver §6.1 y §6.6).
- `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` y `STRIPE_WEBHOOK_SECRET` ya configurados en `.env`.

#### Pasos para cada plan

Repite el siguiente flujo para los tres planes: **INDEPENDIENTE**, **LOCAL** y **CADENA**.

**1. Crear el Product**
- Dashboard Stripe → **Productos** (Catálogo → Productos en el menú lateral).
- Click **+ Añadir producto**.
  - **Nombre:** `Barbero Independiente` (o `Barbería Local` / `Cadenas Multi-sucursal`).
  - **Descripción:** copia la `description` de tu `Plan` en la BD.
  - **Imágenes / metadata / declaración de impuestos:** opcional. BarberSync no usa IVA diferenciado; deja default.
- Click **Guardar**. Anota el `prod_...` que aparece en la URL (no se usa directamente pero sirve de referencia).

**2. Crear los 3 precios recurrentes (Monthly / Quarterly / Annual)**

Dentro del Product recién creado → pestaña **Precios** → **+ Añadir precio**:

| Precio # | Tipo de precio | Importe | Moneda | Periodo | Resultado esperado en BD (`provider_price_id`) |
|---|---|---|---|---|---|
| 1 | **Estándar / Recurrente** | USD equivalente a `amount_minor/100` | `USD` | **Cada 1 mes** | `price_1… mensual` |
| 2 | **Estándar / Recurrente** | USD trimestral (≈ mensual × 3 × 0.95) | `USD` | **Cada 3 meses** | `price_1… trimestral` |
| 3 | **Estándar / Recurrente** | USD anual (≈ mensual × 12 × 0.85) | `USD` | **Cada 12 meses** | `price_1… anual` |

Repite lo mismo en moneda **COP** si también vas a publicar tus precios Stripe en pesos colombianos (la mayoría de comercios colombianos usa Wompi para COP y Stripe sólo para USD, pero Stripe sí soporta COP recurrente).

> 💡 **Atajo Stripe CLI** para crear los precios vía script (opcional, recomendado para entornos nuevos):
> ```bash
> # Variables de ejemplo para INDEPENDIENTE en USD
> MONTHLY=$(stripe prices create \
>   -d product-data.name="Barbero Independiente" \
>   -d unit-amount=1900 \
>   -d currency=usd \
>   -d type=recurring \
>   -d recurring.interval=month \
>   --output json | jq -r .id)
> QUARTERLY=$(stripe prices create \
>   -d product-data.name="Barbero Independiente" \
>   -d unit-amount=5415 \
>   -d currency=usd \
>   -d type=recurring \
>   -d recurring.interval=month \
>   -d recurring.interval_count=3 \
>   --output json | jq -r .id)
> ANNUAL=$(stripe prices create \
>   -d product-data.name="Barbero Independiente" \
>   -d unit-amount=19380 \
>   -d currency=usd \
>   -d type=recurring \
>   -d recurring.interval=month \
>   -d recurring.interval_count=12 \
>   --output json | jq -r .id)
> echo "INDEPENDIENTE USD → $MONTHLY  $QUARTERLY  $ANNUAL"
> ```

**3. Actualizar la base de datos con los IDs `price_1...`**

Conecta al shell de Django y reemplaza los placeholders dejados por la migración `0005`:

```python
# venv\Scripts\python.exe manage.py shell
from django.utils import timezone
from apps.billing.models import Plan, PlanPrice

# —— INDEPENDIENTE (USD / stripe) ——
plan = Plan.objects.get(code="INDEPENDIENTE")
PlanPrice.objects.filter(
    plan=plan, provider="stripe", currency="USD",
    interval_count=3, is_current=True,
).update(provider_price_id="price_1XXXX_stripe_independiente_usd_quarter")

PlanPrice.objects.filter(
    plan=plan, provider="stripe", currency="USD",
    interval_count=12, is_current=True,
).update(provider_price_id="price_1XXXX_stripe_independiente_usd_year")

# —— LOCAL (USD / stripe) ——
plan = Plan.objects.get(code="LOCAL")
PlanPrice.objects.filter(
    plan=plan, provider="stripe", currency="USD",
    interval_count=3, is_current=True,
).update(provider_price_id="price_1XXXX_stripe_local_usd_quarter")
PlanPrice.objects.filter(
    plan=plan, provider="stripe", currency="USD",
    interval_count=12, is_current=True,
).update(provider_price_id="price_1XXXX_stripe_local_usd_year")

# —— CADENA (USD / stripe) ——
plan = Plan.objects.get(code="CADENA")
PlanPrice.objects.filter(
    plan=plan, provider="stripe", currency="USD",
    interval_count=3, is_current=True,
).update(provider_price_id="price_1XXXX_stripe_cadena_usd_quarter")
PlanPrice.objects.filter(
    plan=plan, provider="stripe", currency="USD",
    interval_count=12, is_current=True,
).update(provider_price_id="price_1XXXX_stripe_cadena_usd_year")
```

> ✅ El precio mensual ya tiene un `price_1...` real (asignado inicialmente); no hace falta tocarlo.
> ✅ Los precios de Wompi son **pago único por adelantado** (no se crean en Wompi) — sólo el registro en `billing_plan_price` controla el monto y el `months_in_cycle`.

**4. Verificar en la landing**

```bash
venv\Scripts\python.exe manage.py runserver
# Abre http://127.0.0.1:8000/#planes
# Prueba a toggle Mensual → Trimestral → Anual:
#   • Los precios deben cambiar dinámicamente SIN recargar.
#   • El badge "-5%" / "-15%" ya está pintado en HTML.
#   • Al hacer submit en "Registrarse ahora", el formulario POST envía
#     plan_code=LOCAL, chosen_provider=stripe, interval_count=12.
```

**5. Verificar el webhook completo**

Usa tarjetas de prueba de Stripe (ver §6.4):
- `4242 4242 4242 4242` → success.
- Compra plan mensual → llega `checkout.session.completed` → `Subscription(pending)` se promueve a `active`.
- Compra plan anual → igual flujo pero `current_period_end` queda a 12 meses.

**6. Checklist final**

| Item | OK |
|---|---|
| 3 Products creados en Stripe (INDEPENDIENTE / LOCAL / CADENA) | ☐ |
| 9 Prices creados (3×plan × interval 1/3/12) | ☐ |
| `provider_price_id` actualizado en BD para los 6 precios trimestral+anual | ☐ |
| Precios mensuales intactos | ☐ |
| Webhook endpoint registrado con 3 eventos requeridos | ☐ |
| `STRIPE_WEBHOOK_SECRET` en `.env` coincide con el del dashboard | ☐ |
| Landing muestra toggle y precios dinámicos OK | ☐ |
| Pago de prueba con `4242...` activa la suscripción en local (vía ngrok) | ☐ |
| Tarea `python manage.py reconcile_subscriptions --async` no encuentra PENDINGs (vacío normal) | ☐ |

## 10. Módulo de Suscripción en Mi Perfil

Esta sección documenta la interfaz responsiva de la sección "Suscripción" accesible desde `/accounts/profile/`, incluyendo la card de suscripción, el modal de historial de pagos con scroll infinito y el flujo de cancelación de recurrencia para Stripe.

### 10.1 Endpoints del Perfil de Suscripción

**`GET /billing/subscription-detail/`** (`apps/billing/views.py::SubscriptionDetailView`)
- Autenticación: `LoginRequiredMixin`.
- **Anti-IDOR**: cruza rígidamente la organización del usuario autenticado vía `membership.organization`. Si no pertenece a ninguna organización, retorna **403 Forbidden**.
- Respuesta JSON (200) si hay suscripción activa (`trialing`, `active`, `past_due`); 404 si no existe:
  ```json
  {
    "id": 1,
    "plan_name": "Barbero Independiente",
    "plan_code": "INDEPENDIENTE",
    "status": "active",
    "provider": "stripe",
    "is_stripe": true,
    "current_period_start": "2026-06-01T00:00:00Z",
    "current_period_end": "2026-07-01T00:00:00Z",
    "amount_minor": 1900,
    "currency": "USD",
    "interval_count": 1,
    "canceled_at": null,
    "can_cancel": true
  }
  ```
- `can_cancel` es `true` exclusivamente cuando `provider == "stripe"` AND `status in (active, trialing)`.

**`GET /billing/invoice-history/?page=N`** (`apps/billing/views.py::InvoiceHistoryView`)
- Autenticación: `LoginRequiredMixin`.
- **Anti-IDOR**: el queryset se filtra por `organization=org OR user=request.user`. No usa parámetros externos para identificar al tenant.
- **Privacidad por diseño**: cada fila devuelta contiene únicamente `id, paid_at, amount_minor, currency, plan_name, status, provider`. No se expone `raw_webhook_data`, `provider_invoice_id` completo, ni datos sensibles de tarjetas o tokens.
- Paginación: 30 registros por página. `total`, `total_pages`, `has_next` para el scroll infinito.

**`POST /billing/cancel-subscription/`** (`apps/billing/views.py::CancelSubscriptionView`)
- Autenticación: `LoginRequiredMixin`.
- **Anti-IDOR**: la suscripción a cancelar se obtiene filtrando por `organization=org + status__in=ACTIVE_STATUSES`.
- Solo aplicable a suscripciones Stripe. Responde 400 si el proveedor no es `stripe`.
- Invoca `StripeProvider.cancel_subscription(sub)` que llama a `stripe.Subscription.modify(..., cancel_at_period_end=True)`.
- Aplica **Borrado Lógico** local: `sub.status = "canceled"`, `sub.canceled_at = now()`. No borra el registro.
- Invalida la caché de suscripción (`invalidate_subscription(sub)`) para que se refleje en el middleware.

### 10.2 Card de Suscripción (UI)

Ubicada en `templates/accounts/profile.html` entre el formulario de perfil y el grid de Google/Roles. Solo se renderiza si `active_subscription` está presente en el contexto de la vista (`ProfileView.get_context_data`).

**Elementos:**
- Badge de estado (`Activa` / `Prueba` / `Pago pendiente`) con colores semánticos (verde, azul, amarillo).
- Nombre del plan adquirido (`active_subscription.plan.name`) y proveedor (`stripe` / `wompi` formato title).
- Dos tarjetas de periodo: **Inicio del ciclo actual** y **Vencimiento** (ambas desde `current_period_start` / `current_period_end`).
- Botón **Historial de Pagos** (siempre visible si hay suscripción activa).
- Botón **Cancelar renovación** (solo visible si `provider == "stripe"` AND `status in (active, trialing)`).

**Contexto inyectado por `ProfileView`** (`apps/accounts/views.py`):
```python
from apps.billing.models import Subscription
from apps.billing.cache_utils import get_org_subscription_status

active_sub = Subscription.objects.filter(
    organization=org, status__in=Subscription.ACTIVE_STATUSES,
).select_related("plan", "plan_price").order_by("-created_at").first()
context["active_subscription"] = active_sub
context["has_active_subscription"] = get_org_subscription_status(org) if org else False
```

### 10.3 Modal de Historial de Pagos — Scroll Infinito

**Estructura (HTML + CSS):**
- Modal flotante con backdrop oscuro (`bg-black/60 backdrop-blur-sm`).
- Panel `bg-neutral-900`, `max-h-[80vh]`, área de scroll interno `overflow-y-auto`.
- Diseño mobile-first: `rounded-t-2xl` en móviles, `sm:rounded-2xl` en desktop.

**Comportamiento JS (Vanilla):**
```javascript
// Al hacer scroll cerca del final (40px del fondo):
invoiceScroll.addEventListener('scroll', function() {
    if (scrollTop + clientHeight >= scrollHeight - 40) {
        loadInvoicePage();  // Fetch GET /billing/invoice-history/?page=N
    }
});
```
- Estado global: `invoicePage`, `invoiceHasNext`, `invoiceLoadingFlag` (previene cargas concurrentes).
- Al abrir: resetea lista y carga la primera página.
- Al cerrar: oculta modal y limpia scroll.
- Cada fila renderizada con `document.createElement('div')` — no innerHTML concat (previene XSS con `escapeHtml()` para valores dinámicos).
- Formateo de moneda: USD con 2 decimales, COP con locale `es-CO`.

**Estados visuales:**
| Estado | Elemento visible |
|---|---|
| Cargando | Spinner animado (`animate-spin`) + "Cargando..." |
| Vacío (página 1 sin resultados) | Icono documento + "Sin facturas registradas." |
| Fin del listado | "— Fin del historial —" |
| Error de red | Toast "Error al cargar el historial." |

### 10.4 Modal de Confirmación de Cancelación

**UX anti-errores:** al pulsar "Cancelar renovación" no se ejecuta la acción inmediatamente. Se abre un modal intermedio que:

1. **Informa la fecha exacta de acceso residual** (extraída de `current_period_end` renderizada en la card).
2. **Recalca que conservará acceso hasta esa fecha** (texto: "Conservarás acceso hasta el final del período pagado. No se realizarán más cobros automáticos.").
3. **Requiere confirmación explícita** con dos botones: "Volver" (dismiss) y "Sí, cancelar renovación" (rojo).

Al confirmar:
- `fetch POST /billing/cancel-subscription/` con token CSRF y `Content-Type: application/json`.
- Si éxito: toast verde + recarga de la página en 2 segundos (para reflejar `status="canceled"`).
- Si error: toast rojo con el mensaje del backend, botón se rehabilita.
- Tecla Escape cierra cualquiera de los dos modales.

### 10.5 Endpoints Afectados / Resumen del Módulo

| Endpoint | Método | Auth | Rol |
|---|---|---|---|
| `/accounts/profile/` | GET | `LoginRequiredMixin` | Renderiza card de suscripción (contexto inyectado) |
| `/billing/subscription-detail/` | GET | `LoginRequiredMixin` | JSON detalle suscripción activa |
| `/billing/invoice-history/` | GET | `LoginRequiredMixin` | Historial paginado 30×30 (scroll infinito) |
| `/billing/cancel-subscription/` | POST | `LoginRequiredMixin` | Cancela recurrencia Stripe + borrado lógico |

**Archivos modificados / nuevos:**
- `apps/billing/views.py` — clases `SubscriptionDetailView`, `InvoiceHistoryView`, `CancelSubscriptionView`.
- `apps/billing/urls.py` — rutas `subscription-detail/`, `invoice-history/`, `cancel-subscription/`.
- `apps/accounts/views.py` — `ProfileView.get_context_data` inyecta `active_subscription` + `has_active_subscription`.
- `templates/accounts/profile.html` — card de suscripción + modales de historial/cancelación + JS vanilla (scroll infinito + cancelación).
- `DOCUMENTACION_TECNICA.md` — sección 10 completa.
