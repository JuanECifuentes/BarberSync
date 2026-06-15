# Manual Operativo: Configuración e Integración de AWS SES en BarberSync

Este manual detalla los pasos técnicos y operativos requeridos por un Administrador de Sistemas o DevOps para configurar el servicio de correos **AWS SES (Simple Email Service)** e integrarlo con el backend Django de **BarberSync**.

---

## Paso 1: Verificación de Identidad en AWS SES

Para que AWS SES pueda enviar correos en nombre de tu organización, debes verificar la identidad (dominio o direcciones de correo individuales) desde donde saldrán los correos.

### 1.1 Ingresar a la consola de AWS SES
1. Inicia sesión en la **Consola de Administración de AWS**.
2. En la barra de búsqueda superior, escribe **Simple Email Service** o **SES** y selecciona el servicio.
3. Asegúrate de estar en la región más óptima para tu operación. Para Colombia y Latinoamérica, la región de **US East (N. Virginia) `us-east-1`** es la recomendada debido a su menor costo, baja latencia de red y soporte completo para todas las funcionalidades de SES.

### 1.2 Crear y Verificar la Identidad del Dominio (Recomendado)
Verificar un dominio completo permite enviar correos desde cualquier dirección asociada (ej. `noreply@barbersync.app`, `soporte@barbersync.app`) sin tener que verificar cada buzón individualmente.

1. En el panel izquierdo de SES, haz clic en **Verified identities** (Identidades verificadas).
2. Haz clic en el botón naranja **Create identity** (Crear identidad).
3. Selecciona el tipo de identidad: **Domain** (Dominio).
4. Introduce tu dominio (ej. `barbersync.app`).
5. **Configuración de DKIM (DomainKeys Identified Mail):**
   * Deja la opción **Easy DKIM** seleccionada (recomendado).
   * Elige la longitud de clave **RSA_2048_BIT**.
   * Haz clic en **Create identity** en la parte inferior.
6. **Configuración de Registros DNS (DKIM, SPF y MX):**
   * Tras crear la identidad, AWS generará una lista de **registros CNAME** para DKIM.
   * Debes ingresar al proveedor de DNS de tu dominio (ej. Cloudflare, GoDaddy, Namecheap) y añadir los 3 registros CNAME provistos por AWS.
   * **Configuración de SPF (Sender Policy Framework):** Añade o actualiza un registro TXT en tu DNS para autorizar a AWS SES a enviar correos. Si no tienes uno, crea un registro TXT con:
     ```txt
     v=spf1 include:amazonses.com ~all
     ```
     Si ya tienes un registro SPF existente, simplemente agrega `include:amazonses.com` antes del mecanismo final (ej. `v=spf1 include:_spf.google.com include:amazonses.com ~all`).
7. Espera unos minutos (puede tardar hasta 48 horas, aunque usualmente toma menos de 1 hora) a que el estado cambie a **Verified** (Verificado) en la consola de AWS.

### 1.3 Alternativa: Verificar un Correo Electrónico Único (Pruebas)
Si estás en etapa de pruebas y no tienes acceso al DNS del dominio:
1. En **Create identity**, selecciona **Email address** (Dirección de correo electrónico).
2. Escribe la dirección exacta (ej. `noreply@barbersync.app`).
3. Haz clic en **Create identity**.
4. AWS enviará un correo de confirmación a ese buzón. Abre el correo y haz clic en el enlace de verificación. El estado cambiará a **Verified**.

---

## Paso 2: Creación del Usuario IAM (Principio de Menor Privilegio)

Por motivos estrictos de seguridad, nunca se deben usar las credenciales de la cuenta raíz de AWS. Crearemos un usuario en **IAM (Identity and Access Management)** dedicado exclusivamente para BarberSync y con permisos limitados.

