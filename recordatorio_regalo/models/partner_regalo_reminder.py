# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import timedelta

class PartnerRegaloReminder(models.TransientModel):
    _name = 'partner.regalo.reminder'
    _description = 'Recordatorio de regalo no usado'

    @api.model
    def enviar_recordatorio_regalo(self):
        Message = self.env['whatsapp.message']
        SaleOrder = self.env['sale.order']

        # Fecha límite: hace 48 horas
        cutoff = fields.Datetime.now() - timedelta(hours=48)

        # Buscar mensajes de las plantillas 191 y 192 enviados hace más de 48 hs
        mensajes = Message.search([
            ('template_id', 'in', ['191', '192']),
            ('state', '=', 'sent'),
            ('create_date', '<=', cutoff)
        ])

        for mensaje in mensajes:
            partner = mensaje.partner_id
            if not partner:
                continue

            # Verificar si ya usó el código REGALOCRISTAL
            usaron_cupon = SaleOrder.search_count([
                ('partner_id', '=', partner.id),
                ('state', 'in', ['sale', 'done']),
                '|',
                ('client_order_ref', 'ilike', 'REGALOCRISTAL'),
                ('note', 'ilike', 'REGALOCRISTAL')
            ])

            if not usaron_cupon:
                # Crear mensaje con plantilla 194 (recordatorio)
                self.env['whatsapp.message'].create({
                    'partner_id': partner.id,
                    'mobile_number': partner.mobile,
                    'template_id': '194',
                    'state': 'queued'
                })
