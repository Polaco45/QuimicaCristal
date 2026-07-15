# -*- coding: utf-8 -*-
"""
Configuración de cobranza, colgada de la config del agente (cristal.agent.config)
para que Joaco la edite desde la misma pantalla de siempre.
"""
from odoo import models, fields


class CristalAgentConfig(models.Model):
    _inherit = 'cristal.agent.config'

    # ─── Interruptor maestro ───
    cobranza_enabled = fields.Boolean(
        string="Cobranza automática activa",
        default=False,
        help="Interruptor maestro. Si está apagado, el cron de cobranza no manda "
             "nada aunque esté activo en Tareas Programadas.",
    )
    cobranza_test_mode = fields.Boolean(
        string="Modo prueba (solo un cliente)",
        default=True,
        help="Mientras esté activo, la cobranza SOLO le manda al 'Cliente de "
             "prueba'. Ideal para probar en staging sin molestar a nadie.",
    )
    cobranza_test_partner_id = fields.Many2one(
        'res.partner',
        string="Cliente de prueba",
        help="En modo prueba, el único cliente al que se le manda cobranza.",
    )

    # ─── Parámetros de la cadencia ───
    cobranza_wa_account_id = fields.Many2one(
        'whatsapp.account',
        string="Cuenta WhatsApp de cobranza",
        help="Cuenta desde la que salen los recordatorios (típicamente Info).",
    )
    cobranza_ventana_dias = fields.Integer(
        string="Ventana 'por vencer' (días)",
        default=5,
        help="El estado de cuenta muestra como 'por vencer' las facturas que "
             "vencen dentro de estos días.",
    )
    cobranza_min_gap_days = fields.Integer(
        string="Días mínimos entre pasos",
        default=4,
        help="Mínimo de días entre un paso de la cadencia y el siguiente. Evita "
             "que un cliente que entra ya muy vencido reciba todos los pasos "
             "seguidos.",
    )
    cobranza_min_amount = fields.Float(
        string="Importe mínimo a gestionar",
        default=0.0,
        help="No se gestionan clientes cuyo total vencido sea menor a este "
             "importe. 0 = gestionar todo.",
    )

    # ─── Datos de pago (aparecen en el estado de cuenta y mensajes) ───
    cobranza_payment_titular = fields.Char(
        string="Titular de la cuenta",
        default="Química Cristal – Crilim S.A.S.")
    cobranza_payment_bank = fields.Char(string="Banco", default="Brubank")
    cobranza_payment_cbu = fields.Char(
        string="CBU", default="1430001725040102970011")
    cobranza_payment_alias = fields.Char(string="Alias", default="crilim.sas")
    cobranza_payment_cuit = fields.Char(string="CUIT", default="30-71855127-3")
    cobranza_payment_account = fields.Char(
        string="N° de cuenta", default="2504010297001")
    cobranza_recargo_text = fields.Text(
        string="Texto de recargos (día 10)",
        default="Pasado este aviso se aplicarán los recargos por mora vigentes "
                "sobre el saldo impago.",
        help="Advertencia que aparece en el ultimátum del día 10. El sistema "
             "SOLO advierte; no genera ningún recargo automáticamente.",
    )

    # ─── Responsables de las actividades ───
    cobranza_call_user_id = fields.Many2one(
        'res.users',
        string="Responsable de llamadas (día 15)",
    )
    cobranza_visit_user_id = fields.Many2one(
        'res.users',
        string="Responsable de visitas (día 20)",
    )

    # ─── Templates de WhatsApp por nivel ───
    cobranza_template_day0_id = fields.Many2one(
        'whatsapp.template', string="Template día 0 (recordatorio)")
    cobranza_template_day5_id = fields.Many2one(
        'whatsapp.template', string="Template día 5 (seguimiento)")
    cobranza_template_day10_id = fields.Many2one(
        'whatsapp.template', string="Template día 10 (ultimátum)")
