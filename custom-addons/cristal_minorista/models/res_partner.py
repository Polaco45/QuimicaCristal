# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models

from .origin import ORIGINS

SEGMENTS = [
    ('campeon', 'Campeón'),
    ('leal', 'Leal'),
    ('nuevo', 'Nuevo'),
    ('en_riesgo', 'En riesgo'),
    ('no_perder', 'No perder'),
    ('dormido', 'Dormido'),
    ('perdido', 'Perdido'),
    ('sin_compras', 'Sin compras'),
]
OPTIN_SOURCES = [
    ('local', 'Local'),
    ('web', 'Web'),
    ('whatsapp', 'WhatsApp'),
    ('importado', 'Importado'),
]
DEFAULT_AREA = '358'   # Río Cuarto: números de 7 dígitos sin característica
# Palabras del nombre que delatan a un negocio sin responsabilidad AFIP cargada.
BUSINESS_WORDS = re.compile(
    r'\b(complejo|lavadero|apart|hotel|hostel|hostal|caba[ñn]as?|club|cooperativa|colegio|escuela|'
    r'instituto|jard[ií]n de infantes|universidad|sociedad|s\.?\s?a\.?\s?s?\.?|s\.?\s?r\.?\s?l\.?|'
    r'srl|sas|ltda|restaurant|restaurante|resto|bar|caf[eé]|cafeter[ií]a|gimnasio|gym|consorcio|'
    r'edificio|cl[ií]nica|sanatorio|hospital|municipalidad|iglesia|parroquia|panader[ií]a|'
    r'carnicer[ií]a|verduler[ií]a|kiosco|almac[eé]n|supermercado|autoservicio|estaci[oó]n|taller|'
    r'inmobiliaria|pizzer[ií]a|helader[ií]a|rotiser[ií]a|comedor|f[aá]brica|empresa|frigor[ií]fico|'
    r'geri[aá]trico|residencia|lubricentro|lavacoches|lavaautos|car ?wash|peluquer[ií]a|'
    r'veterinaria|farmacia|bodega|distribuidora|mayorista|sal[oó]n|aut[oó]dromo|gremio|sindicato|'
    r'asociaci[oó]n|fundaci[oó]n|mutual|centro|camping|country|de qu[ií]mica cristal)\b', re.I)


