# -*- coding: utf-8 -*-
"""
Configuración global del agente Claudio.

Modelo singleton-like (1 sola instancia activa). Guarda la API key de Anthropic,
el modelo de Claude a usar, el system prompt activo, y parámetros operativos.

La configuración se accede desde cualquier parte del código vía:
    config = self.env['cristal.agent.config'].get_active()
"""
import logging
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class CristalAgentConfig(models.Model):
    _name = 'cristal.agent.config'
    _description = "Cristal Agent — Configuración"
    _order = 'active desc, id desc'

    name = fields.Char(
        string="Nombre de configuración",
        required=True,
        default="Configuración principal",
    )
    active = fields.Boolean(string="Activa", default=True)

    # ─────────── API de Anthropic ───────────
    anthropic_api_key = fields.Char(
        string="Anthropic API Key",
        help="API key de Anthropic. Se guarda como ir.config_parameter por seguridad.",
    )
    anthropic_api_url = fields.Char(
        string="Anthropic API URL",
        default="https://api.anthropic.com/v1/messages",
        required=True,
    )
    anthropic_model = fields.Char(
        string="Modelo Claude",
        default="claude-sonnet-4-6",
        required=True,
        help="Identificador del modelo. Ej: claude-sonnet-4-6, claude-opus-4-7",
    )
    # v1.10.5 — Modo híbrido OPCIONAL. Si se carga un modelo acá, el agente lo usa
    # SOLO en tareas complejas (comandos de Joaco, cron proactivo). Para el grueso
    # del tráfico (mensajes WhatsApp de calificación) sigue usando anthropic_model
    # (Haiku). Vacío = usa siempre anthropic_model. Default vacío: dejamos todo en
    # Haiku hasta confirmar que aguanta el cierre; si patina, cargá acá un Sonnet.
    anthropic_model_complex = fields.Char(
        string="Modelo Claude (tareas complejas)",
        default="",
        help="Modelo a usar solo en tareas complejas (joaco_command / cron). "
             "Vacío = usar el modelo base para todo. Ej: claude-sonnet-4-6.",
    )
    anthropic_version = fields.Char(
        string="Versión API",
        default="2023-06-01",
        required=True,
    )

    # ─────────── Parámetros del loop ───────────
    max_tokens = fields.Integer(
        string="Max tokens por respuesta",
        default=4096,
        required=True,
        help="Tokens máximos que Claude puede devolver en cada turno.",
    )
    max_iterations = fields.Integer(
        string="Max iteraciones de tool_use",
        default=20,
        required=True,
        help="Cantidad máxima de ciclos tool_use → tool_result antes de cortar. Evita loops infinitos.",
    )
    temperature = fields.Float(
        string="Temperatura",
        default=0.7,
        help="0.0 = determinístico, 1.0 = más creativo. Para agente comercial: 0.5-0.8.",
    )
    enable_prompt_caching = fields.Boolean(
        string="Activar prompt caching",
        default=True,
        help="Cachea el system prompt para bajar costos en 90% en mensajes seguidos del mismo cliente.",
    )

    # ─────────── System prompt ───────────
    system_prompt = fields.Text(
        string="System prompt activo (mayorista)",
        required=True,
        help="Prompt que define la personalidad, reglas y comportamiento del agente "
             "para flow MAYORISTA. El default se carga desde data/prompts/claudio_v2.md.",
    )
    prompt_version = fields.Char(
        string="Versión del prompt",
        default="claudio_v2",
        required=True,
    )

    # v1.9.0: prompt institucional. Si está vacío, el sistema usa el prompt
    # mayorista con una sección condicional. Si tiene valor, lo usa entero
    # cuando memory.client_type == 'institucional'.
    system_prompt_institutional = fields.Text(
        string="System prompt institucional",
        help="Prompt dedicado para flow INSTITUCIONAL (empresas finales, "
             "Plan Control). Si está vacío, se usa el prompt mayorista. "
             "Default se carga de data/prompts/claudio_institutional_v2.md.",
    )

    # v1.10.0: reporte de muestra (PDF) que el bot adjunta en la propuesta
    # institucional (STEP 3 del flow). El prompt referencia el placeholder
    # {{REPORTE_MUESTRA_ATTACHMENT_ID}}, que prompt_builder reemplaza por este ID.
    institutional_report_attachment_id = fields.Many2one(
        'ir.attachment',
        string="Reporte de muestra (PDF institucional)",
        help="PDF de ejemplo del reporte mensual de consumo que el bot adjunta "
             "en la propuesta institucional. Si está vacío, el bot manda la "
             "propuesta sin adjunto y avisa a Joaco que falta cargarlo. "
             "Se completa solo al subir un PDF en 'institutional_report_pdf'.",
    )

    # v1.10.2 — campo de subida cómodo. Al subir un PDF acá y guardar, se crea
    # un ir.attachment standalone y se setea institutional_report_attachment_id.
    institutional_report_pdf = fields.Binary(
        string="Subir reporte de muestra (PDF)",
        help="Arrastrá acá el PDF de muestra ANONIMIZADO (no uses datos reales "
             "de un cliente). Al guardar, queda como el reporte que adjunta el bot.",
    )
    institutional_report_pdf_filename = fields.Char(
        string="Nombre del archivo del reporte",
    )

    # ─────────── Operativa ───────────
    enabled = fields.Boolean(
        string="Agente habilitado",
        default=True,
        help="Si está apagado, el agente no procesa mensajes entrantes (modo mantenimiento).",
    )
    timezone = fields.Char(
        string="Zona horaria operativa",
        default="America/Argentina/Cordoba",
    )
    work_hours_start = fields.Float(
        string="Hora inicio jornada",
        default=8.5,
        help="8.5 = 8:30 AM",
    )
    work_hours_end = fields.Float(
        string="Hora fin jornada",
        default=21.0,
        help="21.0 = 9:00 PM",
    )

    # ─────────── Identidades técnicas (referencias) ───────────
    bot_partner_id = fields.Many2one(
        'res.partner',
        string="Partner del bot (Claudio)",
        help="Partner que se usa como author_id de los mensajes salientes. "
             "Por defecto: id 80799 (claudio.quimicacristal).",
    )
    owner_partner_id = fields.Many2one(
        'res.partner',
        string="Partner del dueño (Joaco)",
        help="Partner al que se escala. Por defecto: id 65374.",
    )
    owner_user_id = fields.Many2one(
        'res.users',
        string="Usuario dueño (Joaco)",
        help="Usuario al que se asignan leads de Empresa. Por defecto: id 18.",
    )
    bot_user_id = fields.Many2one(
        'res.users',
        string="Usuario del bot (Claudio)",
        help="Usuario al que se asignan leads de Mayorista. Por defecto: id 721.",
    )
    internal_channel_id = fields.Many2one(
        'discuss.channel',
        string="Canal interno Joaco↔Claudio",
        help="Canal donde se postean escalaciones. Por defecto: id 969.",
    )

    # ─────────── Mapping fase agente → stage CRM ───────────
    # Cuando el agente actualiza agent_strategy_phase de un lead, el módulo
    # mueve automáticamente el stage_id del CRM al correspondiente.
    crm_stage_phase_1_id = fields.Many2one(
        'crm.stage',
        string="Stage CRM para Fase 1 (Calificación)",
        help="Etapa del CRM donde se ubica el lead cuando está en Fase 1.",
    )
    crm_stage_phase_2_sample_id = fields.Many2one(
        'crm.stage',
        string="Stage CRM para Fase 2 - Muestra entregada",
        help="Etapa cuando confirmó muestra (post-Fase 1).",
    )
    crm_stage_phase_2_quoted_id = fields.Many2one(
        'crm.stage',
        string="Stage CRM para Fase 2 - Propuesta enviada",
        help="Etapa cuando le mandaste cotización (sale.order).",
    )
    crm_stage_phase_3_won_id = fields.Many2one(
        'crm.stage',
        string="Stage CRM para Fase 3+ (Ganado)",
        help="Etapa cuando hizo primera compra. Después se mantiene acá.",
    )

    # ═════════════════ FEATURE FLAGS (habilidades del bot) ═════════════════
    # Joaco puede prender/apagar capacidades desde la UI sin tocar código.

    # WhatsApp
    enable_send_whatsapp = fields.Boolean(
        string="Enviar WhatsApp (texto libre)",
        default=True,
        help="Si está OFF, el bot no puede mandar mensajes de WA al cliente. "
             "Va a escalar a Joaco siempre. Útil para parar al bot temporalmente.",
    )
    enable_send_whatsapp_templates = fields.Boolean(
        string="Enviar templates WhatsApp",
        default=True,
        help="Si está OFF, el bot no puede iniciar conversación con templates "
             "cuando la ventana 24hs está cerrada. Solo responde mensajes activos.",
    )

    # CRM
    enable_create_leads = fields.Boolean(
        string="Crear leads en CRM",
        default=True,
        help="Si está OFF, el bot no crea leads nuevos. Solo lee/actualiza existentes.",
    )
    enable_update_leads = fields.Boolean(
        string="Actualizar leads",
        default=True,
    )
    enable_schedule_activities = fields.Boolean(
        string="Agendar y completar actividades CRM",
        default=True,
        help="Si está OFF, no agenda actividades nuevas. El cron proactivo no funciona.",
    )
    enable_escalate_to_joaco = fields.Boolean(
        string="Escalar a Joaco",
        default=True,
        help="Si está OFF, el bot intenta resolver todo solo (no recomendado).",
    )

    # Ventas
    enable_create_sale_orders = fields.Boolean(
        string="Crear cotizaciones (sale.order)",
        default=True,
        help="Si está OFF, el bot no crea cotizaciones — escala a Joaco para que cotice.",
    )
    enable_generate_quote_pdf = fields.Boolean(
        string="Generar PDFs de cotización",
        default=True,
    )
    enable_generate_pricelist_pdf = fields.Boolean(
        string="Generar PDFs de Lista Mayorista",
        default=True,
    )

    # Muestras
    enable_confirm_sample = fields.Boolean(
        string="Confirmar envío de muestras",
        default=True,
        help="Si está OFF, el bot escala a Joaco al coordinar muestras (no las registra).",
    )

    # Proactividad
    enable_proactive_activities = fields.Boolean(
        string="Cron PROACTIVO de actividades",
        default=True,
        help="Si está OFF, el cron cada 2hs no ejecuta nada. El bot pasa a 100% reactivo.",
    )
    enable_phase2_cadences = fields.Boolean(
        string="Cadencias proactivas Fase 2 (post-muestra)",
        default=True,
    )
    enable_phase3_cadences = fields.Boolean(
        string="Cadencias proactivas Fase 3 (post-compra)",
        default=True,
    )
    enable_level_recalculation = fields.Boolean(
        string="Recálculo mensual de niveles BRONCE/PLATA/ORO",
        default=False,
        help="Cron mensual que asigna niveles. Default OFF hasta validar reglas.",
    )
    enable_churn_detection = fields.Boolean(
        string="Detección automática de churn",
        default=False,
        help="Cron diario que detecta clientes inactivos. Default OFF.",
    )

    # Aprendizaje y conocimiento
    enable_internal_channel_learning = fields.Boolean(
        string="Aprender desde canal interno con Joaco",
        default=False,
        help="Cuando vos le hablás al bot en el canal interno 969, lo procesa y "
             "puede guardar conocimiento. Default OFF (consume tokens). "
             "Activalo solo cuando vayas a usarlo activamente.",
    )
    enable_apply_offers = fields.Boolean(
        string="Aplicar ofertas vigentes en conversaciones",
        default=True,
        help="Si está OFF, el bot no menciona ofertas proactivamente.",
    )
    enable_qualification = fields.Boolean(
        string="Calificar mayoristas (5 preguntas)",
        default=True,
        help="Si está OFF, el bot no califica — solo atiende consultas y escala.",
    )

    # ─────────── Broadcast semanal de oferta (lunes 14hs) ───────────
    enable_weekly_offer_broadcast = fields.Boolean(
        string="Broadcast semanal de oferta (lunes 14hs)",
        default=False,
        help="Si está ON, todos los lunes a las 14hs se manda la oferta vigente "
             "a TODOS los Mayoristas (excluyendo Fuera de zona y takeovers activos). "
             "Default OFF — activar solo cuando el template esté aprobado.",
    )
    weekly_offer_template_id = fields.Many2one(
        'whatsapp.template',
        string="Template para broadcast semanal",
        domain="[('status', '=', 'approved')]",
        help="Template aprobado que se manda los lunes. Recomendado: oferta_semanal_general. "
             "Variables esperadas: {{1}}=nombre cliente, {{2}}=descripción oferta vigente.",
    )

    # ─────────── Filtrado por cuenta WhatsApp ───────────
    restricted_wa_account_ids = fields.Many2many(
        'whatsapp.account',
        string="Cuentas WhatsApp donde actúa el bot",
        help="Lista de cuentas donde el bot procesa mensajes entrantes. "
             "Si está vacío, el bot actúa en todas las cuentas. "
             "v1.9.0: configurar [5, 8] para que el bot actúe en Crilimp (mayorista, id=8) "
             "Y Compras (institucional, id=5). Info (id=3) queda fuera."
    )

    # ═════════════════ RANGOS DE NIVELES (en LITROS mensuales) ═════════════════
    # Los niveles se miden internamente en monto pero al cliente se le habla en litros.
    level_bronce_max_liters = fields.Integer(
        string="Máximo BRONCE (L/mes)",
        default=500,
        help="Hasta este consumo mensual el cliente es BRONCE.",
    )
    level_plata_max_liters = fields.Integer(
        string="Máximo PLATA (L/mes)",
        default=1500,
        help="Hasta este consumo mensual el cliente es PLATA (5% off). Por encima → ORO.",
    )

    # ─────────── Métricas computadas ───────────
    runs_today = fields.Integer(
        string="Ejecuciones hoy",
        compute='_compute_runs_today',
    )
    runs_total = fields.Integer(
        string="Ejecuciones totales",
        compute='_compute_runs_total',
    )

    # ─────────── Métodos ───────────
    @api.model
    def get_active(self):
        """Devuelve la configuración activa. Si no hay, crea una con defaults."""
        config = self.search([('active', '=', True)], limit=1)
        if not config:
            _logger.warning("No hay config activa. Creando una con defaults.")
            config = self.sudo().create({})
        return config

    @api.model
    def get_api_key(self):
        """Obtiene la API key. Prioridad: ir.config_parameter, luego campo del modelo."""
        param_key = self.env['ir.config_parameter'].sudo().get_param('cristal_agent.anthropic_api_key')
        if param_key:
            return param_key
        config = self.get_active()
        return config.anthropic_api_key or False

    def write(self, vals):
        """Si se escribe la API key, también la guardamos en ir.config_parameter."""
        if 'anthropic_api_key' in vals and vals['anthropic_api_key']:
            self.env['ir.config_parameter'].sudo().set_param(
                'cristal_agent.anthropic_api_key', vals['anthropic_api_key']
            )
        res = super().write(vals)
        # v1.10.2 — si subieron un PDF de reporte, materializarlo como
        # ir.attachment standalone y apuntar el m2o que usa el bot.
        if 'institutional_report_pdf' in vals:
            for rec in self:
                rec._sync_institutional_report_attachment()
        return res

    def _sync_institutional_report_attachment(self):
        """Crea un ir.attachment standalone a partir del PDF subido y lo asigna
        a institutional_report_attachment_id (el que adjunta send_whatsapp)."""
        self.ensure_one()
        if not self.institutional_report_pdf:
            return
        name = self.institutional_report_pdf_filename or 'Reporte de muestra - Quimica Cristal.pdf'
        att = self.env['ir.attachment'].sudo().create({
            'name': name,
            'datas': self.institutional_report_pdf,
            'mimetype': 'application/pdf',
            'type': 'binary',
        })
        # No re-dispara el sync porque vals no incluye institutional_report_pdf.
        self.institutional_report_attachment_id = att.id

    @api.constrains('active')
    def _check_only_one_active(self):
        for rec in self:
            if rec.active:
                others = self.search([('active', '=', True), ('id', '!=', rec.id)])
                if others:
                    raise ValidationError(_(
                        "Solo puede haber UNA configuración activa. "
                        "Desactive primero las demás."
                    ))

    @api.constrains('max_iterations')
    def _check_max_iterations(self):
        for rec in self:
            if rec.max_iterations < 1 or rec.max_iterations > 100:
                raise ValidationError(_("max_iterations debe estar entre 1 y 100."))

    @api.constrains('max_tokens')
    def _check_max_tokens(self):
        for rec in self:
            if rec.max_tokens < 256 or rec.max_tokens > 16384:
                raise ValidationError(_("max_tokens debe estar entre 256 y 16384."))

    def _compute_runs_today(self):
        Run = self.env['cristal.agent.run']
        today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for rec in self:
            rec.runs_today = Run.search_count([('create_date', '>=', today_start)])

    def _compute_runs_total(self):
        Run = self.env['cristal.agent.run']
        for rec in self:
            rec.runs_total = Run.search_count([])

    def action_test_connection(self):
        """Botón en la UI para testear que la API key funciona."""
        self.ensure_one()
        api_key = self.get_api_key()
        if not api_key:
            raise UserError(_("No hay API key configurada."))

        try:
            import requests
        except ImportError:
            raise UserError(_("Falta el paquete Python 'requests'. Instalalo con pip."))

        headers = {
            "x-api-key": api_key,
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
        }
        body = {
            "model": self.anthropic_model,
            "max_tokens": 50,
            "messages": [{"role": "user", "content": "Decí 'OK' si me leés."}],
        }
        try:
            resp = requests.post(self.anthropic_api_url, headers=headers, json=body, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'title': _("Conexión OK"),
                    'message': _("Claude respondió: %s") % (text or "(sin texto)"),
                    'sticky': False,
                },
            }
        except Exception as e:
            raise UserError(_("Error al conectar con Anthropic: %s") % str(e))

    # ════════════════════════════════════════════════════════════════════
    # v1.9.0 — Helpers de routing institucional vs mayorista
    # ════════════════════════════════════════════════════════════════════

    # IDs de las cuentas WhatsApp. Hardcoded por ahora — si Joaco cambia
    # las cuentas, hay que actualizar acá.
    WA_ACCOUNT_CRILIMP = 8       # Mayorista (flow Claudio v3.1)
    WA_ACCOUNT_COMPRAS = 5       # Institucional (flow Plan Control)
    WA_ACCOUNT_INFO = 3          # No usar

    # Categorías de partner que indican el tipo (fallback cuando no hay
    # wa_account_id claro). Pueden estar superpuestas en algunos partners.
    CATEGORY_MAYORISTA = 16
    CATEGORY_EMPRESA = 1

    # Partners internos a EXCLUIR del filtro de "cliente activo" para no
    # contar comprobantes X de consumo propio (Sergio, Joaquin, Claudio bot, etc).
    INTERNAL_PARTNER_IDS = [3, 60023, 65371, 65374, 75679, 79526, 79653, 80799, 64675]

    @api.model
    def detect_client_type(self, wa_account_id=None, partner=None):
        """
        Devuelve 'mayorista' / 'institucional' / 'unknown'.

        Criterio principal: wa_account_id por donde entró el mensaje.
        Fallback: categorías del partner.
        """
        # CRITERIO 1: wa_account_id (la fuente más confiable)
        if wa_account_id == self.WA_ACCOUNT_CRILIMP:
            return 'mayorista'
        if wa_account_id == self.WA_ACCOUNT_COMPRAS:
            return 'institucional'

        # CRITERIO 2: categorías del partner
        if partner:
            cats = partner.category_id.ids
            if self.CATEGORY_MAYORISTA in cats:
                return 'mayorista'
            if self.CATEGORY_EMPRESA in cats:
                return 'institucional'

        return 'unknown'

    @api.model
    def has_recent_real_sale(self, partner, days=180):
        """
        True si el partner (o su commercial_partner) tiene una venta REAL
        (no muestra, no comprobante interno) en los últimos N días.

        Filtros:
        - state = 'sale' (confirmada)
        - company_id = 1 (Crilim S.A.S.)
        - amount_total > 0 (excluye muestras de $0)
        - commercial_partner NO está en lista de internos
        - date_order >= today - N días
        """
        if not partner:
            return False

        # Excluir el propio partner si es interno (no aplica bypass)
        commercial_id = partner.commercial_partner_id.id
        if commercial_id in self.INTERNAL_PARTNER_IDS:
            return False

        cutoff = fields.Date.today() - timedelta(days=days)
        count = self.env['sale.order'].sudo().search_count([
            ('partner_id.commercial_partner_id', '=', commercial_id),
            ('state', '=', 'sale'),
            ('company_id', '=', 1),
            ('amount_total', '>', 0),
            ('partner_id.commercial_partner_id', 'not in', self.INTERNAL_PARTNER_IDS),
            ('date_order', '>=', cutoff),
        ])
        return count > 0

    @api.model
    def should_bypass_qualification(self, client_type, partner, memory):
        """
        Devuelve (bool, reason) indicando si el bot debe saltarse el
        flow de calificación y activar takeover directamente.

        IMPORTANTE: el bypass aplica SOLO a client_type='institucional'.
        Para mayorista (Claudio v3.1) NUNCA se hace bypass.
        """
        if client_type != 'institucional':
            return (False, None)

        # Si ya estaba calificado en el pasado, no recalificar
        if memory and memory.qual_qualified:
            return (True, "Ya calificado previamente")

        # Si tiene venta real reciente, es cliente activo
        if self.has_recent_real_sale(partner):
            return (True, "Cliente activo con ventas recientes")

        return (False, None)
