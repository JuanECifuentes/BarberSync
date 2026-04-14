# BarberSync - Documentación Técnica del Proyecto

## 1. Visión General y Objetivo
**BarberSync** es una plataforma SaaS (Software as a Service) multi-tenant diseñada para la gestión integral de barberías. Su objetivo principal es resolver la complejidad administrativa de los negocios de barbería que operan con una o múltiples sucursales bajo una misma organización. 

**Problemas que soluciona:**
- **Gestión Multi-Sucursal:** Permite administrar múltiples barberías desde una sola cuenta organizativa, facilitando la visión global del negocio.
- **CRM Centralizado:** Unifica la base de datos de clientes a nivel de organización, evitando duplicados y mejorando la experiencia del cliente en cualquier sucursal.
- **Gestión de Agendamiento Avanzada:** Administra horarios de trabajo, especialidades de los barberos, excepciones (vacaciones, recesos) y citas, con cálculos dinámicos de duración y precio.
- **Control Financiero y de Inventario:** Integra la facturación (servicios y productos) y un control estricto de inventario mediante un registro inmutable de movimientos de stock.
- **Recordatorios Automáticos:** Reduce el ausentismo (no-shows) mediante un sistema de notificaciones asíncronas para clientes y barberos.

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
