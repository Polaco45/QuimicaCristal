# -*- coding: utf-8 -*-
"""v1.80 — Lista para la caja: bidones de 20 L (y bases) con precio, para que el mayorista elija
sin ocupar a Guillermo (Joaco, 20/11/2026).

v1.80.2 — Formato TICKET de 80 mm (sale por la ticketera), solo productos CON STOCK y las
fragancias en una sola línea ("sujeto a disponibilidad")."""
from markupsafe import escape

from odoo import fields, http
from odoo.http import request


def _money(v):
    return '${:,.0f}'.format(v or 0).replace(',', '.')


class CristalListaBidones(http.Controller):

    @http.route('/cristal/lista-bidones', type='http', auth='user')
    def lista_bidones(self, **kw):
        rows = request.env['product.product'].cristal_top_bidones()
        hoy = fields.Date.context_today(request.env.user).strftime('%d/%m/%Y')

        def item(r):
            price = ('desde ' if r.get('from') else '') + _money(r['price'])
            if r['kind'] == 'bidon':
                detail = f"Bidón 20 L {price} · {_money(r['price_l'])}/L"
            else:
                detail = f"x unidad {price}"
            frag = "<div class='f'>Fragancia según disponibilidad</div>" if r.get('fragrance') else ''
            return f"<div class='it'><div class='n'>{escape(r['name'])}</div><div class='p'>{detail}</div>{frag}</div>"

        bidones = ''.join(item(r) for r in rows if r['kind'] == 'bidon')
        bases = ''.join(item(r) for r in rows if r['kind'] == 'base')
        body = ''
        if bidones:
            body += f"<div class='h'>BIDONES DE 20 L</div>{bidones}"
        if bases:
            body += f"<div class='h'>BASES CONCENTRADAS</div>{bases}"
        if not body:
            body = "<div class='it'>Sin stock cargado en este momento.</div>"
        html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Lista mayorista</title>
<style>
 @page {{ size: 80mm auto; margin: 0; }}
 * {{ box-sizing: border-box; }}
 body {{ width: 72mm; margin: 0 auto; padding: 2mm 0; font-family: Arial, Helvetica, sans-serif;
        font-size: 12px; color: #000; }}
 .t {{ text-align: center; font-weight: bold; font-size: 15px; }}
 .s {{ text-align: center; font-size: 11px; margin: 2px 0 6px; }}
 .h {{ font-weight: bold; font-size: 13px; border-top: 2px solid #000; border-bottom: 1px solid #000;
       padding: 2px 0; margin-top: 6px; }}
 .it {{ padding: 4px 0; border-bottom: 1px dashed #000; }}
 .n {{ font-weight: bold; font-size: 13px; }}
 .p {{ font-size: 12px; }}
 .f {{ font-size: 10px; font-style: italic; }}
 .pie {{ margin-top: 8px; text-align: center; font-size: 12px; border-top: 2px solid #000; padding-top: 4px; }}
 @media print {{ .noprint {{ display: none; }} }}
</style></head><body>
<div class="noprint" style="margin-bottom:6px"><button onclick="window.print()">Imprimir</button></div>
<div class="t">QUÍMICA CRISTAL</div>
<div class="s">Lista mayorista · {hoy}<br/>Solo productos con stock · bidón con recambio
(vacío con tapa, o nuevo con cargo)</div>
{body}
<div class="pie"><b>Hacé tu pedido por WhatsApp</b><br/><b>358 609 1684</b><br/>Te lo preparamos en el
día y te avisamos cuando está listo para retirar.</div>
<script>window.addEventListener('load', function () {{ setTimeout(function () {{ window.print(); }}, 300); }});</script>
</body></html>"""
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')])
