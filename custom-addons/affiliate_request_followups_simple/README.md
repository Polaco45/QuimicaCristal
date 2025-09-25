# Affiliate Request Followups (Simple)

Recordatorios **12/24/48 h** para `affiliate.request`:
- **Dedupe por email** (elige el más nuevo o el que tenga `signup_token`).
- **Idempotencia** por etapa con tabla `affiliate.request.followup.log` (único por `(request_id, stage)`).
- **Excluye** estados terminales configurables.
- **No borra** emails ni altera mensajes previos.

## Requisitos
- Módulo que provea el modelo **`affiliate.request`** (ajusta `depends` si tu módulo no se llama `affiliate_management`).
- Módulo `mail`.

## Configuración manual tras instalar

1) **Plantilla de correo** (Técnico → Correo → Plantillas)
   - Modelo: `affiliate.request`
   - *Para (email_to)*:
     ```
     ${(object.email or (object.partner_id and object.partner_id.email) or '')}
     ```
   - Asunto y Cuerpo: usar tu HTML. El botón/enlace puede ser:
     ```
     <a t-attf-href="#{object.website_id.domain}/affiliate/signup?token=#{object.signup_token or ''}">
       Aceptar invitación
     </a>
     ```
   - Copiá el **ID** de la plantilla (arriba en la URL o en depurador técnico).

2) **Parámetros del sistema** (Técnico → Parámetros → Parámetros del sistema)
   - `affiliate.followup_template_id` → **ID numérico** de la plantilla creada.
   - `affiliate.followup_terminal_states` → Coma-separado con estados a excluir.  
     Para tu flujo:
     ```
     aproove, cancel, register
     ```
     > Si no lo definís, el módulo usará un **fallback seguro** que excluye
     `aproove, cancel, register, approved, accepted, rejected, cancelled, done, active, valid`.

3) **Cron**  
   Ya viene instalado: **Afiliados: Recordatorios 12/24/48h** (cada 15 min).  
   Podés ejecutarlo manualmente desde Técnico → Acciones planificadas.

## Cómo funciona

- Candidatos = `affiliate.request` con `create_date >= 12h` y `state` **no** en los terminales.
- Se **deduplican por email**; si hay múltiples registros con el mismo email, se elige:
  1. El que **tiene** `signup_token`.
  2. Si ambos/ninguno lo tienen, el de **fecha más reciente**.
- Se calcula etapa: `12`, `24` o `48` según antigüedad.
- Se intenta crear un log `(request_id, stage)`.  
  - Si ya existía, **no** vuelve a enviar.
  - Si no existía, envía la plantilla.

## Pruebas rápidas

1. Crear 2 solicitudes con **mismo email** en estado `draft`.
2. (Opcional) "Envejecer" `create_date` de una a +12h (acción de servidor o SQL).
3. Ejecutar el cron manualmente y revisar:
   - Correos enviados (Técnico → Correo → Correos electrónicos).
   - Logs en `affiliate.request.followup.log` (vía Modelo → Ver).
4. Ejecutar el cron **otra vez** sin cambiar nada → **no** debe reenviar la misma etapa.
5. Envejecer a 24/48 h → debe enviar nuevas etapas respectivas.

## Notas

- Si no hay plantilla o es de otro modelo, el cron **no hace nada** y lo deja logueado.
- Si la plantilla no resuelve un email, Odoo marcará el correo con error "sin destinatarios".
- El módulo **no** crea/borra plantillas ni parámetros. Todo manual para evitar fallos de importación.
