# -*- coding: utf-8 -*-
"""Registrar una visita que no estaba en el recorrido del día.

No es "dar de alta un cliente nuevo": la mayoría de las veces el cliente YA
existe y ya tiene su oportunidad vigente en el flujo del CRM. Sirve para que la
vendedora complete TODOS los días a TODOS los clientes que visitó, aunque los
tuviera agendados para otro día o no los tuviera agendados.

Reglas:
  · Si el cliente ya está cargado → se usa, NO se duplica.
  · Se engancha a la oportunidad VIGENTE del cliente. Solo si no tiene ninguna
    abierta se le crea una y se la asocia. Nunca se apila una oportunidad nueva
    sobre otra que ya está en el flujo.
  · Al final se abre el registro de la visita para anotar cómo le fue.
"""
from odoo import fields, models
from odoo.exceptions import UserError


class ClienteNuevoWizard(models.TransientModel):
    _name = 'cristal.cliente.nuevo.wizard'
    _description = 'Registrar visita (buscar cliente o crearlo)'

    existing_partner_id = fields.Many2one(
        'res.partner', string="¿Ya está cargado?",
        help="Buscá acá: si el cliente ya existe, usalo (no lo dupliques). "
             "Se va a enganchar a su oportunidad vigente.")
    name = fields.Char(string="Nombre del cliente nuevo")
    phone = fields.Char(string="Teléfono / WhatsApp")
    city = fields.Char(string="Ciudad", default="Río Cuarto")
    is_company = fields.Boolean(string="Es empresa", default=True)

    def _ensure_opportunity(self, partner):
        """Devuelve la oportunidad VIGENTE del cliente; si no tiene, la crea.

        La clave: NO crear una oportunidad nueva cuando el cliente ya tiene una
        andando en el flujo — se trabaja sobre esa.
        """
        lead = partner._visit_open_lead()
        if lead:
            return lead
        return self.env['crm.lead'].sudo().create({
            'name': "Oportunidad de %s" % partner.display_name,
            'partner_id': partner.id,
            'type': 'opportunity',
            'user_id': partner.user_id.id or self.env.uid,
        })

    def _registrar_visita(self, partner):
        """Abre el registro de la visita para anotar cómo le fue."""
        return partner.action_visit_done_wizard()

    def action_use_existing(self):
        self.ensure_one()
        if not self.existing_partner_id:
            raise UserError("Elegí un cliente de la lista, o cargá uno nuevo abajo.")
        partner = self.existing_partner_id
        vals = {'visit_plan_active': True}
        # Solo el visitador: el Vendedor (quien factura) no se toca.
        if not partner.visit_user_id:
            vals['visit_user_id'] = self.env.uid
        partner.write(vals)
        self._ensure_opportunity(partner)
        return self._registrar_visita(partner)

    def action_create_new(self):
        self.ensure_one()
        if not self.name:
            raise UserError("Escribí el nombre del cliente (o buscalo arriba si ya existe).")
        partner = self.env['res.partner'].create({
            'name': self.name,
            'phone': self.phone or False,
            'mobile': self.phone or False,
            'city': self.city or False,
            'is_company': self.is_company,
            'user_id': self.env.uid,
            'visit_user_id': self.env.uid,
            'visit_plan_active': True,
        })
        self._ensure_opportunity(partner)
        return self._registrar_visita(partner)