def wa_key(raw):
    """Clave de WhatsApp: los 10 dígitos nacionales (característica + número) de un
    teléfono argentino escrito de cualquier forma. False si no se puede armar."""
    d = re.sub(r'\D', '', raw or '')
    if not d:
        return False
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('54'):
        d = d[2:]
    if d.startswith('9') and len(d) in (11, 13):   # 9 de celular (a veces con el 15 también)
        d = d[1:]
    if d.startswith('0'):
        d = d[1:]
    if len(d) == 12:
        # 15 después de la característica (2 a 4 dígitos)
        for area in (2, 3, 4):
            if d[area:area + 2] == '15':
                d = d[:area] + d[area + 2:]
                break
    if len(d) == 9 and d.startswith('15'):
        d = d[2:]
    if len(d) == 7:
        d = DEFAULT_AREA + d
    return d if len(d) == 10 else False


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ── Cliente único ─────────────────────────────────────────────
    cristal_wa_key = fields.Char(string='Clave WhatsApp', compute='_compute_cristal_wa_key',
                                 store=True, index=True,
                                 help='Celular normalizado (10 dígitos). Une al mismo cliente '
                                      'en el local, la web y WhatsApp.')
    cristal_wa_dup_count = fields.Integer(string='Contactos con el mismo WhatsApp', readonly=True,
                                          help='Se recalcula cada noche. Más de 1: posible duplicado.')

    # ── Tipo de cliente ───────────────────────────────────────────
    cristal_customer_type_manual = fields.Selection(
        [('cf', 'Consumidor final'), ('negocio', 'Negocio')], string='Tipo de cliente (a mano)',
        help='Si se completa, manda sobre la regla automática.')
    cristal_customer_type = fields.Selection(
        [('cf', 'Consumidor final'), ('negocio', 'Negocio')], string='Tipo de cliente',
        compute='_compute_cristal_customer_type', store=True, index=True)
    cristal_wholesale_buyer = fields.Boolean(
        string='Compra a precio mayorista', readonly=True,
        help='Tiene pedidos confirmados con una lista que no es la de consumidor final '
             '(se recalcula cada noche). Lo vuelve "negocio".')

    # ── Origen ────────────────────────────────────────────────────
    cristal_first_origin = fields.Selection(ORIGINS, string='Origen del cliente', readonly=True,
                                            help='Origen de su primera compra.')

    # ── Consentimiento de marketing ───────────────────────────────
    cristal_mkt_optin = fields.Boolean(string='Acepta promociones', tracking=True)
    cristal_mkt_optin_date = fields.Datetime(string='Fecha de alta en promociones')
    cristal_mkt_optin_source = fields.Selection(OPTIN_SOURCES, string='Dónde aceptó')
    cristal_mkt_optout = fields.Boolean(string='Pidió no recibir promociones', tracking=True,
                                        help='Sigue recibiendo avisos de sus pedidos, no promociones.')
    cristal_mkt_optout_date = fields.Datetime(string='Fecha de baja de promociones')
    cristal_mkt_allowed = fields.Boolean(string='Se le pueden mandar promociones',
                                         compute='_compute_cristal_mkt_allowed', store=True, index=True)

    # ── Comportamiento de compra (lo recalcula el proceso nocturno) ──
    cristal_first_purchase = fields.Date(string='Primera compra', readonly=True)
    cristal_last_purchase = fields.Date(string='Última compra', readonly=True)
    cristal_purchases_total = fields.Integer(string='Compras (2 años)', readonly=True)
    cristal_purchases_365 = fields.Integer(string='Compras (12 meses)', readonly=True)
    cristal_amount_365 = fields.Monetary(string='Facturación (12 meses)', readonly=True,
                                         currency_field='currency_id')
    cristal_avg_ticket = fields.Monetary(string='Ticket promedio (12 meses)', readonly=True,
                                         currency_field='currency_id')
    cristal_cycle_days = fields.Integer(string='Ciclo de compra (días)', readonly=True,
                                        help='Mediana de días entre compras. Sin historia: el ciclo general.')
    cristal_recency_days = fields.Integer(string='Días desde la última compra', readonly=True)
    cristal_channels = fields.Char(string='Canales', readonly=True)
    cristal_segment = fields.Selection(SEGMENTS, string='Segmento', readonly=True, index=True)
    cristal_segment_date = fields.Date(string='Segmento calculado el', readonly=True)
    cristal_cycle_ids = fields.One2many('cristal.cf.cycle', 'partner_id', string='Ciclos de consumo')

    @api.depends('mobile', 'phone')
    def _compute_cristal_wa_key(self):
        for partner in self:
            partner.cristal_wa_key = wa_key(partner.mobile) or wa_key(partner.phone)

    @api.depends('cristal_customer_type_manual', 'is_company', 'vat', 'agent_level',
                 'l10n_ar_afip_responsibility_type_id', 'commercial_partner_id',
                 'name', 'commercial_partner_id.name',
                 'commercial_partner_id.is_company', 'commercial_partner_id.vat',
                 'commercial_partner_id.agent_level',
                 'commercial_partner_id.l10n_ar_afip_responsibility_type_id',
                 'commercial_partner_id.cristal_customer_type_manual',
                 'category_id', 'commercial_partner_id.category_id',
                 'commercial_partner_id.cristal_wholesale_buyer')
    def _compute_cristal_customer_type(self):
        for partner in self:
            com = partner.commercial_partner_id or partner
            manual = partner.cristal_customer_type_manual or com.cristal_customer_type_manual
            if manual:
                partner.cristal_customer_type = manual
                continue
            resp = com.l10n_ar_afip_responsibility_type_id
            if com.agent_level in ('bronce', 'plata', 'oro'):
                kind = 'negocio'
            elif com.cristal_wholesale_buyer or 'Mayorista' in com.category_id.mapped('name'):
                kind = 'negocio'     # Claudio lo etiquetó mayorista o compra a precio mayorista
            elif resp and resp.code != '5':          # cualquier responsabilidad que no sea CF
                kind = 'negocio'
            elif com.is_company and com.vat:
                kind = 'negocio'
            elif BUSINESS_WORDS.search(com.name or ''):
                kind = 'negocio'
            else:
                kind = 'cf'
            partner.cristal_customer_type = kind

    @api.depends('cristal_mkt_optin', 'cristal_mkt_optout', 'cristal_wa_key')
    def _compute_cristal_mkt_allowed(self):
        for partner in self:
            partner.cristal_mkt_allowed = bool(
                partner.cristal_mkt_optin and not partner.cristal_mkt_optout and partner.cristal_wa_key)

    def write(self, vals):
        now = fields.Datetime.now()
        if vals.get('cristal_mkt_optin') and 'cristal_mkt_optin_date' not in vals:
            vals['cristal_mkt_optin_date'] = now
            vals.setdefault('cristal_mkt_optout', False)
        if vals.get('cristal_mkt_optout') and 'cristal_mkt_optout_date' not in vals:
            vals['cristal_mkt_optout_date'] = now
        return super().write(vals)

    def action_cristal_optout(self):
        self.write({'cristal_mkt_optout': True})

    def action_cristal_optin(self, source='whatsapp'):
        self.write({'cristal_mkt_optin': True, 'cristal_mkt_optin_source': source})
