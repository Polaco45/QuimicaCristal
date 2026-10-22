# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _load_pos_data(self, data):
        res = super()._load_pos_data(data)
        try:
            res['data'][0]['_cristal_vg'] = self.config_id._cristal_vg_payload()
        except Exception:
            # La caja tiene que abrir igual aunque falle la venta guiada.
            _logger.exception("venta guiada: no pude armar los datos para la caja %s", self.config_id.name)
            res['data'][0]['_cristal_vg'] = {'enabled': False}
        return res
