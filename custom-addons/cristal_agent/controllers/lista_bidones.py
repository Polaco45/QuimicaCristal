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
            # v1.80.4 — Joaco (foto del ticket): "usá mejor los márgenes y que se vean bien los
            # precios". Precio grande y en negrita a la derecha; el por litro abajo, también en negrita.
            if r['kind'] == 'bidon':
                left, sub = "Bidón 20 L", f"{_money(r['price_l'])} por litro"
            else:
                left, sub = "Por unidad", ''
            frag = "Fragancia según disponibilidad" if r.get('fragrance') else ''
            extra = ' · '.join(x for x in (sub, frag) if x)
            extra = f"<div class='x'>{extra}</div>" if extra else ''
            return (f"<div class='it'><div class='n'>{escape(r['name'])}</div>"
                    f"<div class='p'><span>{left}</span><b>{price}</b></div>{extra}</div>")

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
 html, body {{ margin: 0; padding: 0; }}
 body {{ width: 100%; padding: 1mm 1mm 3mm; font-family: Arial, Helvetica, sans-serif;
        font-size: 14px; font-weight: bold; color: #000; -webkit-print-color-adjust: exact; }}
 .t {{ text-align: center; font-weight: 900; font-size: 20px; }}
 .s {{ text-align: center; font-size: 13px; margin: 2px 0 6px; }}
 .h {{ font-weight: 900; font-size: 16px; border-top: 3px solid #000; border-bottom: 2px solid #000;
       padding: 3px 0; margin-top: 6px; }}
 .it {{ padding: 5px 0; border-bottom: 2px dashed #000; }}
 .n {{ font-weight: 900; font-size: 16px; line-height: 1.15; }}
 .p {{ display: flex; justify-content: space-between; align-items: baseline; font-size: 14px; }}
 .p b {{ font-size: 22px; font-weight: 900; white-space: nowrap; }}
 .x {{ font-size: 13px; }}
 .pie {{ margin-top: 8px; text-align: center; font-size: 15px; border-top: 3px solid #000; padding-top: 5px; }}
 .pie .w {{ font-size: 22px; font-weight: 900; }}
 @media print {{ .noprint {{ display: none; }} }}
</style></head><body>
<div class="noprint" style="margin-bottom:6px"><button onclick="window.print()">Imprimir</button></div>
<div class="t">QUÍMICA CRISTAL</div>
<div class="s">Lista mayorista · {hoy}<br/>Solo productos con stock · bidón con recambio
(vacío con tapa, o nuevo con cargo)</div>
{body}
<div class="pie"><b>Hacé tu pedido por WhatsApp</b><br/><span class="w">358 609 1684</span><br/>Te lo preparamos en el
día y te avisamos cuando está listo para retirar.</div>
<script>window.addEventListener('load', function () {{ setTimeout(function () {{ window.print(); }}, 300); }});</script>
</body></html>"""
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')])
