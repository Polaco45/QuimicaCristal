from odoo import fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    inst_first_offer = fields.Boolean(
        'Propuesta de primera compra (institucional)', copy=False,
        help='Cotización con la oferta de primera compra. Tiene un piso de margen que no se puede perforar.')

    def _inst_offer_params(self):
        icp = self.env['ir.config_parameter'].sudo()

        def _num(key, default):
            try:
                return float(icp.get_param('cristal_institucional.%s' % key, default))
            except (TypeError, ValueError):
                return default
        return _num('first_offer_discount', 20.0), _num('first_offer_min_margin_pct', 15.0)

    def action_inst_apply_first_offer(self):
        discount, _floor = self._inst_offer_params()
        for order in self:
            if order.state not in ('draft', 'sent'):
                raise UserError('La oferta solo se aplica a una cotización sin confirmar.')
            lines = order.order_line.filtered(
                lambda l: not l.display_type and not getattr(l, 'is_delivery', False))
            lines.write({'discount': discount})
            order.inst_first_offer = True
        return True

    def action_confirm(self):
        for order in self.filtered('inst_first_offer'):
            _discount, floor = order._inst_offer_params()
            if order.amount_untaxed > 0:
                pct = 100.0 * (order.sudo().margin or 0.0) / order.amount_untaxed
                if pct < floor:
                    raise UserError(
                        'La propuesta de primera compra deja %.1f %% de margen y el piso es %.0f %%. '
                        'Bajá el descuento o cambiá los productos antes de confirmar.' % (pct, floor))
        return super().action_confirm()
