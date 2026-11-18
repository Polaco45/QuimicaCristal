import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        res = super()._action_done()
        # Una entrega validada puede cambiar la etapa (por ejemplo, el kit entregado)
        partners = self.mapped('partner_id.commercial_partner_id')
        if 'sale_id' in self._fields:
            partners |= self.mapped('sale_id.partner_id.commercial_partner_id')
        self.env['cristal.inst.engine']._touch(partners)
        return res
