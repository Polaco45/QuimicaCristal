# -*- coding: utf-8 -*-
import logging

from . import models

_logger = logging.getLogger(__name__)

# Familias de producto para medir el ciclo de consumo. Cada patrón se busca en el
# nombre del producto (sin distinguir mayúsculas); varios patrones se separan con |.
FAMILIES = [
    ('Lavandina', 'lavandina'),
    ('Jabón para ropa', 'jabon b/e|jabón b/e|jabon liq|jabón liq|jabon p/ropa|ariel|skip'),
    ('Suavizante', 'suavizante'),
    ('Detergente', 'detergente'),
    ('Limpiador desodorante', 'limpiador desod|limp desod|limp. desod'),
    ('Desengrasante', 'desengrasante'),
    ('Cloro y químicos de pileta', 'cloro|alguicida|clarificador'),
    ('Bolsas de residuo', 'bolsa negra|bolsa residuo|bolsa consorcio'),
    ('Papel y rollos', 'papel hig|rollo cocina|toalla inter|bobina'),
    ('Perfume para ropa', 'perfume p/ropa|perfume ropa'),
]


def post_init_hook(env):
    Family = env['cristal.cf.family']
    for seq, (name, pattern) in enumerate(FAMILIES):
        if not Family.search([('name', '=', name)], limit=1):
            Family.create({'name': name, 'match_pattern': pattern, 'sequence': seq})

    anon = env['res.partner'].search([('name', '=', 'Consumidor Final Anónimo')], limit=1)
    if anon:
        env['ir.config_parameter'].sudo().set_param('cristal_minorista.anonymous_partner_id', str(anon.id))

    # Origen de las ventas históricas, con las mismas reglas que las ventas nuevas.
    bot_ids = env['sale.order']._cristal_bot_user_ids() or [0]
    cr = env.cr
    cr.execute("UPDATE pos_order SET cristal_origin = 'local' WHERE cristal_origin IS NULL")
    if 'website_id' in env['sale.order']._fields:
        cr.execute("UPDATE sale_order SET cristal_origin = 'web' "
                   "WHERE cristal_origin IS NULL AND website_id IS NOT NULL")
    cr.execute("UPDATE sale_order SET cristal_origin = 'whatsapp_ia' "
               "WHERE cristal_origin IS NULL AND create_uid = ANY(%s)", [bot_ids])
    cr.execute("UPDATE sale_order SET cristal_origin = 'manual' WHERE cristal_origin IS NULL")
    _logger.info("cristal_minorista: origen histórico cargado")

    env['cristal.minorista.engine']._cron_refresh()
