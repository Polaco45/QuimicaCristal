# -*- coding: utf-8 -*-
"""v1.80 — Mayoristas en el local: llegan con el pedido hecho (Joaco, 20/11/2026).

"Los pedidos para retirar en el local deben hacerse anticipadamente … Guillermo debe tener un
botón en el POS donde pueda imprimir un listado de precios x 20 lts de los productos más
vendidos y enviar por WhatsApp la lista de precios mayorista con todo el listado de
productos … tenemos que rumbear a que vayan con el pedido listo … muchos consumidores
finales entran y se van por la demora larga de atender a un mayorista."

- `cristal_top_bidones()`: los bidones de 20 L más vendidos con precio por bidón y por litro
  (la hoja que imprime la caja, controlador /cristal/lista-bidones).
- `res.partner.cristal_pos_send_pricelist(phone, name)`: desde la caja le manda al
  mayorista la lista completa por WhatsApp (cuenta Cristal Mayorista) para que arme el
  pedido con Claudio.
- `sale.order.action_cristal_pickup_ready()`: botón "Avisar que está listo" en los pedidos
  para retirar: le avisa al cliente por WhatsApp que ya puede pasar.
"""
import logging
import re
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PICKUP_ADDRESS = "San Martín 2350, Río Cuarto"
SALES_DAYS = 120


