# -*- coding: utf-8 -*-
"""
Helpers compartidos por las tools y servicios.
"""
from datetime import datetime, timedelta


def is_24h_window_open(env, partner, wa_account_id=None):
    """
    Determina si la ventana de WhatsApp de 24hs está abierta para un cliente.

    La ventana está abierta si el cliente nos escribió un mensaje en las
    últimas 24hs. En ese caso podemos mandarle texto libre.

    Si está cerrada, solo podemos iniciar con templates aprobados por Meta.

    Args:
        env: Odoo env
        partner: res.partner del cliente
        wa_account_id: (opcional) limitar a una cuenta específica

    Returns:
        (bool, datetime or None): (ventana_abierta, fecha_ultimo_inbound)
    """
    if not partner or not partner.exists():
        return False, None

    threshold = datetime.now() - timedelta(hours=24)
    WhatsApp = env['whatsapp.message'].sudo()

    # Buscar el último mensaje inbound del cliente
    domain = [
        ('mobile_number', 'in', [
            partner.mobile or '',
            partner.phone or '',
            '+' + (partner.mobile or '').lstrip('+').lstrip('0').lstrip(),
            '+' + (partner.phone or '').lstrip('+').lstrip('0').lstrip(),
        ]),
        ('message_type', '=', 'inbound'),
    ]
    if wa_account_id:
        domain.append(('wa_account_id', '=', wa_account_id))

    last_inbound = WhatsApp.search(domain, order='create_date desc', limit=1)
    if not last_inbound:
        return False, None

    is_open = last_inbound.create_date >= threshold
    return is_open, last_inbound.create_date


def hours_since_last_inbound(env, partner, wa_account_id=None):
    """Devuelve cuántas horas pasaron desde el último mensaje del cliente,
    o None si nunca escribió."""
    _, last_inbound_date = is_24h_window_open(env, partner, wa_account_id)
    if not last_inbound_date:
        return None
    delta = datetime.now() - last_inbound_date
    return delta.total_seconds() / 3600
