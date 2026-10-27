# -*- coding: utf-8 -*-
import logging
import uuid

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Dos pedidos de POS de dic/2024 (San Martin/1475 y /1501) quedaron con el
    # mismo uuid: Odoo no puede crear la restricción única pos_order_uuid_unique
    # y loguea un ERROR cada vez que se actualiza pos.order (build en Test: Failed).
    # Se conserva el uuid del pedido más viejo y al resto se le da uno nuevo.
    cr.execute("""
        SELECT uuid, array_agg(id ORDER BY id)
          FROM pos_order
         WHERE uuid IS NOT NULL
      GROUP BY uuid
        HAVING count(*) > 1
    """)
    for old_uuid, ids in cr.fetchall():
        for order_id in ids[1:]:
            new_uuid = str(uuid.uuid4())
            cr.execute("UPDATE pos_order SET uuid = %s WHERE id = %s", (new_uuid, order_id))
            _logger.info("pos.order %s: uuid duplicado %s -> %s", order_id, old_uuid, new_uuid)
