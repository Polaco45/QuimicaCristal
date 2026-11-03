# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

# Sergio (03/11): a estos no se les pide la lista del mes.
EXEMPT = ['makro', 'superimperio', 'yash', 'transporte cuarto de milla', 'ayello']
# A estos, en vez de la lista completa, se les pasa el listado de materias primas.
RAW_MATERIALS = ['química olivos', 'quimica olivos']


def post_init_hook(env):
    Partner = env['res.partner'].sudo()
    suppliers = Partner.search([('supplier_rank', '>', 0), ('parent_id', '=', False)])
    for partner in suppliers:
        name = (partner.name or '').lower()
        if any(key in name for key in EXEMPT):
            partner.cristal_price_list_exempt = True
            _logger.info("cristal_compras: %s no recibe pedido de lista", partner.name)
        elif any(key in name for key in RAW_MATERIALS):
            partner.cristal_price_list_mode = 'raw'
            _logger.info("cristal_compras: %s cotiza el listado de materias primas", partner.name)
