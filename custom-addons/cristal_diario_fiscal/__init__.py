# -*- coding: utf-8 -*-
import logging

from . import models

_logger = logging.getLogger(__name__)


def setup_cristal_fiscal(env):
    """Deja configurado el caso de Química Cristal (sin pisar lo ya cargado):
    Ventas X -> diario X (pto. 1), IVA 21% -> Facturas de Venta electrónica;
    cliente sin responsabilidad AFIP -> Ventas X, con responsabilidad -> IVA 21%."""
    FiscalPosition = env['account.fiscal.position']
    Journal = env['account.journal']
    for company in env['res.company'].search([]):
        fp_x = FiscalPosition.search([('name', '=', 'Ventas X'), ('company_id', '=', company.id)], limit=1)
        fp_ri = FiscalPosition.search([('name', '=', 'IVA 21%'), ('company_id', '=', company.id)], limit=1)
        journal_x = Journal.search([
            ('company_id', '=', company.id), ('type', '=', 'sale'),
            ('code', '=', 'X'), ('l10n_ar_afip_pos_number', '=', 1),
        ], limit=1)
        journal_fe = Journal.search([
            ('company_id', '=', company.id), ('type', '=', 'sale'),
            ('l10n_ar_afip_pos_system', '=', 'RAW_MAW'),
        ], limit=1)
        if fp_x and journal_x and not fp_x.cristal_sale_journal_id:
            fp_x.cristal_sale_journal_id = journal_x
        if fp_ri and journal_fe and not fp_ri.cristal_sale_journal_id:
            fp_ri.cristal_sale_journal_id = journal_fe
        if fp_x and not company.cristal_fallback_fiscal_position_id:
            company.cristal_fallback_fiscal_position_id = fp_x
        if fp_ri and not company.cristal_responsible_fiscal_position_id:
            company.cristal_responsible_fiscal_position_id = fp_ri
        _logger.info(
            "cristal_diario_fiscal: %s -> Ventas X=%s/%s, IVA 21%%=%s/%s",
            company.name, fp_x.id, journal_x.id, fp_ri.id, journal_fe.id,
        )


def post_init_hook(env):
    setup_cristal_fiscal(env)
