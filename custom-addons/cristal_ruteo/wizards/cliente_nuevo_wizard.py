# -*- coding: utf-8 -*-
"""Alta rápida de cliente nuevo: primero busca si ya existe; si no, lo crea
(ficha + oportunidad) y lo mete al plan de visitas. Para las visitas 'de paso'."""
from odoo import fields, models
from odoo.exceptions import UserError


class ClienteNuevoWizard(models.TransientModel):
    _name = 'cristal.cliente.nuevo.wizard'
    _description = 'Cliente nuevo (buscar o crear)'

    existing_partner_id = fields.Many2one(
        'res.partner', string="¿Ya está cargado?",
        help="Buscá acá: si el cliente ya existe, usalo (no lo dupliques).")
    name = fields.Char(string="Nombre del cliente nuevo")
    phone = fields.Char(string="Teléfono / WhatsApp")
    city = fields.Char(string="Ciudad", default="Río Cuarto")
    is_company = fields.Boolean(string="Es empresa", default=True)

    def _open_partner(self, partner):
        return {
            'type': 'ir.actions.act_window',
            'name': partner.display_name,
            'res_model': 'res.partner',
            'res_id': partner.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_use_existing(self):
        self.ensure_one()
        if not self.existing_partner_id:
            raise UserError("Elegí un cliente de la lista, o creá uno nuevo abajo.")
        partner = self.existing_partner_id
        vals = {'visit_plan_active': True}
        if not partner.user_id:
            vals['user_id'] = self.env.uid
        partner.write(vals)
        return self._open_partner(partner)

    def action_create_new(self):
        self.ensure_one()
        if not self.name:
            raise UserError("Escribí el nombre del cliente nuevo (o buscá si ya existe).")
        partner = self.env['res.partner'].create({
            'name': self.name,
            'phone': self.phone or False,
            'mobile': self.phone or False,
            'city': self.city or False,
            'is_company': self.is_company,
            'user_id': self.env.uid,
            'visit_plan_active': True,
        })
        self.env['crm.lead'].create({
            'name': "Oportunidad de %s" % self.name,
            'partner_id': partner.id,
            'type': 'opportunity',
            'user_id': self.env.uid,
        })
        return self._open_partner(partner)