### 2.1 Crear el Usuario
1. En la consola de AWS, busca y selecciona el servicio **IAM**.
2. En el menú de la izquierda, haz clic en **Users** (Usuarios) y luego en **Create user** (Crear usuario).
3. Configura los detalles del usuario:
   * **User name:** `barbersync-ses-user`
   * Deja desmarcada la opción *Provide user access to the AWS Management Console* (este usuario solo usará acceso programático por API, no necesita interfaz web).
   * Haz clic en **Next** (Siguiente).

### 2.2 Definir la Política de Seguridad de Menor Privilegio
Para garantizar la seguridad en caso de una filtración de credenciales, limitaremos los permisos del usuario para que **únicamente** pueda enviar correos.

1. En la pantalla de **Set permissions** (Establecer permisos), selecciona **Attach policies directly** (Asociar políticas directamente).
2. En lugar de seleccionar la política genérica `AmazonSESFullAccess` (que permite borrar dominios o cambiar configuraciones de la cuenta), crearemos una política personalizada:
   * Haz clic en **Create policy** (se abrirá una nueva pestaña).
   * Selecciona la pestaña **JSON** y pega el siguiente fragmento:

     ```json
     {
         "Version": "2012-10-17",
         "Statement": [
             {
                 "Sid": "VisualEditor0",
                 "Effect": "Allow",
                 "Action": [
                     "ses:SendEmail",
                     "ses:SendRawEmail"
                 ],
                 "Resource": "*"
             }
         ]
     }
     ```
   * Haz clic en **Next**.
   * Asigna un nombre a la política (ej. `BarberSyncSESSendingPolicy`) y una descripción (ej. "Permite únicamente el envío de correos tradicionales y raw mediante AWS SES").
   * Haz clic en **Create policy** en la esquina inferior derecha.
3. Regresa a la pestaña anterior de creación del usuario IAM.
4. Haz clic en el botón de actualización en la lista de políticas, busca `BarberSyncSESSendingPolicy` y marca la casilla de verificación al lado de ella.
5. Haz clic en **Next** y luego en **Create user**.

---

## Paso 3: Extracción e Inyección de Credenciales

### 3.1 Generar las Claves de Acceso (Access Keys)
1. En la lista de usuarios de **IAM**, haz clic sobre el usuario recién creado (`barbersync-ses-user`).
2. Ve a la pestaña **Security credentials** (Credenciales de seguridad).
3. Desplázate hacia abajo hasta la sección **Access keys** (Claves de acceso) y haz clic en **Create access key** (Crear clave de acceso).
4. Selecciona la opción **Application running outside AWS** (Aplicación ejecutándose fuera de AWS) o **Local code** (Código local).
5. Haz clic en **Next**. Puedes omitir la descripción de etiquetas y hacer clic en **Create access key**.
6. **Guardar Credenciales (Punto Crítico):**
   * Verás en pantalla el **Access key ID** y el **Secret access key**.
   
   > [!CAUTION]
   > **ADVERTENCIA CRÍTICA DE SEGURIDAD:**
   > El **Secret Access Key** solo se mostrará una única vez en esta pantalla. Si cierras la ventana o navegas a otra página sin copiarlo, no podrás recuperarlo y tendrás que borrar la clave y crear una nueva.
   > **NUNCA** guardes estas credenciales en el código fuente de tu repositorio (Git).
   
   * Copia ambos valores inmediatamente.

### 3.2 Configurar el Archivo de Entorno `.env`
Abre el archivo `.env` en la raíz del proyecto BarberSync y añade o actualiza las siguientes variables con las credenciales que acabas de generar:

```env
# AWS SES & General Configuration
AWS_ACCESS_KEY_ID=tu_access_key_id_aqui
AWS_SECRET_ACCESS_KEY=tu_secret_access_key_aqui
AWS_SES_REGION_NAME=us-east-1
AWS_SES_REGION_ENDPOINT=email.us-east-1.amazonaws.com
```

---

## Paso 4: Salida del Sandbox de AWS SES

Por defecto, todas las cuentas nuevas de AWS SES se crean en un entorno de pruebas cerrado llamado **Sandbox**.

