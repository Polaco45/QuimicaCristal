# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """16/11/2026 — Reactivación con oferta desde el primer mensaje.

    Datos al 16/11: "te extrañamos" sin oferta (paso 1) vendió 4 de 181 y el grupo de
    control sin mensaje compró más (2 de 20); el de regalo (paso 2) trajo la venta más
    grande ($125.600). Nuevo orden, con plantillas ya aprobadas por Meta:
      paso 1 = regalo (plantilla del regalo), paso 2 = 10 % de descuento con vencimiento
      (plantilla de último aviso), paso 3 = apagado (tercer mensaje pago sin respuesta).
    """
    def template(name_like):
        cr.execute("SELECT id FROM whatsapp_template WHERE name::text ILIKE %s ORDER BY id LIMIT 1",
                   ('%' + name_like + '%',))
        row = cr.fetchone()
        return row and row[0]

    gift, last = template('Reactivación 2 — regalo'), template('Reactivación 3 — último aviso')
    if gift:
        cr.execute("""UPDATE cristal_fid_flow
                         SET template_id = %s, offer_text = 'un Limpiador Desodorante 900cc de regalo',
                             name = 'Reactivación 1 — regalo'
                       WHERE code = 'reactivacion_1'""", (gift,))
    if last:
        cr.execute("""UPDATE cristal_fid_flow
                         SET template_id = %s, offer_text = 'un 10%% de descuento',
                             name = 'Reactivación 2 — 10 %% de descuento'
                       WHERE code = 'reactivacion_2'""", (last,))
    cr.execute("UPDATE cristal_fid_flow SET send_enabled = false WHERE code = 'reactivacion_3'")
    _logger.info("cristal_fidelizacion 1.7.0: reactivación 1 = regalo (%s), 2 = 10%% (%s), 3 apagada",
                 gift, last)
