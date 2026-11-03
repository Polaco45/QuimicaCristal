# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CristalComprasPriceList(models.Model):
    _name = 'cristal.compras.price.list'
    _description = "Cristal — lista de precios recibida de un proveedor"
    _order = 'date desc, id desc'

    name = fields.Char(string="Archivo", required=True)
    partner_id = fields.Many2one('res.partner', string="Proveedor", required=True, index=True,
                                 ondelete='cascade')
    date = fields.Date(string="Recibida", default=fields.Date.context_today, required=True)
    source = fields.Selection([('whatsapp', "WhatsApp"), ('mail', "Mail"), ('manual', "A mano")],
                              string="Llegó por", default='manual')
    attachment_id = fields.Many2one('ir.attachment', string="Adjunto", ondelete='set null')
    datas = fields.Binary(related='attachment_id.datas', string="Descargar")
    state = fields.Selection([('new', "Para subir al Drive"), ('done', "Subida y cargada")],
                             string="Estado", default='new', required=True)

    @api.model
    def register(self, partner, attachment, source):
        """Guarda una copia del archivo en la ficha del proveedor (sin preguntar)."""
        partner = partner.commercial_partner_id
        existing = self.search([('partner_id', '=', partner.id), ('attachment_id.checksum', '=', attachment.checksum)],
                               limit=1) if attachment.checksum else self
        if existing:
            return existing
        copy = attachment.sudo().copy({'res_model': 'res.partner', 'res_id': partner.id})
        record = self.create({'name': attachment.name or "Lista de precios", 'partner_id': partner.id,
                              'source': source, 'attachment_id': copy.id})
        partner.sudo().cristal_price_list_date = record.date
        return record

    def action_mark_done(self):
        self.write({'state': 'done'})
