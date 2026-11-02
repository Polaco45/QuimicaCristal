# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

# Las casillas de Ferozo que ya tienen alias en Odoo (bandejas que armó Sergio + ventas@).
ACCOUNTS = [
    ('Administración', 'admin@quimicacristal.com.ar', 10),
    ('Ventas', 'ventas@quimicacristal.com.ar', 20),
    ('Compras', 'compras@quimicacristal.com.ar', 30),
    ('Info', 'info@quimicacristal.com.ar', 40),
    ('Cristal', 'cristal@quimicacristal.com.ar', 50),
    ('Bandeja', 'bandeja@quimicacristal.com.ar', 60),
]


def post_init_hook(env):
    Account = env['cristal.mail.account'].sudo()
    Server = env['fetchmail.server'].sudo().with_context(active_test=False)
    for name, email, seq in ACCOUNTS:
        if Account.with_context(active_test=False).search_count([('email', '=', email)]):
            continue
        account = Account.create({'name': name, 'email': email, 'sequence': seq})
        # ventas@ ya se leía por IMAP ("Entrada ventas"): se reusa ese servidor tal cual.
        server = Server.search([('user', '=ilike', email), ('server_type', '=', 'imap')], limit=1)
        if server:
            account.fetchmail_server_id = server
        _logger.info("cristal_correo: casilla %s (%s)", email, account.destination)
