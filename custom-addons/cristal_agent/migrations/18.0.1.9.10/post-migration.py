# -*- coding: utf-8 -*-
"""
Migración 18.0.1.9.10 — Fix crítico: wa_account de entrada manda sobre memoria.

Bug fix: si un cliente escribía primero a Crilimp (cuenta 8), la memoria
quedaba con client_type='mayorista' para siempre. Cuando después escribía
a Compras (cuenta 5), el bot lo seguía tratando como mayorista y derivaba
al canal donde ya estaba (loop circular).

Cambio en whatsapp_message.py:
- El wa_account_id del mensaje entrante ahora es AUTORIDAD sobre la memoria
- Si la cuenta de entrada da un client_type distinto al guardado, se actualiza
- La memoria solo se usa como fallback cuando NO hay wa_account_id

Auto-fix de memorias inconsistentes:
- Para cada memoria con client_type seteado, recalcular en el próximo mensaje
  según wa_account_id de entrada. No tocamos las memorias existentes (no
  sabemos en qué canal van a escribir próximo) — el código nuevo las corrige
  on-demand.
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("⚙️  MIGRATION 1.9.10: wa_account de entrada manda sobre memoria histórica")