### 4.1 Limitaciones del Sandbox
Mientras estés en el Sandbox:
* Solo puedes enviar correos a direcciones de email o dominios que hayas verificado explícitamente en el **Paso 1**.
* Tienes un límite máximo de **200 correos al día**.
* Tienes una tasa de envío limitada a **1 correo por segundo**.

### 4.2 Proceso para Solicitar la Salida a Producción
Para poder enviar correos de confirmación y recordatorios de BarberSync a cualquier cliente externo sin restricciones, debes solicitar a AWS la salida del Sandbox.

1. Ve al panel de control de **AWS SES**.
2. En la parte superior de la página principal (Dashboard), verás una alerta azul que indica que tu cuenta está en Sandbox. Haz clic en el botón **Request production access** (Solicitar acceso a producción) o ve a la esquina superior derecha y haz clic en **Edit get started**.
3. Rellena el formulario de solicitud con los siguientes detalles recomendados:
   * **Mail type:** Transactional (Correos Transaccionales).
   * **Website URL:** URL de tu SaaS (ej. `https://barbersync.app` o una web informativa del proyecto).
   * **Use case description (Caso de Uso):** Describe de forma clara y detallada cómo utilizarás el servicio. AWS revisa esto manualmente.
     
     *Ejemplo de justificación en español:*
     > "BarberSync es un SaaS de gestión y agendamiento para barberías en Colombia. Los correos enviados serán estrictamente transaccionales, incluyendo: confirmaciones de citas creadas por los clientes, recordatorios automáticos de citas (24 horas y 1 hora antes del servicio), notificaciones de reprogramación de horarios, invitaciones a miembros del personal de la barbería y códigos OTP para verificación de identidad y restablecimiento de contraseñas.
     >
     > Todos los destinatarios corresponden a usuarios registrados o clientes que agendan activamente citas en las sucursales de la plataforma y que han otorgado su consentimiento para recibir notificaciones de su reserva. Contamos con un flujo automatizado para manejar rebotes y quejas de spam mediante AWS SNS integrado en el backend (django-ses), lo que nos permitirá dar de baja de forma inmediata a los correos inválidos para proteger la reputación del dominio."
     
   * **Agreement:** Acepta los términos de servicio sobre no enviar spam (AWS prohíbe el envío masivo de publicidad no solicitada en SES sin flujos adecuados de desuscripción).
4. Envía la solicitud. AWS suele procesar y aprobar estas solicitudes en un plazo de **12 a 24 horas**.

---

## Consejo Técnico de Arquitectura: Gestión de Bounces y Reputación

La integración de BarberSync con **`django-ses`** en lugar del SMTP estándar de AWS ofrece una ventaja competitiva fundamental: **soporte nativo para hooks de AWS SNS (Simple Notification Service)**.

### ¿Por qué es crucial para BarberSync?
Cuando envías correos transaccionales a gran escala (miles de recordatorios de citas al mes), algunos correos rebotarán (bounces) porque la dirección no existe, y otros usuarios podrían marcarlos accidentalmente como spam (complaints). 
Si tu tasa de rebotes supera el **10%** o tu tasa de quejas supera el **0.1%**, **AWS suspenderá temporal o definitivamente tu cuenta de SES** para proteger la reputación de sus IPs.

### ¿Cómo funciona la protección automática con `django-ses`?
1. **AWS SNS** recibe notificaciones en tiempo real cuando un correo de BarberSync rebota o es marcado como spam.
2. `django-ses` provee vistas (endpoints de webhook) en BarberSync que escuchan estas alertas de SNS.
3. El sistema puede dar de baja automáticamente la dirección de correo errónea en el CRM de BarberSync (marcando el email como inactivo o rebotado), previniendo futuros envíos a ese destinatario.
4. Esto garantiza que la reputación de envío de tu dominio se mantenga en **100%**, optimizando la entregabilidad general para todos tus clientes legítimos.
