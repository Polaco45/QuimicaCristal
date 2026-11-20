# -*- coding: utf-8 -*-
"""v1.80 — Hoja imprimible para la caja: bidones de 20 L más vendidos con precio por bidón y
por litro, para que el mayorista elija sin ocupar a Guillermo (Joaco, 20/11/2026)."""
from markupsafe import escape

from odoo import fields, http
from odoo.http import request


def _money(v):
    return '${:,.0f}'.format(v or 0).replace(',', '.')


class CristalListaBidones(http.Controller):

    @http.route('/cristal/lista-bidones', type='http', auth='user')
    def lista_bidones(self, **kw):
        rows = request.env['product.product'].cristal_top_bidones(limit=24)
        hoy = fields.Date.context_today(request.env.user).strftime('%d/%m/%Y')
        body = ''.join(
            f"<tr><td>{escape(r['name'])}</td><td class='n'>{_money(r['price'])}</td>"
            f"<td class='n'>{_money(r['price_l'])}</td></tr>" for r in rows)
        html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Lista mayorista — bidones de 20 L</title>
<style>
 body {{ font-family: Arial, sans-serif; margin: 18px; color: #222; }}
 h1 {{ font-size: 20px; margin: 0 0 4px; }} .sub {{ font-size: 12px; color: #555; margin-bottom: 12px; }}
 table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
 th, td {{ border-bottom: 1px solid #ccc; padding: 6px 4px; text-align: left; }}
 th {{ background: #f39200; color: #fff; }} td.n, th.n {{ text-align: right; white-space: nowrap; }}
 .pie {{ margin-top: 14px; font-size: 13px; border: 2px solid #f39200; padding: 8px; }}
 @media print {{ .noprint {{ display: none; }} body {{ margin: 6mm; }} }}
</style></head><body>
<div class="noprint" style="margin-bottom:10px"><button onclick="window.print()">Imprimir</button></div>
<h1>Química Cristal — Lista mayorista en bidones de 20 L</h1>
<div class="sub">Los más vendidos · precios de Lista Mayorista al {hoy} · el bidón va con recambio
(vacío con tapa, o bidón nuevo con cargo)</div>
<table><thead><tr><th>Producto (bidón de 20 L)</th><th class="n">Precio bidón</th>
<th class="n">Precio por litro</th></tr></thead><tbody>{body}</tbody></table>
<div class="pie"><b>¿Querés la lista completa o hacer tu pedido?</b> Escribinos por WhatsApp al
<b>358 609 1684</b>. Te preparamos el pedido y te avisamos cuando está listo para retirar
(no se arma en el momento).</div>
<script>window.addEventListener('load', function () {{ setTimeout(function () {{ window.print(); }}, 300); }});</script>
</body></html>"""
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')])
