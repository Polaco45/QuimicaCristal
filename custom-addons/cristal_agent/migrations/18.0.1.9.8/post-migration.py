# -*- coding: utf-8 -*-
"""
Migración 18.0.1.9.8 — Opp apunta al CONTACTO, no a empresa madre.

Cambio:
- partner_id de crm.lead/opportunity ahora es el CONTACTO (subcontacto que
  tiene WhatsApp/email), no la empresa madre.
- name de la opp sigue siendo "[Plan Control] {empresa}" para identificar
  visualmente.
- commercial_partner_id (auto desde parent_id del contacto) sigue apuntando
  a la empresa → facturas siguen saliendo a su nombre, sin cambios.
- Búsqueda anti-duplicado de opp ahora es por contact.id (más granular).

Beneficio: cuando se envíen templates/cotizaciones/promos desde la opp,
el destinatario WhatsApp/email se resuelve correctamente del contacto.
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("⚙️  MIGRATION 1.9.8: opp.partner_id = contacto (no empresa madre)")
