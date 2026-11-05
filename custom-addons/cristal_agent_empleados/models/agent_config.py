# -*- coding: utf-8 -*-
from odoo import fields, models

DEFAULT_EMPLOYEE_PROMPT = """Sos Claudio, gerente de Química Cristal. {empleado} te escribe en Odoo, en el chatter de un registro donde tiene una actividad abierta. Abajo tenés el registro, sus actividades, los últimos mensajes y el conocimiento que aplica.

Contestale corto y concreto qué tiene que hacer: castellano rioplatense, máximo 3 líneas, texto plano, sin tablas ni listas. Usá solo los datos del registro y del conocimiento; no inventes cantidades, tanques, fechas ni precios.

Antes de escalar, buscá la respuesta en el registro: el origen y las notas de la orden, la nota de la actividad, los componentes (el producto a granel), el centro de trabajo y los mensajes. Si ahí dice de dónde sale el producto (tacho, tanque, granel), qué cantidad o para cuándo, esa es la respuesta: dásela citando el dato. Escalá solo lo que de verdad no está o necesita una decisión.

Si no sabés, o hace falta una decisión de Sergio (precios, proveedores, cantidades distintas a la orden, descartar producto, cambiar fechas de entrega a clientes), usá la herramienta escalate_to_sergio con la pregunta completa y contestá exactamente: Esto lo paso a Sergio

Si te dice que terminó una actividad suya de este registro, cerrala con mark_activity_done y confirmale en pocas palabras.

Si el mensaje no te pide nada (un "ok", un "gracias", un comentario para un compañero), contestá exactamente: SIN_RESPUESTA

Nunca le escribas a clientes ni a proveedores, y no prometas nada en nombre de Sergio."""


class CristalAgentConfig(models.Model):
    _inherit = 'cristal.agent.config'

    employee_mode_enabled = fields.Boolean(
        string="Asistente de empleados activo", default=True,
        help="Claudio contesta en el chatter las consultas de los empleados sobre sus actividades.")
    employee_partner_ids = fields.Many2many(
        'res.partner', 'cristal_agent_config_employee_rel', 'config_id', 'partner_id',
        string="Empleados atendidos",
        help="Si uno de ellos escribe en el chatter de un registro donde tiene una actividad "
             "abierta, Claudio le contesta ahí mismo.")
    system_prompt_employee = fields.Text(
        string="Prompt del asistente de empleados", default=DEFAULT_EMPLOYEE_PROMPT,
        help="{empleado} se reemplaza por el nombre de quien pregunta.")
    employee_hours = fields.Char(
        string="Horario de respuesta", default="8-13,17-20",
        help="Franjas en hora de Córdoba, de lunes a sábado. Fuera de horario la pregunta "
             "espera a la próxima apertura.")
    employee_max_turns = fields.Integer(
        string="Respuestas por registro por día", default=5,
        help="Pasado este número, la consulta se le pasa directo a Sergio.")
    sergio_user_id = fields.Many2one(
        'res.users', string="Usuario de Sergio",
        help="A quién se le crean las actividades de las consultas escaladas.")
    sergio_whatsapp_partner_id = fields.Many2one(
        'res.partner', string="WhatsApp de Sergio",
        help="Contacto con el celular de Sergio para avisarle las consultas escaladas.")
    employee_wa_account_id = fields.Many2one(
        'whatsapp.account', string="Cuenta de WhatsApp para avisar a Sergio")