def _ar_mobile(phone):
    """'358 154 123456' / '0358-4123456' / '+54 9 358…' → '+5493584123456' (o '')."""
    d = re.sub(r'\D', '', phone or '').lstrip('0')
    if d.startswith('54'):
        d = d[2:]
    d = d.lstrip('9').lstrip('0') if len(d) > 10 else d
    if len(d) == 9 and d.startswith('15'):
        d = '358' + d[2:]
    m = re.match(r'^(\d{2,4})15(\d{6,8})$', d)
    if len(d) in (11, 12) and m and len(m.group(1) + m.group(2)) == 10:
        d = m.group(1) + m.group(2)
    if len(d) == 7:
        d = '358' + d
    return f"+549{d}" if len(d) == 10 else ''


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def cristal_top_bidones(self, limit=0):
        """Lista para la caja (ticket): SOLO lo que tiene stock. [{name, price, price_l, sold,
        fragrance, kind}]. Bidones de 20 L más vendidos primero (ventas de 120 días, el granel
        cuenta como su bidón) y después las bases. Las fragancias van en UNA línea (Joaco,
        20/11/2026: "los desodorantes no los pongas por fragancia… las bases 1 unidad sin
        fragancia, eso queda sujeto a disponibilidad")."""
        from ..services.tools.search_products import is_bidon20, bidon20_equivalent, is_granel
        Product = self.sudo()
        pricelist = self.env['product.pricelist'].sudo().search(
            [('name', '=', 'Lista Mayorista')], limit=1)
        bidones = Product.search([('sale_ok', '=', True), ('name', '=ilike', '% x 20 lts%')])
        bases = Product.search([('sale_ok', '=', True), ('product_tmpl_id.name', '=ilike', 'base %')])
        sold = {p.id: 0.0 for p in bidones}
        since = fields.Datetime.now() - timedelta(days=SALES_DAYS)
        lines = self.env['sale.order.line'].sudo().read_group(
            [('order_id.state', 'in', ('sale', 'done')), ('order_id.date_order', '>=', since),
             '|', ('product_id.name', 'ilike', 'granel'), ('product_id.name', '=ilike', '% x 20 lts%')],
            ['product_id', 'product_uom_qty:sum'], ['product_id'])
        cache = {}
        for row in lines:
            prod = Product.browse(row['product_id'][0])
            qty = row['product_uom_qty'] or 0.0
            if is_bidon20(prod):
                target, n = prod, qty
            elif is_granel(prod):
                if prod.id not in cache:
                    cache[prod.id] = bidon20_equivalent(self.env, prod)
                target, n = cache[prod.id], qty / 20.0
            else:
                continue
            if target and target.id in sold:
                sold[target.id] += n

        groups = {}
        for kind, prods in (('bidon', bidones), ('base', bases)):
            for p in prods:
                ptavs = p.product_template_attribute_value_ids
                frag = ptavs.filtered(lambda v: 'fragan' in (v.attribute_id.name or '').lower())
                other = ptavs - frag
                if any((v.name or '').lower() == 'granel' for v in other):
                    continue
                key = (kind, p.product_tmpl_id.id, tuple(other.ids))
                g = groups.setdefault(key, {'kind': kind, 'tmpl': p.product_tmpl_id,
                                            'extra': ' '.join(other.mapped('name')),
                                            'fragrance': bool(frag), 'stock': 0.0,
                                            'prices': [], 'sold': 0.0})
                g['stock'] += max(p.free_qty, 0.0) if p.is_storable else 1.0
                price = pricelist._get_product_price(p, 1.0) if pricelist else p.list_price
                if price > 1.0 and (p.free_qty > 0 or not p.is_storable):
                    g['prices'].append(price)
                g['sold'] += sold.get(p.id, 0.0)
        out = []
        for g in groups.values():
            if g['stock'] <= 0 or not g['prices']:
                continue
            name = g['tmpl'].name.replace(' x 20 lts', '').strip()
            if g['extra']:
                name = f"{name} {g['extra']}"
            price = min(g['prices'])
            out.append({'name': name, 'price': price,
                        'price_l': price / 20.0 if g['kind'] == 'bidon' else 0.0,
                        'sold': g['sold'], 'kind': g['kind'], 'fragrance': g['fragrance'],
                        'from': len(set(g['prices'])) > 1})
        out.sort(key=lambda r: (r['kind'] != 'bidon', -r['sold'], r['name']))
        return out[:limit] if limit else out


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def cristal_pos_send_pricelist(self, phone, name=False):
        """Desde la caja: le manda al mayorista la lista de precios completa por WhatsApp
        (cuenta Cristal Mayorista) con el aviso de que el pedido se arma por ahí y se retira
        cuando está listo. Devuelve {'ok', 'message'} para mostrar en la caja."""
        mobile = _ar_mobile(phone)
        if not mobile:
            return {'ok': False, 'message': "El número no es válido: cargalo con característica "
                                            "(ej. 358 4123456)."}
        Partner = self.sudo()
        tail = mobile[-8:]
        partner = Partner.search(['|', ('mobile', 'ilike', tail), ('phone', 'ilike', tail)],
                                 limit=1, order='id desc')
        if not partner:
            vals = {'name': (name or '').strip() or f"Mayorista (caja) {mobile[-10:]}",
                    'mobile': mobile}
            tag = self.env['res.partner.category'].sudo().search(
                [('name', '=ilike', 'mayorista')], limit=1)
            if tag:
                vals['category_id'] = [(4, tag.id)]
            partner = Partner.create(vals)
        elif name and partner.name.startswith('Mayorista (caja)'):
            partner.name = name.strip()

        from ..services.tool_registry import ToolRegistry
        from ..services.helpers import closed_window_template
        pdf = ToolRegistry.get('generate_pricelist_pdf')
        res = pdf.execute(env=self.env, run=None) if pdf else {}
        att = self.env['ir.attachment'].sudo().browse(res.get('attachment_id') or 0).exists()
        if not att:
            return {'ok': False, 'message': "No pude armar la lista de precios. Avisale a Joaco."}
        att.public = True
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        link = f"{base}/web/content/{att.id}/{att.name}"
        text = (f"Te paso la lista de precios mayorista de Química Cristal: {link} — Elegí "
                f"tranquilo y mandanos tu pedido por acá: lo preparamos en el día y te avisamos cuando "
                f"esté listo para retirar en {PICKUP_ADDRESS} (no se arma en el momento).")

        account = self.env['whatsapp.account'].sudo().search(
            [('name', 'ilike', 'Mayorista')], limit=1)
        env2 = self.env(context=dict(self.env.context, from_cristal_agent=True,
                                     wa_transactional=True, cristal_system_attachments=True))
        channel = self.env['discuss.channel'].sudo().search(
            [('channel_type', '=', 'whatsapp'), ('channel_partner_ids', 'in', partner.ids)]
            + ([('wa_account_id', '=', account.id)] if account else []),
            order='write_date desc', limit=1)
        sent = {}
        if channel and channel.wa_account_id and channel.whatsapp_number:
            tool = ToolRegistry.get('send_whatsapp')
            sent = tool.execute(env=env2, run=None, channel_id=channel.id, body=f"<p>{text}</p>",
                                wa_account_id=channel.wa_account_id.id,
                                mobile_number=channel.whatsapp_number,
                                attachment_ids=[att.id]) or {}
        else:
            template = closed_window_template(self.env, account.id if account else False)
            tool = ToolRegistry.get('send_whatsapp_template')
            if template and tool:
                sent = tool.execute(env=env2, run=None, partner_id=partner.id,
                                    template_name=template.template_name, variables=[text],
                                    wa_account_id=template.wa_account_id.id) or {}
            else:
                sent = {'error': 'no hay plantilla aprobada para escribirle'}
        if not sent.get('ok'):
            _logger.warning("Lista mayorista desde la caja a %s no salió: %s", mobile, sent)
            return {'ok': False, 'message': "No se pudo mandar el WhatsApp: "
                                            + str(sent.get('error') or sent.get('message') or '')[:160]}
        partner.message_post(body="📲 Lista de precios mayorista enviada por WhatsApp desde la caja "
                                  "(para que arme el pedido y retire cuando esté listo).",
                             subtype_xmlid='mail.mt_note')
        return {'ok': True, 'message': f"Lista enviada por WhatsApp a {partner.name}. Cuando "
                                       f"conteste, Claudio le arma el pedido."}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    cristal_pickup_ready_at = fields.Datetime(
        string="Aviso de listo para retirar", copy=False, readonly=True)

    def action_cristal_pickup_ready(self):
        """Botón para quien arma el pedido: avisa al cliente que ya puede pasar a retirar."""
        from ..services.tool_registry import ToolRegistry
        tool = ToolRegistry.get('send_whatsapp')
        for order in self:
            if order.state not in ('sale', 'done'):
                raise UserError("Primero confirmá el pedido.")
            partner = order.partner_id
            channel = self.env['discuss.channel'].sudo().search(
                [('channel_type', '=', 'whatsapp'), ('channel_partner_ids', 'in', partner.ids)],
                order='write_date desc', limit=1)
            if not tool or not channel or not channel.wa_account_id or not channel.whatsapp_number:
                raise UserError(f"{partner.name} no tiene chat de WhatsApp: avisale por teléfono.")
            text = (f"Tu pedido {order.name} ya está listo para retirar en {PICKUP_ADDRESS} "
                    f"(lunes a viernes de 8 a 13 y de 17 a 20, sábados de 9 a 13). Traé los "
                    f"bidones vacíos con tapa para el recambio. ¡Te esperamos!")
            env2 = self.env(context=dict(self.env.context, from_cristal_agent=True,
                                         wa_transactional=True))
            res = tool.execute(env=env2, run=None, channel_id=channel.id, body=f"<p>{text}</p>",
                               wa_account_id=channel.wa_account_id.id,
                               mobile_number=channel.whatsapp_number) or {}
            if not res.get('ok'):
                raise UserError("No se pudo mandar el aviso: "
                                + str(res.get('error') or res.get('message') or '')[:200])
            order.cristal_pickup_ready_at = fields.Datetime.now()
            order.message_post(body="📲 Se le avisó al cliente que el pedido está listo para retirar.",
                               subtype_xmlid='mail.mt_note')
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': "Aviso enviado",
                           'message': "El cliente ya sabe que puede pasar a retirar.",
                           'type': 'success'}}
