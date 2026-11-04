# -*- coding: utf-8 -*-
"""
Autotest de la ruta del camión.

Corre los criterios de aceptación de la ruta sobre los datos reales de la base
(staging), dentro de un SAVEPOINT que SIEMPRE se revierte: no deja partners,
órdenes, salidas ni mensajes creados. Se dispara desde un botón (Ruta del camión →
Autotest) y muestra el resultado caso por caso. tests/test_route.py corre los
mismos casos, así hay una sola fuente de verdad.
"""
import json
import logging
from datetime import date, datetime, time, timedelta

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class _SelftestRollback(Exception):
    """Fuerza el rollback del savepoint del autotest."""


class CristalAgentRouteSelftest(models.TransientModel):
    _name = 'cristal.agent.route.selftest'
    _description = 'Autotest de la ruta del camión'

    result_html = fields.Html(string="Resultado", readonly=True, sanitize=False)
    passed = fields.Integer(string="OK", readonly=True)
    failed = fields.Integer(string="Fallidos", readonly=True)

    def action_run(self):
        results = self.run_selftest()
        passed = sum(1 for _n, ok, _d in results if ok)
        rows = ''.join(
            f"<tr><td>{'✅' if ok else '❌'}</td><td><b>{name}</b></td>"
            f"<td>{detail}</td></tr>" for name, ok, detail in results)
        html = ("<table class='table table-sm'><thead><tr><th></th><th>Caso</th>"
                f"<th>Detalle</th></tr></thead><tbody>{rows}</tbody></table>")
        wiz = self.create({'result_html': html, 'passed': passed,
                           'failed': len(results) - passed})
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name,
            'res_id': wiz.id, 'view_mode': 'form', 'target': 'new',
            'name': f"Autotest ruta: {passed}/{len(results)} OK",
        }

    @api.model
    def run_selftest(self):
        """Devuelve [(caso, ok, detalle)]. Nada de lo que crea queda en la base."""
        results = []
        try:
            with self.env.cr.savepoint():
                self._run_all(results)
                raise _SelftestRollback()
        except _SelftestRollback:
            pass
        except Exception as e:  # el savepoint se rompió (p. ej. rollback interno)
            _logger.exception("Autotest de ruta abortado: %s", e)
            results.append(("Ejecución", False, f"Autotest abortado: {e}"))
            self.env.cr.rollback()
        self.env.invalidate_all()
        return results

    # ───────────────────────── Helpers ─────────────────────────
    def _case(self, results, name, fn):
        try:
            with self.env.cr.savepoint():
                detail = fn()
            results.append((name, True, detail or 'OK'))
        except AssertionError as e:
            results.append((name, False, str(e)))
        except Exception as e:
            results.append((name, False, f"Excepción: {e}"))

    def _utc_from_local(self, day, hour, minute=0):
        tz = pytz.timezone('America/Argentina/Cordoba')
        local_dt = tz.localize(datetime.combine(day, time(hour, minute)))
        return local_dt.astimezone(pytz.utc).replace(tzinfo=None)

    # ───────────────────────── Casos ─────────────────────────
    def _run_all(self, results):
        from ..services.tool_registry import ToolRegistry
        env = self.env
        Circuit = env['cristal.agent.circuit'].sudo()
        Dep = env['cristal.agent.route.departure'].sudo()
        SaleOrder = env['sale.order'].sudo()
        Partner = env['res.partner'].sudo()

        config = env['cristal.agent.config'].sudo().get_active()
        freight = config.route_freight_product_id or env['product.product'].sudo().search(
            [('default_code', '=', 'FLETE-ZONA')], limit=1)
        config.write({'enable_truck_route': True, 'route_freight_product_id': freight.id})
        so = Circuit.search([('name', '=', 'Sur-Oeste')], limit=1)
        este = Circuit.search([('name', '=', 'Este')], limit=1)
        if not (so and este and freight):
            results.append(("Preparación", False,
                            "Faltan los circuitos Sur-Oeste/Este o el producto de flete."))
            return

        # Salidas fijas para el caso del 29/09/2026 (idempotente).
        for circ, d in ((so, date(2026, 10, 14)), (este, date(2026, 10, 28))):
            dep = Dep.search([('circuit_id', '=', circ.id), ('date', '=', d)], limit=1)
            if not dep:
                dep = Dep.create({'circuit_id': circ.id, 'date': d})
            dep.state = 'preventa'
        # Hay que tener una salida abierta para los pedidos de hoy.
        Dep.generate_upcoming(weeks=12)

        product = env['product.product'].sudo().create({
            'name': 'ZZ Autotest Ruta', 'type': 'consu', 'list_price': 1.0, 'is_storable': False,
            'sale_ok': True, 'taxes_id': [(6, 0, [])]})
        cso = ToolRegistry.get('create_sale_order')
        gri = ToolRegistry.get('get_route_info')
        channel = config.internal_channel_id

        def mk_partner(name, city, cat=None, circuit=None):
            vals = {'name': f'ZZ Autotest {name}', 'city': city or False,
                    'mobile': '+5493580000000'}
            if cat:
                vals['category_id'] = [(4, cat.id)]
            p = Partner.create(vals)
            if circuit:
                p.truck_circuit_id = circuit.id
            return p

        def quote(partner, amount):
            return cso.execute(env=env, run=None, partner_id=partner.id, lines=[
                {'product_id': product.id, 'qty': 1, 'price_unit': amount}])

        def freight_lines(order):
            return order.order_line.filtered(lambda l: l.product_id == freight)

        next_dep = date.today() + timedelta(days=14)
        while next_dep.weekday() != 3:  # jueves (v1.54)
            next_dep += timedelta(days=1)

        # 1) Normalización
        def c_normalizacion():
            cases = [
                ('chajàn', 'circuit', 'Sur-Oeste', 'Chaján'),
                ('Chajén', 'circuit', 'Sur-Oeste', 'Chaján'),
                ('Vicuña Maquena', 'circuit', 'Sur-Oeste', 'Vicuña Mackenna'),
                ('Moldes', 'circuit', 'Sur-Oeste', 'Coronel Moldes'),
                ('GRAL CABRERA', 'circuit', 'Norte', 'General Cabrera'),
                ('adelia maria', 'circuit', 'Sur-Este', 'Adelia María'),
                ('Rio Cuarto', 'rio_cuarto', None, 'Río Cuarto'),
                ('Laboulaye', 'fuera_zona', None, 'Laboulaye'),
            ]
            for text, kind, circ, canon in cases:
                info = Circuit.classify_city(text)
                got_c = info['circuit'].name if info.get('circuit') else None
                assert (info['kind'], got_c, info['canonical']) == (kind, circ, canon), (
                    f"'{text}' → {info['kind']}/{got_c}/{info['canonical']} "
                    f"(esperado {kind}/{circ}/{canon})")
            return f"{len(cases)} localidades OK"
        self._case(results, "1. Normalización de localidades", c_normalizacion)

        # 2) Próxima salida al 29/09/2026
        def c_fechas():
            ref = self._utc_from_local(date(2026, 9, 29), 12)
            d = so.get_next_departure(ref)
            assert d and d.date == date(2026, 10, 14), f"Sampacho: {d.date if d else None}"
            cl = d.get_cutoff_local()
            assert (cl.date(), cl.hour, cl.minute) == (date(2026, 10, 12), 18, 0), (
                f"Cierre Sampacho: {cl}")
            d2 = este.get_next_departure(ref)
            assert d2 and d2.date == date(2026, 10, 28), f"Ucacha: {d2.date if d2 else None}"
            p = mk_partner('InfoSampacho', 'Sampacho')
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('zone') == 'ruta_camion' and gi.get('circuit') == 'Sur-Oeste', gi
            return "Sampacho → mié 14/10 (cierre lun 12/10 18 h); Ucacha → mié 28/10"
        self._case(results, "2. Próxima salida (29/09/2026)", c_fechas)

        # 3) Pedido en Sampacho: $60k / $80k / $120k
        def c_pedidos():
            p60 = mk_partner('S60', 'Sampacho')
            r = quote(p60, 60000)
            assert r.get('blocked_route_min') and r.get('order_created') is False, r
            assert not SaleOrder.search_count([('partner_id', '=', p60.id)]), (
                "$60.000 no debía crear orden")

            p80 = mk_partner('S80', 'Sampacho')
            r = quote(p80, 80000)
            assert r.get('ok') and r.get('route'), r
            order = SaleOrder.browse(r['order_id'])
            fl = freight_lines(order)
            assert order.state == 'draft', f"estado {order.state}"
            assert len(fl) == 1 and fl.price_unit == 9000 and fl.discount == 0, (
                f"flete: {[(l.price_unit, l.discount) for l in fl]}")
            dep = so.get_next_departure()
            assert order.route_departure_id == dep, "salida de la orden"
            assert order.commitment_date == dep.get_commitment_datetime(), (
                f"commitment_date {order.commitment_date}")
            local_commit = pytz.utc.localize(order.commitment_date).astimezone(
                pytz.timezone('America/Argentina/Cordoba'))
            assert local_commit.weekday() == 3, "la entrega no cae jueves"
            assert 'Ruta Sur-Oeste' in order.tag_ids.mapped('name'), "etiqueta de circuito"
            if channel:
                esc = env['mail.message'].sudo().search_count([
                    ('model', '=', 'discuss.channel'), ('res_id', '=', channel.id),
                    ('body', 'ilike', order.name)])
                assert esc, "no se escaló a Joaco"

            p120 = mk_partner('S120', 'Sampacho')
            gratis = max(120000, (config.route_free_shipping_from or 0) + 1000)
            r = quote(p120, gratis)
            order = SaleOrder.browse(r['order_id'])
            assert r.get('ok') and not freight_lines(order), f"${gratis:,.0f} no lleva flete"
            return (f"$60k no crea; $80k borrador + flete $9.000 + jueves + etiqueta + "
                    f"escalado; ${gratis:,.0f} sin flete")
        self._case(results, "3. Pedidos en Sampacho", c_pedidos)

        # 4) Mínimo y envío gratis SIN contar el flete
        def c_sin_flete():
            p = mk_partner('S95', 'Sampacho')
            r = quote(p, 95000)
            order = SaleOrder.browse(r['order_id'])
            assert freight_lines(order), "$95.000 debía llevar flete"
            assert order.amount_untaxed == 104000, f"total s/IVA {order.amount_untaxed}"
            assert r.get('product_subtotal') == 95000, r.get('product_subtotal')
            return "$95.000 → flete → total s/IVA $104.000, sigue con flete"
        self._case(results, "4. Umbrales sin contar el flete", c_sin_flete)

        # 5) Zona horaria: martes 17:59 entra, 18:01 pasa a la siguiente
        def c_timezone():
            tc = Circuit.create({'name': 'ZZ Autotest TZ', 'sequence': 99,
                                 'first_departure_date': next_dep})
            d1 = Dep.create({'circuit_id': tc.id, 'date': next_dep})
            d2 = Dep.create({'circuit_id': tc.id, 'date': next_dep + timedelta(days=28)})
            cl = d1.get_cutoff_local()
            assert (cl.weekday(), cl.hour, cl.minute) == (1, 18, 0), f"cierre local {cl}"
            cut = d1.get_preventa_cutoff()
            got1 = tc.get_next_departure(cut - timedelta(minutes=1))
            got2 = tc.get_next_departure(cut + timedelta(minutes=1))
            assert got1 == d1, f"17:59 → {got1.date if got1 else None}"
            assert got2 == d2, f"18:01 → {got2.date if got2 else None}"
            return f"cierre mar {cl.strftime('%d/%m')} 18:00 (Córdoba); 17:59 entra, 18:01 pasa"
        self._case(results, "5. Cierre de preventa y zona horaria", c_timezone)

        # 6) Rescate (Plan B)
        def c_rescate():
            rc_c = Circuit.create({'name': 'ZZ Autotest Rescate', 'sequence': 98,
                                   'first_departure_date': next_dep})
            courtesy = env['product.product'].sudo().create(
                {'name': 'ZZ Autotest Cortesía', 'type': 'consu', 'sale_ok': True})
            dep = Dep.create({'circuit_id': rc_c.id, 'date': next_dep, 'state': 'rescate',
                              'courtesy_product_id': courtesy.id})
            cl = dep.get_cutoff_local()
            assert (cl.weekday(), cl.hour) == (2, 12), f"cierre rescate {cl}"
            p = mk_partner('Rescate', 'ZZ Pueblo', circuit=rc_c)
            r = quote(p, 80000)
            order = SaleOrder.browse(r['order_id'])
            assert r.get('ok') and not freight_lines(order), "rescate $80k: sin flete"
            assert r.get('courtesy_product'), "no ofrece cortesía"
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('free_shipping_from') == 75000 and gi.get('rescate'), gi
            return "$80k sin flete (umbral $75.000), ofrece cortesía, cierre mar 12 h"
        self._case(results, "6. Rescate (Plan B)", c_rescate)

        # 7) Sin localidad
        def c_sin_ciudad():
            p = mk_partner('SinCiudad', False)
            r = quote(p, 80000)
            assert r.get('blocked_no_city') and r.get('needs_city'), r
            assert not SaleOrder.search_count([('partner_id', '=', p.id)]), "creó orden"
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('needs_city'), gi
            return "no cotiza y pide la localidad"
        self._case(results, "7. Cliente sin localidad", c_sin_ciudad)

        # 8) Río Cuarto nunca jueves (v1.54)
        def c_rio_cuarto():
            p = mk_partner('RC', 'Rio Cuarto')
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('zone') == 'rio_cuarto' and 'departure_date' not in gi, gi
            assert 'JUEVES' in gi.get('message_for_bot', ''), gi
            r = quote(p, 80000)
            order = SaleOrder.browse(r['order_id'])
            assert r.get('ok') and not r.get('route'), r
            assert 'jueves' in (r.get('route_note') or '').lower(), r.get('route_note')
            assert not order.commitment_date and not order.route_departure_id, (
                "a Río Cuarto no se le asigna salida de ruta")
            return "sin salida de ruta y aviso de NO jueves"
        self._case(results, "8. Río Cuarto nunca jueves", c_rio_cuarto)

        # 9) Backfill: la etiqueta manda, la ciudad solo si no hay etiqueta
        def c_backfill():
            cat = so.partner_category_id
            assert cat, "Sur-Oeste no tiene etiqueta de contacto (Ruta Sur-Oeste)"
            a = mk_partner('BackfillTag', 'Laboulaye', cat=cat)
            b = mk_partner('BackfillCity', 'Ucacha')
            Circuit.action_backfill_truck_circuits(partner_ids=[a.id, b.id])
            assert a.truck_circuit_id == so and cat in a.category_id, (
                f"con etiqueta: {a.truck_circuit_id.name}")
            assert b.truck_circuit_id == este, f"por ciudad: {b.truck_circuit_id.name}"
            return "etiqueta 35 + Laboulaye → Sur-Oeste; sin etiqueta + Ucacha → Este"
        self._case(results, "9. Backfill de circuitos", c_backfill)

        # ───────────────────── Reglas de oro (v1.33) ─────────────────────
        from ..services.helpers import date_context_ar, within_contact_hours
        tz = pytz.timezone('America/Argentina/Cordoba')

        # 10) Fecha de Argentina (no UTC)
        def c_fecha_ar():
            # Bug real: a las 21:26 del lunes 28/09 (00:26 UTC del 29) Claudio decía
            # "tu pedido sale esta mañana". En hora Argentina sigue siendo el 28.
            utc = pytz.utc.localize(datetime(2026, 9, 29, 0, 26))
            cal = date_context_ar(env, now=utc.astimezone(tz))
            assert cal['hoy'] == 'lunes 28/09/2026', cal['hoy']
            assert cal['manana'] == 'martes 29/09', cal['manana']
            assert cal['pasado'] == 'miércoles 30/09', cal['pasado']
            assert cal['hora'] == '21:26', cal['hora']
            real = date_context_ar(env)
            assert real['now'].date() == datetime.now(tz).date(), "hoy no es hora Argentina"
            return f"00:26 UTC del 29/09 → HOY {cal['hoy']} 21:26; mañana {cal['manana']}"
        self._case(results, "10. Fecha y día de Argentina", c_fecha_ar)

        # 11) Ventana para iniciar mensajes (7:30 a 21:30, todos los días)
        def c_horario():
            cfg = env['cristal.agent.config'].sudo().get_active()
            cfg.write({'work_hours_start': 7.5, 'work_hours_end': 21.5})
            day = date(2026, 10, 4)  # domingo: también vale
            checks = [((7, 29), False), ((7, 30), True), ((21, 29), True),
                      ((21, 30), False), ((0, 57), False), ((5, 24), False)]
            for (h, m), expected in checks:
                now = tz.localize(datetime.combine(day, time(h, m)))
                got = within_contact_hours(env, now=now)
                assert got == expected, f"{h:02d}:{m:02d} → {got} (esperado {expected})"
            return "7:29 no · 7:30 sí · 21:29 sí · 21:30 no · 00:57 no · 05:24 no"
        self._case(results, "11. Horario para iniciar mensajes", c_horario)

        # 12) Bidones: aviso siempre, cobro correcto y precio fijo
        def c_bidones():
            cfg = env['cristal.agent.config'].sudo().get_active()
            bidon = cfg.bidon_product_id or env['product.product'].sudo().search(
                [('default_code', '=', 'DA0355')], limit=1)
            assert bidon, "no hay producto de bidón (DA0355)"
            cfg.write({'bidon_product_id': bidon.id, 'bidon_price': 3500.0})
            granel = env['product.product'].sudo().create({
                'name': 'ZZ Autotest Lavandina a granel', 'type': 'consu',
                'sale_ok': True, 'taxes_id': [(6, 0, [])]})
            p = mk_partner('Bidones', 'Rio Cuarto')
            line = {'product_id': granel.id, 'qty': 40, 'price_unit': 2000}
            # a) No se sabe si tiene vacíos para canjear → avisa y pide preguntar
            r = cso.execute(env=env, run=None, partner_id=p.id, lines=[line])
            assert r.get('ok'), r
            b = r.get('bidones') or {}
            assert b.get('needed') == 2 and not b.get('answered'), b
            summ = r.get('client_summary', '')
            assert 'bidones de 20 L' in summ and '$3.500' in summ, summ
            assert 'preguntale' in (r.get('bidones_note') or '').lower(), r.get('bidones_note')
            # b) Le faltan 2 (y aunque venga con 20% OFF, el bidón no se descuenta)
            r = cso.execute(env=env, run=None, partner_id=p.id, lines=[line],
                            bidones_nuevos=2, discount_percent=20)
            order = SaleOrder.browse(r['order_id'])
            bl = order.order_line.filtered(lambda l: l.product_id == bidon)
            assert len(bl) == 1 and bl.product_uom_qty == 2 and bl.price_unit == 3500 \
                and bl.discount == 0, f"bidón: {[(l.product_uom_qty, l.price_unit, l.discount) for l in bl]}"
            assert '2 nuevo' in r.get('client_summary', ''), r.get('client_summary')
            # c) Tiene todos los vacíos para el canje → se saca el cargo
            r = cso.execute(env=env, run=None, partner_id=p.id, lines=[line], bidones_nuevos=0)
            order = SaleOrder.browse(r['order_id'])
            assert not order.order_line.filtered(lambda l: l.product_id == bidon), "quedó el cargo"
            assert 'de recambio' in r.get('client_summary', ''), r.get('client_summary')
            # d) Bajo el mínimo también avisa los bidones (caso real de staging)
            p2 = mk_partner('BidonesChico', 'Rio Cuarto')
            r = cso.execute(env=env, run=None, partner_id=p2.id, lines=[
                {'product_id': granel.id, 'qty': 20, 'price_unit': 1000}])
            assert r.get('blocked_min_compra') and 'BIDONES' in (r.get('bidones_note') or ''), r
            return ("avisa y pregunta · 2 nuevos a $3.500 sin 20% · con vacíos no se cobra "
                    "· también bajo el mínimo")
        self._case(results, "12. Bidones de 20 L", c_bidones)

        # 13) Sanitizador de tono (muletillas en medio del mensaje)
        def c_tono():
            from ..services.helpers import sanitize_tone
            cases = [
                ("Hola, soy Claudio de Química Cristal. Perfecto, te doy los precios:",
                 "Hola, soy Claudio de Química Cristal. Te doy los precios:"),
                ("Veo que tiene una despensa — perfecto, te atendemos.",
                 "Veo que tiene una despensa — te atendemos."),
                ("El jabón es excelente, se lo recomiendo.",
                 "El jabón es excelente, se lo recomiendo."),
                ("Soy Claudio de Química Cristal. \U0001F44B Perfecto, tengo todo.",
                 "Soy Claudio de Química Cristal. \U0001F44B Tengo todo."),
            ]
            for src, expected in cases:
                got = sanitize_tone(src)
                assert got == expected, f"'{src}' → '{got}'"
            return "saca 'Perfecto' tras punto y tras guión; respeta 'es excelente'"
        self._case(results, "13. Sanitizador de tono", c_tono)

        # 14) Aviso de bidones garantizado al enviar
        def c_aviso_bidones():
            from ..services.helpers import ensure_bidones_notice
            falta = ensure_bidones_notice(
                env, 0, "<p>Sobre los 20 L de detergente: ¿cuál preferís?</p>")
            assert 'bidones de 20 L' in falta and '$3.500' in falta, falta
            nada = "<p>Te paso la lista de precios.</p>"
            assert ensure_bidones_notice(env, 0, nada) == nada, "agregó sin hablar de granel"
            ya = "<p>Son 40 L de lavandina: van en 2 bidones de recambio.</p>"
            assert ensure_bidones_notice(env, 0, ya) == ya, "duplicó el aviso"
            return "agrega el aviso si habla de granel sin bidones; no duplica ni ensucia"
        self._case(results, "14. Aviso de bidones al enviar", c_aviso_bidones)

        # ───────────────────── Precios (v1.34) ─────────────────────
        # 15) "jabón líquido" trae los jabones a granel del catálogo mayorista
        def c_busqueda_jabon():
            sp = ToolRegistry.get('search_products')
            r = sp.execute(env=env, run=None, query='jabón líquido')
            names = [p['name'] for p in r.get('products') or []]
            granel = [n for n in names if 'granel' in n.lower() and 'jabon b/e' in n.lower()]
            assert granel, f"no trajo jabones a granel: {names[:6]}"
            assert names[0] in granel or r['products'][0]['is_mayorista_catalog'], (
                f"el catálogo no va primero: {names[:3]}")
            return f"trae {len(granel)} jabones B/E a granel primero ({granel[0]})"
        self._case(results, "15. Búsqueda 'jabón líquido'", c_busqueda_jabon)

        # 16) Control de precios al enviar (mensaje real del 02/10)
        def c_control_precios():
            import json as _json
            from ..services.helpers import verify_prices
            log = [{'tool_name': 'search_products', 'output': {'products': [
                {'name': 'Jabon Liquido Ariel Platinum x 3 Lts', 'price': 10512},
                {'name': 'Detergente Magistral Limón a granel', 'price': 720},
                {'name': 'Detergente Magistral Marina a  granel', 'price': 720},
                {'name': 'Jabon B/E Extra c/Desmanchador y sauv a granel', 'price': 600},
            ]}}]
            run = env['cristal.agent.run'].sudo().create({
                'trigger': 'whatsapp_message', 'tool_calls_log': _json.dumps(log)})
            real = ("<p><b>JABONES LÍQUIDOS (a granel):</b></p><p>• Jabon B/E Ariel: $720/L<br>"
                    "• Jabon B/E Skip: $720/L</p><p>• Detergente Magistral Limón: $720/L<br>"
                    "• Detergente Magistral Marina: $720/L</p>")
            bad = verify_prices(env, run, real)
            assert len(bad) == 2 and 'Ariel' in bad[0] and 'Skip' in bad[1], bad
            ok_msgs = [
                "<p>• Detergente Magistral Limón: $720/L</p>",
                "<p>Con el 20% le queda el Magistral Limón a $576 el litro.</p>",
                "<p>Te paso el precio: $408/L</p>",
            ]
            for msg in ok_msgs:
                assert not verify_prices(env, run, msg), f"bloqueó de más: {msg}"
            return "bloquea Ariel/Skip a $720 (inventados); deja Magistral $720, el 20% y frases sin producto"
        self._case(results, "16. Control de precios al enviar", c_control_precios)

        # ───────────────────── Ruta de los jueves (v1.54) ─────────────────────
        # 17) Todas las salidas abiertas de los circuitos reales caen jueves, y
        #     Río Cuarto no tiene reparto ese día.
        def c_jueves():
            from ..services.helpers import rc_no_delivery_day, route_weekday
            real = Circuit.search([('active', '=', True), ('name', 'not ilike', 'ZZ Autotest')])
            assert real and all(c.weekday == '3' for c in real), (
                f"circuitos: {[(c.name, c.weekday) for c in real]}")
            deps = Dep.search([('circuit_id', 'in', real.ids),
                               ('date', '>=', date.today()),
                               ('state', 'in', ('preventa', 'rescate'))])
            # Una salida que el equipo movió a mano (ej. Sur-Oeste al viernes 23/10)
            # es válida: solo se exige jueves a las que generó el sistema.
            moved = deps.filtered(lambda d: d.date.weekday() != 3 and d.write_uid.id != 1)
            bad = deps.filtered(lambda d: d.date.weekday() != 3) - moved
            assert deps and not bad, f"salidas que no caen jueves: {bad.mapped('name')}"
            assert rc_no_delivery_day(env) == 'jueves', rc_no_delivery_day(env)
            assert route_weekday(env) == 'jueves', route_weekday(env)
            extra = f" (movidas a mano: {', '.join(moved.mapped('name'))})" if moved else ""
            return (f"{len(deps)} salidas abiertas, las generadas caen jueves{extra}; "
                    f"RC sin reparto el jueves")
        self._case(results, "17. Ruta de los jueves", c_jueves)
        # ───────────────────── Sin muestras gratis (v1.34.1) ─────────────────────
        # 18) Joaco sacó la promo de 3 muestras gratis con compras de +$60.000: la
        #     herramienta no existe más y el cotizador no la sugiere.
        def c_sin_muestras():
            assert ToolRegistry.get('add_free_samples') is None, "add_free_samples sigue registrada"
            p = mk_partner('PromoOff', 'Rio Cuarto')
            r = quote(p, 90000)
            assert r.get('ok'), r
            assert 'samples_hint' not in r, "el cotizador sigue sugiriendo muestras"
            txt = str(r).lower()
            assert 'muestras gratis' not in txt and 'add_free_samples' not in txt, (
                "la respuesta del cotizador sugiere muestras")
            order = SaleOrder.browse(r['order_id'])
            assert not order.order_line.filtered(
                lambda l: 'muestra' in (l.product_id.name or '').lower()), "la orden trae muestras"
            return "sin herramienta de muestras; pedido de $90k sin muestras ni aviso"
        self._case(results, "18. Sin muestras gratis", c_sin_muestras)

        # ═════════════════ Correcciones del 13/10 (v1.36) ═════════════════
        # 19) 20% de primera compra: SOLO Río Cuarto / Las Higueras.
        def c_veinte_zona():
            from ..services.helpers import first_purchase_discount_status
            prod = env['product.product'].sudo().create({
                'name': 'ZZ Autotest Lista', 'type': 'consu', 'list_price': 200000.0, 'is_storable': False,
                'sale_ok': True, 'taxes_id': [(6, 0, [])]})
            mayorista_pl = env['product.pricelist'].sudo().search(
                [('name', '=', 'Lista Mayorista')], limit=1)
            env['product.pricelist.item'].sudo().create({
                'pricelist_id': mayorista_pl.id, 'applied_on': '0_product_variant',
                'product_id': prod.id, 'product_tmpl_id': prod.product_tmpl_id.id,
                'compute_price': 'fixed', 'fixed_price': 160000.0})
            ps = mk_partner('Veinte Sampacho', 'Sampacho')
            assert first_purchase_discount_status(env, ps)[0] == 'blocked'
            r = cso.execute(env=env, run=None, partner_id=ps.id, discount_percent=20,
                            lines=[{'product_id': prod.id, 'qty': 1}])
            assert r.get('zone_discount_blocked'), f"Sampacho: no bloqueó el 20% ({r})"
            if r.get('order_id'):
                o = SaleOrder.browse(r['order_id'])
                assert not o.order_line.filtered(lambda l: l.discount), "Sampacho con descuento"
            prc = mk_partner('Veinte RC', 'Rio Cuarto')
            assert first_purchase_discount_status(env, prc)[0] == 'allowed'
            r = cso.execute(env=env, run=None, partner_id=prc.id, discount_percent=20,
                            lines=[{'product_id': prod.id, 'qty': 1}])
            assert r.get('ok') and not r.get('zone_discount_blocked'), r
            o = SaleOrder.browse(r['order_id'])
            assert o.order_line.filtered(lambda l: l.product_id == prod).discount == 20, (
                "Río Cuarto sin el 20%")
            pf = mk_partner('Veinte Laboulaye', 'Laboulaye')
            assert first_purchase_discount_status(env, pf)[0] == 'blocked'
            pn = mk_partner('Veinte SinCiudad', False)
            assert first_purchase_discount_status(env, pn)[0] == 'unknown'
            return "Sampacho sin 20% · Río Cuarto con 20% · Laboulaye bloqueado · sin ciudad: no se ofrece"
        self._case(results, "19. 20% solo Río Cuarto", c_veinte_zona)

        # 20) Localidades mal escritas: alias + parecido (pregunta, no fuera de zona).
        def c_localidades():
            casos = [('Olver', 'circuit', 'Holmberg'), ('olmberg', 'circuit', 'Holmberg'),
                     ('Holver', 'circuit', 'Holmberg'), ('Moldes', 'circuit', 'Coronel Moldes'),
                     ('Cnel Moldes', 'circuit', 'Coronel Moldes'),
                     ('Vicuña', 'circuit', 'Vicuña Mackenna'),
                     ('Mackena', 'circuit', 'Vicuña Mackenna'),
                     ('Gral Cabrera', 'circuit', 'General Cabrera'),
                     ('Deheza', 'circuit', 'General Deheza'),
                     ('La Carlota', 'circuit', 'La Carlota'),
                     ('Adelia', 'circuit', 'Adelia María'),
                     ('Rio IV', 'rio_cuarto', 'Río Cuarto'),
                     ('Laboulaye', 'fuera_zona', None)]
            for text, kind, canon in casos:
                info = Circuit.classify_city(text)
                got = info['canonical'] if info['kind'] != 'fuera_zona' else None
                assert (info['kind'], got) == (kind, canon), f"'{text}' → {info['kind']}/{got}"
            maybe = Circuit.classify_city('Berrotaram')
            assert maybe['kind'] == 'maybe' and maybe['candidate'] == 'Berrotarán', maybe
            p = mk_partner('Tipeo', 'Berrotaram')
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('needs_confirmation') and gi.get('candidate_city') == 'Berrotarán', gi
            r = cso.execute(env=env, run=None, partner_id=p.id,
                            lines=[{'product_id': product.id, 'qty': 1, 'price_unit': 90000}])
            assert r.get('needs_city_confirmation'), f"cotizó con localidad dudosa: {r}"
            p2 = mk_partner('TipeoUpd', False)
            up = ToolRegistry.get('update_partner').execute(
                env=env, run=None, partner_id=p2.id, city='Berrotaram')
            assert up.get('needs_confirmation') and p2.agent_zone != 'fuera_zona', up
            fz = env['res.partner.category'].sudo().search([('name', '=', 'Fuera de zona')], limit=1)
            assert not fz or fz not in p2.category_id, "lo etiquetó Fuera de zona"
            return "Olver/olmberg/Moldes/Vicuña/Gral Cabrera… OK · Laboulaye fuera · 'Berrotaram' → pregunta"
        self._case(results, "20. Localidades mal escritas", c_localidades)

        # 21) Feriados y días cerrados.
        def c_feriados():
            from ..services.helpers import (closed_day_reason, business_status,
                                            next_business_day, attention_status_line)
            tz = pytz.timezone('America/Argentina/Cordoba')
            assert 'feriado' in (closed_day_reason(env, date(2026, 10, 12)) or ''), "12/10"
            assert closed_day_reason(env, date(2026, 10, 13)) is None, "13/10 es hábil"
            assert closed_day_reason(env, date(2026, 10, 18)) == 'domingo'
            st = business_status(env, tz.localize(datetime(2026, 10, 12, 10, 0)))
            assert st['closed_today'] and not st['open_now'], st
            assert st['confirm_when'] == 'el martes 13/10', st['confirm_when']
            line = attention_status_line(env, tz.localize(datetime(2026, 10, 12, 10, 0)))
            assert 'HOY NO ATENDEMOS' in line, line
            st = business_status(env, tz.localize(datetime(2026, 10, 16, 20, 30)))  # vie 20:30
            assert not st['open_now'] and st['confirm_when'] == 'el sábado 17/10', st
            st = business_status(env, tz.localize(datetime(2026, 10, 13, 10, 0)))  # mar 10 h
            assert st['open_now'] and st['confirm_when'] == 'hoy', st
            config.closed_dates = "2026-10-14 Inventario"
            assert closed_day_reason(env, date(2026, 10, 14)) == 'Inventario'
            assert next_business_day(env, date(2026, 10, 13)) == date(2026, 10, 15)
            config.closed_dates = False
            hc = Circuit.create({'name': 'ZZ Autotest Feriado', 'sequence': 97,
                                 'first_departure_date': date(2026, 12, 8)})
            Dep.create({'circuit_id': hc.id, 'date': date(2026, 12, 8)})
            ph = mk_partner('Feriado', 'ZZ Pueblo', circuit=hc)
            gi = gri.execute(env=env, run=None, partner_id=ph.id)
            assert gi.get('departure_on_closed_day'), f"salida en feriado sin aviso: {gi}"
            return ("12/10 feriado → 'hoy no atendemos', confirma el martes 13/10 · vie 20:30 "
                    "→ sábado · config · salida 8/12 no se promete")
        self._case(results, "21. Feriados y días cerrados", c_feriados)

        # 22) Controles al enviar: 20%, "Joaquín coordina", minutos, entrega RC.
        def c_controles_envio():
            import json as _json
            from ..services.send_guards import apply_send_guards
            ch = config.internal_channel_id.id
            pz = mk_partner('GuardSampacho', 'Sampacho')
            prc = mk_partner('GuardRC', 'Rio Cuarto')
            run = env['cristal.agent.run'].sudo().create({
                'trigger': 'whatsapp_message', 'partner_id': pz.id})

            def guard(body, partner):
                return apply_send_guards(env, run, ch, body, partner)

            _b, err = guard("<p>Le paso la lista. Su primer pedido lleva 20% OFF.</p>", pz)
            assert err and err['guard'] == 'first_purchase_zone', err
            _b, err = guard("<p>Le paso la lista. Su primer pedido lleva 20% OFF.</p>", prc)
            assert not err, f"bloqueó el 20% a Río Cuarto: {err}"
            _b, err = guard("<p>Para su localidad el envío lo coordina Joaquín.</p>", pz)
            assert err and err['guard'] == 'coordina_envio', err
            _b, err = guard("<p>Dejame chequear con Joaco, te aviso en un minuto.</p>", pz)
            assert err and err['guard'] == 'promesa_minutos', err
            _b, err = guard("<p>Te lo llevamos el lunes 19/10 a las 11 h.</p>", prc)
            assert err and err['guard'] == 'entrega_rc', err
            _b, err = guard("<p>Pasamos por Sampacho el jueves 12/11; tomamos pedidos "
                            "hasta el martes 10/11 a las 18 h.</p>", pz)
            assert not err, f"bloqueó la fecha de la ruta: {err}"
            _b, err = guard("<p>¿Cuántos litros llevás hoy?</p>", prc)
            assert not err, f"bloqueó una pregunta común: {err}"
            # 2da vez en la misma corrida: corrige y manda.
            run.tool_calls_log = _json.dumps([{'tool_name': 'send_whatsapp', 'output': {
                'error': 'x', 'guard': 'first_purchase_zone'}}])
            body, err = guard("<p>Le paso la lista. Su primer pedido lleva 20% OFF. "
                              "¿Le armo la cotización?</p>", pz)
            assert not err and '20%' not in body and 'cotización' in body, body
            return ("20% zona · 'Joaquín coordina' · 'en un minuto' · entrega RC: bloqueados; "
                    "ruta y preguntas OK; 2da vez corrige")
        self._case(results, "22. Controles al enviar", c_controles_envio)

        # 23) Una escalación por pedido (se actualiza, no se duplica).
        def c_escalacion_unica():
            esc = ToolRegistry.get('escalate_to_joaco')
            ch = config.internal_channel_id
            assert ch, "sin canal interno"
            pe = mk_partner('Escala', 'Rio Cuarto')
            Msg = env['mail.message'].sudo()
            n0 = Msg.search_count([('model', '=', 'discuss.channel'), ('res_id', '=', ch.id)])
            r1 = esc.execute(env=env, run=None, related_partner_id=pe.id,
                             message="PEDIDO PARA CONFIRMAR — ZZ Escala. Cotización S99999, total $90.000.")
            r2 = esc.execute(env=env, run=None, related_partner_id=pe.id,
                             message="Ruta: el cliente sumó 20 L de lavandina a S99999.")
            r3 = esc.execute(env=env, run=None, related_partner_id=pe.id,
                             message="Pregunta si hay gamuzas.")
            n1 = Msg.search_count([('model', '=', 'discuss.channel'), ('res_id', '=', ch.id)])
            assert r1.get('ok') and r2.get('updated_existing') and r3.get('updated_existing'), (
                r1, r2, r3)
            assert n1 - n0 == 1, f"se crearon {n1 - n0} mensajes (esperado 1)"
            body = Msg.browse(r2['escalation_message_id']).body
            assert 'lavandina' in body and 'gamuzas' in body, "no agregó las novedades"
            return "3 escalaciones del mismo pedido/cliente → 1 mensaje actualizado"
        self._case(results, "23. Una escalación por pedido", c_escalacion_unica)

        # 24) Duplicados y adjuntos inventados (canal 2997: mismo texto 2 veces).
        def c_duplicados():
            import json as _json
            from ..services.send_guards import check_attachments, duplicate_recent
            run = env['cristal.agent.run'].sudo().create({'trigger': 'whatsapp_message'})
            att = env['ir.attachment'].sudo().create({'name': 'ZZ autotest.pdf', 'raw': b'%PDF'})
            err = check_attachments(env, run, [att.id])
            assert err and err['guard'] == 'attachment', "aceptó un adjunto que no generó ninguna tool"
            run.tool_calls_log = _json.dumps([{'tool_name': 'generate_pricelist_pdf',
                                               'output': {'attachment_id': att.id}}])
            assert check_attachments(env, run, [att.id]) is None, "rechazó el PDF de la tool"
            ch = config.internal_channel_id.id
            bot = config.bot_partner_id.id if config.bot_partner_id else 2
            text = "<p>ZZ autotest: Hola Carla, te paso la lista mayorista.</p>"
            assert not duplicate_recent(env, ch, text, bot)
            env['mail.message'].sudo().with_context(from_cristal_agent=True).create({
                'author_id': bot, 'body': text, 'message_type': 'comment',
                'model': 'discuss.channel', 'res_id': ch})
            assert duplicate_recent(env, ch, text, bot), "no detectó el duplicado"
            return "adjunto inventado → bloqueado · PDF de la tool OK · mismo texto en segundos → no se repite"
        self._case(results, "24. Duplicados y adjuntos", c_duplicados)

        # 25) Sin stock: la línea no se carga y se ofrecen alternativas.
        def c_sin_stock():
            categ = env['product.category'].sudo().create({'name': 'ZZ Autotest Categ'})
            sin = env['product.product'].sudo().create({
                'name': 'ZZ Aromatizante sin stock', 'type': 'consu', 'is_storable': True,
                'list_price': 5000.0, 'sale_ok': True, 'categ_id': categ.id})
            alt = env['product.product'].sudo().create({
                'name': 'ZZ Aromatizante a granel', 'type': 'consu',
                'list_price': 5000.0, 'sale_ok': True, 'categ_id': categ.id})
            p = mk_partner('Stock', 'Rio Cuarto')
            r = cso.execute(env=env, run=None, partner_id=p.id, lines=[
                {'product_id': sin.id, 'qty': 2},
                {'product_id': product.id, 'qty': 1, 'price_unit': 90000}])
            assert r.get('ok'), r
            o = SaleOrder.browse(r['order_id'])
            assert sin not in o.order_line.mapped('product_id'), "cargó el producto sin stock"
            ns = r.get('no_stock_lines') or []
            assert ns and any(a['product_id'] == alt.id for a in ns[0]['alternativas']), ns
            assert 'FALTA DE STOCK' in (r.get('no_stock_note') or ''), r.get('no_stock_note')
            return "producto sin stock no se carga; ofrece alternativa del mismo tipo"
        self._case(results, "25. Productos sin stock", c_sin_stock)

        # 26) Cliente que no entiende: mensaje corto + escalar.
        def c_no_entiende():
            from ..services import send_guards as sg
            assert sg._RE_NO_ENTIENDE.search("no entiendo nada")
            assert sg._RE_PIDE_AUDIO.search("me podés mandar un audio?")
            assert sg._RE_PIDE_AUDIO.search("llamame por favor")
            original = sg.confusion_signal
            sg.confusion_signal = lambda *a, **k: (2, False)
            try:
                largo = "<p>" + "Le explico cómo funciona la ruta del camión. " * 8 + "</p>"
                _b, err = sg.apply_send_guards(env, None, 0, largo, None)
                assert err and err['guard'] == 'cliente_no_entiende', err
                _b, err = sg.apply_send_guards(
                    env, None, 0, "<p>Le pido a Joaquín que lo llame.</p>", None)
                assert not err, err
            finally:
                sg.confusion_signal = original
            return "2 'no entiendo' o pedido de audio → bloquea textos largos y pide escalar"
        self._case(results, "26. Cliente que no entiende", c_no_entiende)

        # 27) Modelos: Haiku 5.5 base y Sonnet 5.5 avanzado (v1.42), sin temperature y
        # con esfuerzo; precios correctos.
        def c_modelo():
            from ..services.claude_client import _is_modern_model
            assert _is_modern_model('claude-sonnet-5-5') and _is_modern_model('claude-opus-5-5')
            assert _is_modern_model('claude-haiku-5-5')
            assert not _is_modern_model('claude-haiku-4-5-20251001')
            Run = env['cristal.agent.run']
            p = Run._prices_for_model('claude-sonnet-5-5')
            assert (p['in'], p['out'], p['cr']) == (2.0, 10.0, 0.20), p
            p = Run._prices_for_model('claude-haiku-5-5')
            assert (p['in'], p['out'], p['cr']) == (0.10, 0.50, 0.01), p
            assert Run._prices_for_model('claude-haiku-4-5-20251001')['in'] == 1.0
            # v1.43: no se exige un modelo fijo (Odoo.sh corre este autotest en cada
            # build y descartaba builds si alguien cambiaba el modelo en la config).
            assert config.anthropic_model, "sin modelo base configurado"
            assert config.anthropic_effort in ('low', 'medium', 'high')
            assert config.max_tokens >= 16000, config.max_tokens
            return (f"base {config.anthropic_model} · avanzado {config.anthropic_model_complex}"
                    f" · esfuerzo {config.anthropic_effort} · max_tokens {config.max_tokens} · "
                    f"precios Haiku 5.5 y Sonnet 5.5 OK")
        self._case(results, "27. Modelos Haiku 5.5 / Sonnet 5.5", c_modelo)

        # ═════════════════ Envío sin cargo desde config (v1.37) ═════════════════
        free_from = config.route_free_shipping_from

        # 28) Umbral: free_from - 1 → flete; free_from → sin flete. Base: todo menos flete.
        def c_umbral_envio():
            pa = mk_partner('Umbral A', 'Sampacho')
            r = quote(pa, free_from - 1)
            o = SaleOrder.browse(r['order_id'])
            fl = freight_lines(o)
            assert r.get('ok') and len(fl) == 1 and fl.price_unit == config.route_freight_amount, (
                f"${free_from - 1:,.0f} debía llevar flete: {r.get('route_note')}")
            pb = mk_partner('Umbral B', 'Sampacho')
            r = quote(pb, free_from)
            o = SaleOrder.browse(r['order_id'])
            assert r.get('ok') and not freight_lines(o), f"${free_from:,.0f} no lleva flete"
            # Base: solo productos — ni el flete ni los bidones nuevos suman.
            bidon = config.bidon_product_id
            assert bidon, "falta el producto bidón en la config"
            o.write({'order_line': [(0, 0, {'product_id': bidon.id, 'product_uom_qty': 2,
                                            'price_unit': 3500.0})]})
            base = o._cristal_shipping_base(config)
            assert base == free_from, f"base {base} (esperado {free_from}: sin bidones)"
            pc = mk_partner('Umbral C', 'Sampacho')
            r = quote(pc, free_from - 5000)
            o = SaleOrder.browse(r['order_id'])
            o.write({'order_line': [(0, 0, {'product_id': bidon.id, 'product_uom_qty': 2,
                                            'price_unit': 3500.0})]})
            freight, base = o._cristal_apply_route_freight(config, free_from)
            assert freight and len(freight_lines(o)) == 1, (
                f"${free_from - 5000:,.0f} + 2 bidones: los bidones no suman, debía llevar flete")
            return (f"${free_from - 1:,.0f} → flete ${config.route_freight_amount:,.0f} · "
                    f"${free_from:,.0f} → sin flete · los bidones no suman (como el mínimo)")
        self._case(results, "28. Envío sin cargo desde la config", c_umbral_envio)

        # 29) Envío sin cargo acordado: nunca flete, ni al re-cotizar; Claudio no lo toca.
        def c_envio_acordado():
            p = mk_partner('Acordado', 'Sampacho')
            r = quote(p, 120000)
            o = SaleOrder.browse(r['order_id'])
            assert freight_lines(o), "$120.000 sin acuerdo debía llevar flete"
            o.write({'route_free_shipping_granted': True})
            assert not freight_lines(o), "al marcar el acuerdo no se sacó el flete"
            r2 = cso.execute(env=env, run=None, partner_id=p.id, lines=[
                {'product_id': product.id, 'qty': 1, 'price_unit': 120000},
                {'product_id': product2.id, 'qty': 1, 'price_unit': 5000}])
            o2 = SaleOrder.browse(r2['order_id'])
            assert o2 == o, "no re-usó el borrador"
            assert r2.get('ok') and not freight_lines(o2), (
                f"re-cotizado con el acuerdo y $125.000: no debía llevar flete ({r2.get('route_note')})")
            o2.with_context(from_cristal_agent=True).write({'route_free_shipping_granted': False})
            assert o2.route_free_shipping_granted, "Claudio pudo sacar el envío acordado"
            return "$120.000 con acuerdo → sin flete, también al re-cotizar; Claudio no lo puede cambiar"
        product2 = env['product.product'].sudo().create({
            'name': 'ZZ Autotest Ruta 2', 'type': 'consu', 'list_price': 1.0,
            'is_storable': False, 'sale_ok': True, 'taxes_id': [(6, 0, [])]})
        self._case(results, "29. Envío sin cargo acordado", c_envio_acordado)

        # 30) Upsell al umbral: cuánto falta + UNA opción, solo promos vigentes.
        def c_upsell_umbral():
            env['cristal.agent.offer'].sudo().create({
                'name': 'ZZ Promo 5+1 suavizante', 'description': 'ZZ autotest',
                'offer_type': 'other', 'valid_from': date.today(),
                'valid_until': date.today(), 'active': True, 'applies_to_levels': 'all',
                'priority': 99})
            p = mk_partner('Upsell', 'Sampacho')
            r = quote(p, 100000)
            up = r.get('free_shipping_upsell') or ''
            falta = '${:,.0f}'.format(free_from - 100000).replace(',', '.')
            assert falta in up and 'ZZ Promo 5+1 suavizante' in up, up
            assert 'UNA sola opción' in up and 'NUNCA inventes' in up, up
            assert 'Kit Cloro' not in up, "sugirió una promo de consumidor final"
            return f"$100.000 → 'le faltan {falta}', sugiere UNA opción de las promos vigentes"
        self._case(results, "30. Upsell al envío sin cargo", c_upsell_umbral)

        # ═════════════════ Retiro en planta sin mínimo (v1.38) ═════════════════
        # 31) Caso Valeria: 1 bidón para retirar → se cotiza sin mínimo ni flete.
        def c_retiro_sin_minimo():
            def q(partner, amount, mode=None):
                kw = {'delivery_mode': mode} if mode else {}
                return cso.execute(env=env, run=None, partner_id=partner.id, lines=[
                    {'product_id': product.id, 'qty': 1, 'price_unit': amount}], **kw)
            p1 = mk_partner('Retiro RC', 'Rio Cuarto')
            r = q(p1, 13120, 'retiro')
            assert r.get('ok') and not r.get('blocked_min_compra') and not r.get('upsell'), r
            o = SaleOrder.browse(r['order_id'])
            assert o.cristal_delivery_mode == 'retiro', o.cristal_delivery_mode
            assert 'RETIRO EN PLANTA' in (r.get('route_note') or ''), r.get('route_note')
            p2 = mk_partner('Envio RC', 'Rio Cuarto')
            r = q(p2, 13120)
            assert r.get('blocked_min_compra'), "con envío $13.120 debía frenar por el mínimo"
            assert "delivery_mode='retiro'" in r.get('message_for_bot', ''), "no ofrece el retiro"
            p3 = mk_partner('Retiro Sampacho', 'Sampacho')
            r = q(p3, 30000, 'retiro')
            o = SaleOrder.browse(r['order_id']) if r.get('order_id') else SaleOrder
            assert r.get('ok') and not r.get('blocked_route_min'), r
            assert not freight_lines(o) and not o.route_departure_id, "retiro con flete o salida"
            p4 = mk_partner('Retiro sin ciudad', False)
            r = q(p4, 13120, 'retiro')
            assert r.get('ok') and not r.get('needs_city'), r
            return ("RC 1 bidón ($13.120) retirando → se cotiza · con envío → mínimo + ofrece "
                    "retiro · Sampacho $30.000 retirando → sin mínimo, flete ni salida · "
                    "sin localidad retirando → OK")
        self._case(results, "31. Retiro en planta sin mínimo", c_retiro_sin_minimo)

        # ═════════════════ Ventana cerrada → plantilla (v1.39) ═════════════════
        # 32) Caso Margarita: seguimiento con la ventana cerrada sale solo por la
        # plantilla genérica; no se repite si la anterior no se contestó; si no
        # sale, la tool lo dice (not_sent) para que no se anote como enviado.
        def c_ventana_plantilla():
            from unittest.mock import patch
            from ..services.helpers import (template_text_from_html,
                                            closed_window_template)
            t = template_text_from_html(
                "<p>Hola Margarita, ¿pudo ver la cotización?</p><p>Le faltan 20 L.</p>")
            assert t == "¿Pudo ver la cotización? Le faltan 20 L.", t
            t = template_text_from_html("<p>Hola, ¿cómo está? Le escribo por el pedido.</p>")
            assert t == "Le escribo por el pedido.", t
            t = template_text_from_html("<p>Mañana sale el camión.</p>")
            assert t == "Mañana sale el camión.", t
            tpl = env['whatsapp.template'].sudo().search(
                [('template_name', '=', 'hola_mayorista_crm'), ('status', '=', 'approved')],
                limit=1)
            assert tpl, "no está la plantilla aprobada hola_mayorista_crm"
            acc = tpl.wa_account_id.id
            assert closed_window_template(env, acc) == tpl, "no elige hola_mayorista_crm"
            p = mk_partner('Ventana cerrada', 'Rio Cuarto')
            p.mobile = '+5493589990032'
            ch = env['discuss.channel'].sudo().create({
                'name': 'ZZ Autotest ventana', 'channel_type': 'group',
                'channel_member_ids': [(0, 0, {'partner_id': p.id})]})
            sw = ToolRegistry.get('send_whatsapp')
            tool = ToolRegistry.get('send_whatsapp_template')
            calls = []

            def fake_execute(**kw):
                calls.append(kw)
                return {'ok': True, 'wa_message_id': False}
            with patch.object(tool, 'execute', fake_execute):
                body = "<p>Hola Ventana, ¿pudo ver la cotización? Si me confirma, la dejo lista.</p>"
                r = sw._execute(env=env, run=None, channel_id=ch.id, body=body,
                                wa_account_id=acc, mobile_number=p.mobile)
                assert r.get('ok') and r.get('sent_via_template') == 'hola_mayorista_crm', r
                assert calls and calls[0]['partner_id'] == p.id, calls
                assert calls[0]['variables'] == [
                    "¿Pudo ver la cotización? Si me confirma, la dejo lista."], calls[0]
                assert calls[0]['env'].context.get('from_cristal_agent'), "sin from_cristal_agent"
                # Plantilla anterior sin contestar → no se manda otra.
                WA = env['whatsapp.message'].sudo()
                sent = WA.create({'mobile_number': p.mobile, 'wa_account_id': acc,
                                  'wa_template_id': tpl.id, 'message_type': 'outbound',
                                  'state': 'sent'})
                env.cr.execute("UPDATE whatsapp_message SET create_date = "
                               "now() at time zone 'UTC' - interval '2 hours' WHERE id = %s",
                               (sent.id,))
                WA.invalidate_model(['create_date'])
                r = sw._execute(env=env, run=None, channel_id=ch.id,
                                body="<p>¿Lo vio? Quedo atento.</p>",
                                wa_account_id=acc, mobile_number=p.mobile)
                assert r.get('error') == 'TEMPLATE_PENDING' and r.get('not_sent'), r
                assert len(calls) == 1, "mandó otra plantilla sin respuesta a la anterior"
                # Texto largo → no sale y lo dice (sin la plantilla pendiente; un
                # inbound abriría la ventana y el mensaje saldría de verdad).
                sent.unlink()
                r = sw._execute(env=env, run=None, channel_id=ch.id,
                                body="<p>" + "Detalle del pedido. " * 60 + "</p>",
                                wa_account_id=acc, mobile_number=p.mobile)
                assert r.get('error') == 'TEMPLATE_TEXT_TOO_LONG' and r.get('not_sent'), r
            return ("saludo fuera del texto · ventana cerrada → hola_mayorista_crm con "
                    "from_cristal_agent · plantilla sin contestar → TEMPLATE_PENDING (no "
                    "manda otra) · texto largo → not_sent")
        self._case(results, "32. Ventana cerrada sale por plantilla", c_ventana_plantilla)

        # ═════════════════ Envío de los lunes (v1.40) ═════════════════
        # 33) Solo sale la oferta marcada para el envío, con su texto para el cliente, y
        # no le llega a los circuitos excluidos, a "Fuera de zona", a números repetidos
        # ni a quien recibió una plantilla en las últimas 24 h.
        def c_envio_lunes():
            from odoo.exceptions import ValidationError
            Offer = env['cristal.agent.offer'].sudo()
            Cat = env['res.partner.category'].sudo()
            may = Cat.search([('name', '=', 'Mayorista')], limit=1)
            fz = Cat.search([('name', '=', 'Fuera de zona')], limit=1)
            so = env['cristal.agent.circuit'].sudo().search([('name', '=', 'Sur-Oeste')], limit=1)
            assert may and fz and so, "faltan la etiqueta Mayorista/Fuera de zona o Sur-Oeste"
            today = fields.Date.context_today(Offer)
            Offer.create({'name': 'ZZ Autotest zona', 'description': 'interna',
                          'offer_type': 'other', 'valid_from': today,
                          'valid_until': today, 'priority': 98})
            off = Offer.create({'name': 'ZZ Autotest lunes', 'description': 'instrucción interna',
                                'offer_type': 'bonus', 'valid_from': today,
                                'valid_until': today, 'priority': 99,
                                'weekly_broadcast': True, 'broadcast_text': 'pack de regalo',
                                'excluded_circuit_ids': [(6, 0, so.ids)]})
            assert Offer.get_weekly_broadcast_offer() == off, "elige una oferta no marcada"
            try:
                with env.cr.savepoint():
                    Offer.create({'name': 'ZZ sin texto', 'description': 'x',
                                  'offer_type': 'other', 'valid_from': today,
                                  'valid_until': today, 'weekly_broadcast': True})
                raise AssertionError("dejó marcar el envío sin texto para el cliente")
            except ValidationError:
                pass

            def mk(name, number, cats, circuit=None):
                p = Partner.create({'name': f'ZZ Autotest {name}', 'mobile': number,
                                    'category_id': [(6, 0, cats.ids)]})
                if circuit:
                    p.truck_circuit_id = circuit.id
                return p
            ok = mk('Lunes RC', '+5493589330001', may)
            dup = mk('Lunes repetido', '+54 9 358 933-0001', may)
            sur = mk('Lunes Sur-Oeste', '+5493589330002', may, so)
            fuera = mk('Lunes fuera', '+5493589330003', may | fz)
            reciente = mk('Lunes reciente', '+5493589330004', may)
            tpl = env['whatsapp.template'].sudo().search([('status', '=', 'approved')], limit=1)
            env['whatsapp.message'].sudo().create({
                'mobile_number': '+5493589330004', 'wa_account_id': tpl.wa_account_id.id,
                'wa_template_id': tpl.id, 'message_type': 'outbound', 'state': 'sent'})
            got = env['cristal.agent.run']._weekly_broadcast_partners(off)
            assert len(got & (ok | dup)) == 1, "el mismo número tiene que salir una sola vez"
            assert sur not in got, "manda al circuito excluido"
            assert fuera not in got, "manda a Fuera de zona"
            assert reciente not in got, "manda a quien recibió una plantilla hoy"
            return ("solo la oferta marcada · sin texto no se puede marcar · excluye Sur-Oeste, "
                    "Fuera de zona, números repetidos y plantilla en 24 h")
        self._case(results, "33. Envío de los lunes", c_envio_lunes)

        # ═════════════════ Costo: Haiku 5.5 + avanzado por reglas (v1.42) ═════════════════
        # 34) Qué modelo atiende, cuánto cuesta una respuesta típica y cómo se marca
        # la caché (fijo 1 h, conversación 5 min).
        def c_modelo_y_costo():
            from types import SimpleNamespace
            from unittest.mock import patch
            from ..services.claude_client import pick_model, ClaudeClient
            cfg = SimpleNamespace(anthropic_model='claude-haiku-5-5',
                                  anthropic_model_complex='claude-sonnet-5-5',
                                  daily_budget_usd=2.0, strong_share_percent=0,
                                  escalate_client_msgs_to_strong=False)
            H, S = 'claude-haiku-5-5', 'claude-sonnet-5-5'
            checks = [
                (dict(text='Hola, cuánto sale la lavandina?'), H),
                (dict(text='me faltó sumar 20 L de suavizante'), H),
                (dict(text='no me interesa, gracias'), H),
                (dict(text='Me vino roto el bidón y pierde'), S),
                (dict(text='quiero hacer un reclamo'), S),
                (dict(text='lista', has_media=True), S),
                (dict(text='\n'.join(['20 L producto'] * 9)), S),
                (dict(trigger='joaco_command', text='mandale a Ale'), S),
                (dict(client_type='institucional', text='hola'), S),
                (dict(text='me vino roto', spend_today=2.5), H),
            ]
            for kw, want in checks:
                got, why = pick_model(cfg, **kw)
                assert got == want, f"{kw} → {got} ({why}), esperaba {want}"
            cfg.strong_share_percent = 100
            assert pick_model(cfg, text='hola', partner_id=7)[0] == S, "grupo de control"
            # Costo de una respuesta típica (medida 20-27/10: 3 llamadas que suman 25k de
            # cache write, 124k de cache read y 800 de salida; ~50k tokens por llamada).
            Run = env['cristal.agent.run']
            call = {'input_tokens': 3, 'output_tokens': 267,
                    'cache_creation_input_tokens': 8333,
                    'cache_creation': {'ephemeral_5m_input_tokens': 8333},
                    'cache_read_input_tokens': 41333}
            haiku = 3 * Run._call_cost(H, call)
            sonnet_old = 3 * Run._call_cost(S, dict(call, cache_creation={}))
            assert haiku < 0.01, f"Haiku cuesta {haiku:.4f} por respuesta"
            assert sonnet_old > 0.12, f"Sonnet con caché de 1 h: {sonnet_old:.4f}"
            one = Run._call_cost(H, call)
            big = Run._call_cost(H, dict(call, cache_read_input_tokens=150000))
            assert big > one * 5, "Haiku con más de 100K tokens de prompt cuesta 5x"
            # Cómo se arma la llamada: modelo, caché 1 h en lo fijo y 5 min en la charla.
            client = ClaudeClient(env)
            client.model = H
            sent = {}

            class _Resp:
                status_code = 200
                headers = {}
                text = ''

                def json(self):
                    return {'content': [], 'stop_reason': 'end_turn', 'usage': {}}

            def fake_post(url, headers=None, json=None, timeout=None):
                sent.update(json)
                return _Resp()
            with patch.object(client._requests, 'post', fake_post):
                client._call_claude_api('fijo', 'del cliente',
                                        [{'role': 'user', 'content': 'hola'}])
            assert sent['model'] == H, sent.get('model')
            assert sent['system'][0]['cache_control'].get('ttl') == '1h', "lo fijo no es 1 h"
            last = sent['messages'][-1]['content'][-1]
            assert last.get('cache_control') == {'type': 'ephemeral'}, last
            assert 'fallbacks' not in sent, "Haiku 5.5 no acepta fallbacks"
            client.strong_model = S
            client._spend_today = lambda: 0.0  # sin depender del gasto real del día
            assert client._escalate('prueba') and client.model == S, "no pasa al avanzado"
            assert not client._escalate('otra vez'), "pasó dos veces"
            return (f"reglas de modelo OK (10 casos + grupo de control) · respuesta típica "
                    f"Haiku US$ {haiku:.4f} vs Sonnet con caché 1 h US$ {sonnet_old:.3f} · "
                    f"caché 1 h fijo / 5 min charla · pase al avanzado una vez")
        self._case(results, "34. Modelo y costo por respuesta", c_modelo_y_costo)

        # 35) El contexto del cliente trae sus cotizaciones abiertas y su charla reciente.
        def c_contexto_cliente():
            from ..services.prompt_builder import _build_partner_context
            p = mk_partner('Contexto', 'Rio Cuarto')
            r = quote(p, 60000)
            o = SaleOrder.browse(r['order_id']) if r.get('order_id') else SaleOrder
            ctx = _build_partner_context(env, p)
            assert o and o.name in ctx and 'Cotizaciones abiertas' in ctx, ctx[-600:]
            note = 'charla: sin canal de WhatsApp de prueba'
            acc = env['whatsapp.account'].sudo().search([], limit=1)
            if acc:
                try:
                    with env.cr.savepoint():
                        ch = env['discuss.channel'].sudo().create({
                            'name': 'ZZ Autotest contexto', 'channel_type': 'whatsapp',
                            'whatsapp_number': '+5493589990035', 'wa_account_id': acc.id,
                            'whatsapp_partner_id': p.id,
                            'channel_member_ids': [(0, 0, {'partner_id': p.id})]})
                        env['mail.message'].sudo().with_context(from_cristal_agent=True).create({
                            'model': 'discuss.channel', 'res_id': ch.id, 'author_id': p.id,
                            'message_type': 'whatsapp_message',
                            'body': '<p>Hola, quiero precio de lavandina</p>'})
                        ctx = _build_partner_context(env, p)
                        assert 'Conversación reciente' in ctx \
                            and 'Cliente: Hola, quiero precio de lavandina' in ctx, ctx[-500:]
                        note = 'charla reciente incluida'
                except AssertionError:
                    raise
                except Exception as e:
                    note = f'charla: no pude crear el canal de prueba ({str(e)[:60]})'
            return f"cotización abierta {o.name} en el contexto · {note}"
        self._case(results, "35. Contexto del cliente", c_contexto_cliente)

        # 36) No contactar: se marca, sale de envíos, avisos de ruta, cadencias y
        # seguimientos; si escribe él se lo atiende; se puede desmarcar.
        def c_no_contactar():
            from types import SimpleNamespace
            from ..services.claude_client import dispatch_agent_for_activity
            may = env['res.partner.category'].sudo().search([('name', '=', 'Mayorista')], limit=1)
            p = mk_partner('No contactar', 'Rio Cuarto', cat=may)
            p.mobile = '+5493589990036'
            r = ToolRegistry.get('mark_opt_out').execute(
                env=env, run=None, partner_id=p.id, kind='no_vende', quote='no vendo limpieza')
            assert r.get('ok') and p.agent_opt_out, r
            assert 'No contactar' in p.category_id.mapped('name'), "sin etiqueta No contactar"
            assert 'no vendo limpieza' in (p.agent_opt_out_reason or ''), p.agent_opt_out_reason
            ch = env['discuss.channel'].sudo().create({
                'name': 'ZZ Autotest opt-out', 'channel_type': 'group',
                'channel_member_ids': [(0, 0, {'partner_id': p.id})]})
            fake_run = SimpleNamespace(trigger='cron_cadence', partner_id=p,
                                       tool_calls_log='[]')
            r = ToolRegistry.get('send_whatsapp')._execute(
                env=env, run=fake_run, channel_id=ch.id, body='<p>¿Pudo ver la lista?</p>',
                wa_account_id=1, mobile_number=p.mobile)
            assert r.get('error') == 'OPT_OUT' and r.get('not_sent'), r
            r = ToolRegistry.get('send_whatsapp_template')._execute(
                env=env, run=None, partner_id=p.id, template_name='hola_mayorista_crm',
                variables=['hola'])
            assert r.get('error') == 'OPT_OUT', r
            today = fields.Date.context_today(p)
            off = env['cristal.agent.offer'].sudo().create({
                'name': 'ZZ Autotest opt-out', 'description': 'x', 'offer_type': 'other',
                'valid_from': today, 'valid_until': today, 'weekly_broadcast': True,
                'broadcast_text': 'promo'})
            assert p not in env['cristal.agent.run']._weekly_broadcast_partners(off), \
                "el envío de los lunes le llega"
            config = env['cristal.agent.config'].sudo().get_active()
            act = p.activity_schedule('mail.mail_activity_data_todo', summary='ZZ seguimiento',
                                      user_id=config.bot_user_id.id or env.uid)
            runs_before = env['cristal.agent.run'].search_count([('partner_id', '=', p.id)])
            dispatch_agent_for_activity(env, p, None, act)
            assert not act.exists() or not act.active, "la actividad sigue abierta"
            assert env['cristal.agent.run'].search_count([('partner_id', '=', p.id)]) \
                == runs_before, "gastó una corrida en alguien que no quiere propuestas"
            r = ToolRegistry.get('mark_opt_out').execute(env=env, run=None, partner_id=p.id,
                                                          undo=True)
            assert r.get('ok') and not p.agent_opt_out \
                and 'No contactar' not in p.category_id.mapped('name'), r
            return ("se marca con motivo y etiqueta · sin seguimientos, plantillas ni envío de "
                    "los lunes · la actividad se cierra sin corrida · se desmarca con undo")
        self._case(results, "36. No contactar", c_no_contactar)

        # ═════════════════ Mejoras v1.43 ═════════════════
        # 37) "Hoy no atendemos" ya no se bloquea; las fotos/PDF del cliente le llegan
        # adjuntas al modelo (y no quedan en el log); las claves no quedan en la config.
        def c_mejoras_v143():
            import base64
            from unittest.mock import patch
            from ..services import send_guards as sg
            from ..services.claude_client import (_recent_inbound_media, _media_blocks,
                                                  _strip_media_for_log)
            assert not sg._RE_ABIERTO_HOY.search("Hoy domingo no atendemos; el lunes seguimos")
            assert not sg._RE_ABIERTO_HOY.search("Hoy estamos cerrados por feriado")
            assert sg._RE_ABIERTO_HOY.search("Hoy estamos abiertos hasta las 20 h")
            # Fotos del cliente en la ráfaga actual (corta en la última respuesta del bot).
            p = mk_partner('Foto', 'Rio Cuarto')
            ch = env['discuss.channel'].sudo().create({
                'name': 'ZZ Autotest foto', 'channel_type': 'group',
                'channel_member_ids': [(0, 0, {'partner_id': p.id})]})
            png = base64.b64encode(
                b'\x89PNG\r\n\x1a\n' + b'\x00' * 64).decode()
            Att = env['ir.attachment'].sudo()
            Msg = env['mail.message'].sudo().with_context(from_cristal_agent=True)
            old = Att.create({'name': 'vieja.png', 'datas': png, 'mimetype': 'image/png'})
            Msg.create({'model': 'discuss.channel', 'res_id': ch.id, 'author_id': p.id,
                        'body': 'vieja', 'attachment_ids': [(4, old.id)]})
            config = env['cristal.agent.config'].sudo().get_active()
            bot = config.bot_partner_id.id if config.bot_partner_id else 2
            Msg.create({'model': 'discuss.channel', 'res_id': ch.id, 'author_id': bot,
                        'body': 'respuesta del bot'})
            new = Att.create({'name': 'lista.png', 'datas': png, 'mimetype': 'image/png'})
            Msg.create({'model': 'discuss.channel', 'res_id': ch.id, 'author_id': p.id,
                        'body': '', 'attachment_ids': [(4, new.id)]})
            media = _recent_inbound_media(env, ch.id, p)
            assert [a.id for a in media] == [new.id], [a.name for a in media]
            blocks = _media_blocks(media)
            assert blocks and blocks[0]['type'] == 'image' \
                and blocks[0]['source']['media_type'] == 'image/png', blocks
            log = _strip_media_for_log([{'role': 'user', 'content': [{'type': 'text',
                                                                       'text': 'x'}] + blocks}])
            assert 'data' not in log[0]['content'][1]['source'], "el log guarda la imagen"
            # Claves: van al parámetro del sistema y el campo queda vacío.
            seen = {}
            Param = type(env['ir.config_parameter'])
            with patch.object(Param, 'set_param', lambda self, k, v: seen.update({k: v})):
                vals = env['cristal.agent.config']._stash_keys(
                    {'anthropic_api_key': ' sk-prueba ', 'debounce_seconds': 15})
            assert seen == {'cristal_agent.anthropic_api_key': 'sk-prueba'}, seen
            assert vals['anthropic_api_key'] is False and vals['debounce_seconds'] == 15, vals
            return ("'hoy no atendemos' pasa · foto de la ráfaga adjunta (no la vieja) · "
                    "log sin la imagen · claves solo en parámetros del sistema")
        self._case(results, "37. Fotos, claves y control de horario", c_mejoras_v143)

        # 38) Informe semanal, rechazos de WhatsApp y recompra.
        def c_informe_recompra():
            from datetime import datetime as _dt
            Report = env['cristal.agent.weekly.report']
            rep = Report.build_report(date(2026, 10, 20), date(2026, 10, 27))
            assert rep and 'costo por pedido vendido' in (rep.body or ''), rep.body
            # Rechazo 131050 (bloqueó marketing) → No contactar.
            tpl = env['whatsapp.template'].sudo().search(
                [('template_name', '=', 'hola_mayorista_crm')], limit=1)
            note = 'sin plantilla hola_mayorista_crm'
            if tpl:
                p = mk_partner('Bloqueó WA', 'Rio Cuarto')
                p.mobile = '+5493589380038'
                env['whatsapp.message'].sudo().create({
                    'mobile_number': p.mobile, 'wa_account_id': tpl.wa_account_id.id,
                    'wa_template_id': tpl.id, 'message_type': 'outbound', 'state': 'error',
                    'failure_reason': '131050 : Unable to deliver the message. This recipient '
                                      'has chosen to stop receiving marketing messages'})
                marked = Report.cron_wa_failures(days=1)
                assert p in [m[0] for m in marked] and p.agent_opt_out, "no lo marcó"
                note = '131050 → No contactar'
            # Recompra: compra cada ~10 días y la última fue hace 12.
            may = env['res.partner.category'].sudo().search([('name', '=', 'Mayorista')],
                                                            limit=1)
            c = mk_partner('Recompra', 'Rio Cuarto', cat=may)
            c.mobile = '+5493589380039'
            today = fields.Date.context_today(c)
            for days_ago in (32, 22, 12):
                o = SaleOrder.create({'partner_id': c.id, 'order_line': [(0, 0, {
                    'product_id': product.id, 'product_uom_qty': 20, 'price_unit': 650})]})
                o.action_confirm()
                o.date_order = _dt.combine(today - timedelta(days=days_ago), time(12, 0))
            got = {p.id: (i, s) for p, i, s, _prods in Report.reorder_candidates(
                today, limit=10000)}
            assert got.get(c.id) == (10, 12), got.get(c.id)
            c.agent_reorder_reminder_date = today
            got = [p.id for p, *_r in Report.reorder_candidates(today, limit=10000)]
            assert c.id not in got, "repite el aviso antes de su intervalo"
            return (f"informe con costo por pedido vendido · {note} · recompra: cada 10 días, "
                    f"última hace 12 → aviso (y no se repite)")
        self._case(results, "38. Informe semanal, WhatsApp y recompra", c_informe_recompra)

        # ═════════════════ Consumidor final (v1.45) ═════════════════
        # 39) Río Cuarto: precio público, sin mínimo; ruta: no se envía; retiro sí.
        def c_consumidor_final():
            lc1 = env['product.pricelist'].sudo().search([('name', '=', 'L.C 1')], limit=1)
            assert lc1, "no existe la lista L.C 1"

            def q(partner, mode=None):
                kw = {'delivery_mode': mode} if mode else {}
                return cso.execute(env=env, run=None, partner_id=partner.id, consumidor_final=True,
                                   lines=[{'product_id': product.id, 'qty': 1}], **kw)
            p1 = mk_partner('CF RC', 'Rio Cuarto')
            r = q(p1)
            assert r.get('ok') and not r.get('blocked_min_compra'), r
            o = SaleOrder.browse(r['order_id'])
            assert o.pricelist_id == lc1, o.pricelist_id.name
            assert not o.order_line.filtered(lambda l: l.discount), "aplicó descuento"
            assert 'CONSUMIDOR FINAL' in (r.get('cf_note') or ''), r.get('cf_note')
            p2 = mk_partner('CF Sampacho', 'Sampacho')
            r = q(p2)
            assert r.get('blocked_cf_zone') and not r.get('order_id'), r
            r = q(p2, 'retiro')
            assert r.get('ok'), r
            o = SaleOrder.browse(r['order_id'])
            assert o.pricelist_id == lc1 and not freight_lines(o) and not o.route_departure_id, \
                "retiro de consumidor final con lista, flete o salida de ruta"
            return ("RC → L.C 1 sin mínimo ni descuento · Sampacho con envío → no (retiro o web) "
                    "· Sampacho retirando → L.C 1 sin flete")
        self._case(results, "39. Consumidor final", c_consumidor_final)

        # 40) Claudio confirma solo el pedido de consumidor final (efectivo/transferencia)
        def c_confirma_cf():
            confirm = ToolRegistry.get('confirm_cf_order')

            def q(partner, mode=None):
                kw = {'delivery_mode': mode} if mode else {}
                return cso.execute(env=env, run=None, partner_id=partner.id, consumidor_final=True,
                                   lines=[{'product_id': product.id, 'qty': 1}], **kw)
            p1 = mk_partner('CF confirma', 'Rio Cuarto')
            o1 = q(p1)['order_id']
            r = confirm.execute(env=env, run=None, partner_id=p1.id, order_id=o1, payment='efectivo')
            assert r.get('not_confirmed') and 'dirección' in ' '.join(r.get('problems', [])), r
            p1.street = 'San Martín 1000'
            r = confirm.execute(env=env, run=None, partner_id=p1.id, order_id=o1, payment='cheque')
            assert r.get('not_confirmed'), "confirmó con cheque"
            r = confirm.execute(env=env, run=None, partner_id=p1.id, order_id=o1, payment='transferencia')
            assert r.get('confirmed') and SaleOrder.browse(o1).state == 'sale', r
            p2 = mk_partner('CF retira Sampacho', 'Sampacho')
            o2 = q(p2, 'retiro')['order_id']
            r = confirm.execute(env=env, run=None, partner_id=p2.id, order_id=o2, payment='efectivo')
            assert r.get('confirmed'), r
            p3 = mk_partner('Mayorista', 'Rio Cuarto')
            p3.street = 'X 1'
            o3 = cso.execute(env=env, run=None, partner_id=p3.id,
                             lines=[{'product_id': product.id, 'qty': 1, 'price_unit': 60000}])['order_id']
            r = confirm.execute(env=env, run=None, partner_id=p3.id, order_id=o3, payment='efectivo')
            assert r.get('not_confirmed'), "confirmó una cotización mayorista"
            return ("sin dirección → no · cheque → no · transferencia en RC → confirmado · "
                    "retiro en Sampacho → confirmado · cotización mayorista → no")
        self._case(results, "40. Claudio confirma solo al consumidor final", c_confirma_cf)

        # 41) Modo administración: mail del e-cheq (sin crear cobros: no gasta recibos)
        def c_echeq_mail():
            from datetime import date as _date
            from .agent_admin import _money
            Admin = env['cristal.agent.admin']
            assert _money(1421990.26) == '$1.421.990,26', _money(1421990.26)
            fake = type('P', (), {'name': 'RE-X 0001-00000099'})()
            no_inv = env['account.move']
            b = Admin._echeq_mail_body(fake, '90043481', 236092.06, _date(2026, 11, 13), no_inv, 0.0)
            assert 'e-cheq N° 90043481 por $236.092,06 con fecha de pago 13/11/2026' in b, b
            assert 'recibo RE-X 0001-00000099' in b and 'admin@quimicacristal.com.ar' in b, b
            assert 'retención' not in b, "pidió certificado sin diferencia"
            b2 = Admin._echeq_mail_body(fake, '1', 100.0, _date(2026, 11, 13), no_inv, 3.5)
            assert 'por los $3,50 de diferencia' in b2 and 'certificado de retención' in b2, b2
            r = Admin.register_echeq(False, '', 0, False)
            assert not r.get('ok') and r.get('error'), r
            return "texto de Sergio con y sin diferencia · faltan datos → no registra"
        self._case(results, "41. Modo administración: mail del e-cheq", c_echeq_mail)

        # ═════════════════ v1.52 — Ciclo de vida, NBA, origen y sugerencias ═════════════════
        # Todo con partners/pedidos ZZ creados acá: no depende del día ni de la config.
        def _backdate_order(order, days_ago):
            dt = fields.Datetime.now() - timedelta(days=days_ago)
            order.write({'date_order': dt})
            env.cr.execute("UPDATE sale_order SET create_date=%s WHERE id=%s", (dt, order.id))
            order.invalidate_recordset(['create_date', 'date_order'])

        def _confirmed(partner, days_ago, amount=20000):
            o = SaleOrder.browse(quote(partner, amount)['order_id'])
            o.action_confirm()
            _backdate_order(o, days_ago)
            return o

        may_tag = env['res.partner.category'].sudo().search([('name', '=', 'Mayorista')], limit=1)
        Life = env['cristal.agent.lifecycle']
        NBA = env['cristal.agent.nba'].sudo()
        cfg = env['cristal.agent.config'].sudo().get_active()
        cfg.write({'lifecycle_mode': 'dry_run', 'lifecycle_holdout_pct': 0,
                   'lifecycle_daily_cap': 30, 'lifecycle_default_cycle_days': 30,
                   'enable_create_leads': True, 'lifecycle_live_actions': '',
                   'bot_user_id': cfg.bot_user_id.id or env.ref('base.user_root').id})
        today_ar = fields.Date.context_today(cfg)
        lc_state = {}

        def mk_lc(name, city=None, mobile='+5493589990042'):
            p = mk_partner(name, city, cat=may_tag)
            p.mobile = mobile
            if city:
                p.agent_zone = 'rio_cuarto'
            return p

        # 42) Etapas del ciclo de vida
        def c_ciclo_vida():
            p_lead = mk_lc('LC lead')
            p_qual = mk_lc('LC calificado', 'Rio Cuarto')
            p_qual.agent_phase_started_at = fields.Datetime.now() - timedelta(days=12)
            p_quot = mk_lc('LC cotizado', 'Rio Cuarto')
            o = SaleOrder.browse(quote(p_quot, 30000)['order_id'])
            _backdate_order(o, 20)
            p_new = mk_lc('LC nuevo', 'Rio Cuarto')
            _confirmed(p_new, 11)
            p_act = mk_lc('LC activo', 'Rio Cuarto')
            for d in (60, 30, 5):          # ciclo 27, último hace 5 → activo
                _confirmed(p_act, d)
            p_risk = mk_lc('LC riesgo', 'Rio Cuarto')
            for d in (150, 120, 70):       # ciclo 40, último hace 70 (> 1,5 ciclos) → en riesgo
                _confirmed(p_risk, d)
            p_dorm = mk_lc('LC dormido', 'Rio Cuarto')
            for d in (230, 200, 170):      # ciclo 30, último hace 170 (> 90) → dormido
                _confirmed(p_dorm, d)
            p_lost = mk_lc('LC perdido', 'Rio Cuarto')
            _confirmed(p_lost, 200)
            p_opt = mk_lc('LC opt-out', 'Rio Cuarto')
            p_opt.set_agent_opt_out('no vende')
            group = p_lead | p_qual | p_quot | p_new | p_act | p_risk | p_dorm | p_lost | p_opt
            Life.recompute(group, today_ar)
            got = {p.name.replace('ZZ Autotest LC ', ''): p.agent_lifecycle for p in group}
            want = {'lead': 'lead', 'calificado': 'qualified_no_quote', 'cotizado': 'quoted_no_order',
                    'nuevo': 'new_customer', 'activo': 'active', 'riesgo': 'at_risk',
                    'dormido': 'dormant', 'perdido': 'lost', 'opt-out': 'no_contact'}
            assert got == want, got
            assert all(p.agent_lifecycle_date == today_ar and p.agent_lifecycle_reason for p in group)
            lc_state['group'] = group
            return " · ".join(f"{k}→{v}" for k, v in want.items())
        self._case(results, "42. Ciclo de vida: 9 etapas desde los datos", c_ciclo_vida)

        # 43) Próxima mejor acción: en seco no manda nada; en real agenda a Claudio
        def c_nba():
            group = lc_state.get('group')
            assert group, "depende del caso 42"
            stats = Life.gather(group, today_ar)
            Act = env['mail.activity'].sudo()
            Run = env['cristal.agent.run'].sudo()
            acts_before = Act.search_count([('res_model', '=', 'res.partner'), ('res_id', 'in', group.ids)])
            runs_before = Run.search_count([('partner_id', 'in', group.ids)])
            created = NBA.plan(group, stats, today_ar, cfg)
            by = {n.partner_id.name.replace('ZZ Autotest LC ', ''): n.action_code for n in created}
            want = {'calificado': 'q_combo', 'cotizado': 'c_objecion', 'nuevo': 'n_producto_top',
                    'riesgo': 'r_reactivacion_1', 'dormido': 'd_reactivacion_3'}
            assert by == want, by
            assert set(created.mapped('state')) == {'dry_run'}, created.mapped('state')
            assert Act.search_count([('res_model', '=', 'res.partner'), ('res_id', 'in', group.ids)]) == acts_before, \
                "en seco creó actividades"
            assert Run.search_count([('partner_id', 'in', group.ids)]) == runs_before, "en seco gastó corridas"
            again = NBA.plan(group, stats, today_ar, cfg)
            assert not again, f"repitió acciones en la misma semana: {again.mapped('action_code')}"
            # Prioridad: lo cotizado (plata parada) va antes que lo dormido.
            order = [n.action_code[:2] for n in created.sorted('id')]
            assert order.index('c_') < order.index('d_'), order
            # Modo real: la acción se agenda a Claudio (actividad) y, si compra, cuenta.
            p_risk = group.filtered(lambda p: p.name.endswith('LC riesgo'))
            created.filtered(lambda n: n.partner_id == p_risk).unlink()
            cfg.lifecycle_mode = 'live'
            live = NBA.plan(p_risk, stats, today_ar, cfg)
            assert len(live) == 1 and live.state == 'planned' and live.activity_id, live.read()
            assert live.activity_id.user_id == cfg.bot_user_id and '[NBA]' in live.activity_id.summary
            _confirmed(p_risk, 0)
            NBA.mark_conversions(today_ar)
            assert live.converted and live.converted_amount > 0, live.read(['converted', 'converted_amount'])
            # Modo real acotado: solo las acciones habilitadas se agendan; el resto sigue en seco.
            p_dorm = group.filtered(lambda p: p.name.endswith('LC dormido'))
            created.filtered(lambda n: n.partner_id == p_dorm).unlink()
            cfg.lifecycle_live_actions = 'c_'
            limited = NBA.plan(p_dorm, stats, today_ar, cfg)
            assert len(limited) == 1 and limited.state == 'dry_run' and not limited.activity_id, limited.read()
            cfg.write({'lifecycle_mode': 'dry_run', 'lifecycle_live_actions': ''})
            return ("5 acciones correctas por etapa · en seco sin actividades ni corridas · una por "
                    "semana · en real agenda [NBA] a Claudio y marca la compra · acciones no "
                    "habilitadas quedan en seco")
        self._case(results, "43. Próxima mejor acción (en seco y real)", c_nba)

        # 44) Origen del contacto: código, frase del anuncio, orgánico, fuente del lead
        def c_origen():
            env['ir.config_parameter'].sudo().set_param(
                'cristal_agent.origin_phrases', "RUTA-N | el camión pasa por tu pueblo")
            p1 = mk_lc('Origen código', 'Rio Cuarto')
            assert p1.agent_capture_origin("Hola! Quiero la lista mayorista MAY-SUAV", first_message=True) == 'MAY-SUAV'
            assert p1.agent_capture_origin("otra cosa MAY-OTRO", first_message=True) is False, "pisó el origen"
            p0 = mk_lc('Origen falso', 'Rio Cuarto')
            assert p0.agent_capture_origin("tengo COVID-19, mañana paso", first_message=True) == 'ORGANICO', \
                "tomó COVID-19 como anuncio"
            p2 = mk_lc('Origen frase', 'Rio Cuarto')
            assert p2.agent_capture_origin("Hola, vi que el camión pasa por tu pueblo", first_message=True) == 'RUTA-N'
            p3 = mk_lc('Origen orgánico', 'Rio Cuarto')
            assert p3.agent_capture_origin("hola, precio del detergente?", first_message=True) == 'ORGANICO'
            p4 = mk_lc('Origen tardío', 'Rio Cuarto')
            assert p4.agent_capture_origin("hola", first_message=False) is False, "marcó orgánico sin ser el primer mensaje"
            r = ToolRegistry.get('create_lead').execute(
                env=env, run=None, partner_id=p1.id, lead_name='ZZ Autotest lead origen',
                client_type='mayorista')
            lead = env['crm.lead'].sudo().browse(r.get('lead_id') or 0)
            assert lead.exists() and lead.source_id.name == 'MAY-SUAV', (r, lead.source_id.name)
            return "código MAY-SUAV · frase del anuncio → RUTA-N · sin anuncio → ORGANICO · fuente del lead"
        self._case(results, "44. Origen del contacto (atribución)", c_origen)

        # 45) suggest_products: lo habitual que no pidió + brecha al mínimo, sin tocar la cotización
        def c_sugerencias():
            p = mk_lc('Sugerencias', 'Rio Cuarto')
            _confirmed(p, 30, amount=15000)   # compró el producto ZZ Ruta hace un mes
            other = env['product.product'].sudo().create({
                'name': 'ZZ Autotest Detergente', 'type': 'consu', 'list_price': 1000.0,
                'is_storable': False, 'sale_ok': True, 'taxes_id': [(6, 0, [])]})
            oid = cso.execute(env=env, run=None, partner_id=p.id,
                              lines=[{'product_id': other.id, 'qty': 1, 'price_unit': 1000}])['order_id']
            lines_before = len(SaleOrder.browse(oid).order_line)
            r = ToolRegistry.get('suggest_products').execute(env=env, run=None, partner_id=p.id, order_id=oid)
            assert r.get('ok') and r.get('suggestions'), r
            ids = [s['product_id'] for s in r['suggestions']]
            assert product.id in ids and other.id not in ids, ids
            s0 = next(s for s in r['suggestions'] if s['product_id'] == product.id)
            assert s0['kind'] == 'habitual' and s0['price'] >= 0 and s0['text'], s0
            assert r['gaps'].get('falta_para_minimo', 0) > 0 and 'subtotal_productos' in r['gaps'], r['gaps']
            assert len(SaleOrder.browse(oid).order_line) == lines_before, "modificó la cotización"
            return ("sugiere lo que compró antes y no pidió · no sugiere lo ya cotizado · "
                    "informa cuánto falta para el mínimo · no toca la cotización")
        self._case(results, "45. suggest_products (cross-sell con datos)", c_sugerencias)

        # ═════════════════ v1.53 — Productos a pedido, variantes y confirmación ═════════════════
        # 46) search_products: palabras pegadas, a pedido (granel) y nombre con variante
        def c_busqueda_v153():
            sp = ToolRegistry.get('search_products')
            granel = env['product.product'].sudo().create({
                'name': 'ZZ Quita Sarro Test a granel', 'type': 'consu', 'list_price': 500.0,
                'is_storable': True, 'sale_ok': True, 'taxes_id': [(6, 0, [])],
                'uom_id': product.uom_id.id})
            r = sp.execute(env=env, run=None, query='zz quitasarro')
            ids = [x['id'] for x in r.get('products') or []]
            assert granel.id in ids, r
            hit = next(x for x in r['products'] if x['id'] == granel.id)
            assert hit['a_pedido'] is True and hit['qty_available'] is None, hit
            assert 'a pedido' in hit['disponible'].lower(), hit
            assert 'A PEDIDO' in (r.get('message_for_bot') or ''), r.get('message_for_bot')
            assert hit['name'].startswith('ZZ Quita Sarro Test') and 'variant' in hit, hit
            r2 = sp.execute(env=env, run=None, query='zz quita sarro test')
            assert granel.id in [x['id'] for x in r2['products']] and not r2['approximate'], r2
            return ("'zz quitasarro' encuentra 'ZZ Quita Sarro Test a granel' · marcado a pedido, sin "
                    "stock que lo frene · nombre completo con variante")
        self._case(results, "46. search_products: pegadas, a pedido, variantes", c_busqueda_v153)

        # 47) create_sale_order: una línea ambigua (aroma) no se carga; con el aroma, sí
        def c_variantes():
            Attr = env['product.attribute'].sudo()
            attr = Attr.create({'name': 'ZZ Aroma Test', 'create_variant': 'always'})
            v1 = env['product.attribute.value'].sudo().create({'name': 'Lavandatest', 'attribute_id': attr.id})
            v2 = env['product.attribute.value'].sudo().create({'name': 'Pinotest', 'attribute_id': attr.id})
            tmpl = env['product.template'].sudo().create({
                'name': 'ZZ Base Test (1+80)', 'type': 'consu', 'list_price': 7000.0,
                'is_storable': False, 'sale_ok': True, 'taxes_id': [(6, 0, [])],
                'attribute_line_ids': [(0, 0, {'attribute_id': attr.id, 'value_ids': [(6, 0, [v1.id, v2.id])]})]})
            assert len(tmpl.product_variant_ids) == 2, tmpl.product_variant_ids
            p = mk_lc('Variantes', 'Rio Cuarto')
            r = cso.execute(env=env, run=None, partner_id=p.id,
                            lines=[{'product_name': 'ZZ Base Test', 'qty': 2}])
            probs = ' '.join(r.get('problems') or [])
            assert 'varias variantes' in probs and 'Lavandatest' in probs and 'Pinotest' in probs, r
            assert not r.get('order_id') or not any(
                l.product_id.product_tmpl_id == tmpl for l in SaleOrder.browse(r['order_id']).order_line), \
                "cargó una variante al azar"
            r2 = cso.execute(env=env, run=None, partner_id=p.id,
                             lines=[{'product_name': 'ZZ Base Test Pinotest', 'qty': 2}])
            assert r2.get('order_id'), r2
            lines = SaleOrder.browse(r2['order_id']).order_line.filtered(lambda l: l.product_id.product_tmpl_id == tmpl)
            assert len(lines) == 1 and 'Pinotest' in lines.product_id.display_name, lines.mapped('product_id.display_name')
            return "nombre sin aroma → no carga y lista las opciones · con el aroma → carga la variante correcta"
        self._case(results, "47. Variantes: ambigua no se carga", c_variantes)

        # 49) Variantes numeradas: "lampazo 7" / "nº 15" / "5 lts" (caso Milagro y Hernán, 02/11)
        def c_variantes_numeradas():
            sp = ToolRegistry.get('search_products')
            attr = env['product.attribute'].sudo().create({'name': 'ZZ Numero Test', 'create_variant': 'always'})
            vals = {n: env['product.attribute.value'].sudo().create({'name': n, 'attribute_id': attr.id})
                    for n in ('Nº5', 'Nº7', 'Nº15')}
            tmpl = env['product.template'].sudo().create({
                'name': 'ZZ Lampazo Test', 'type': 'consu', 'list_price': 4000.0,
                'is_storable': False, 'sale_ok': True, 'taxes_id': [(6, 0, [])],
                'attribute_line_ids': [(0, 0, {'attribute_id': attr.id,
                                               'value_ids': [(6, 0, [v.id for v in vals.values()])]})]})
            by_name = {p.product_template_variant_value_ids.name: p for p in tmpl.product_variant_ids}
            assert set(by_name) == {'Nº5', 'Nº7', 'Nº15'}, by_name
            r = sp.execute(env=env, run=None, query='zz lampazo test 7')
            assert r['products'] and r['products'][0]['id'] == by_name['Nº7'].id, r['products'][:3]
            assert 'Nº7' in r['products'][0]['name'] and r['products'][0]['variant'] == 'Nº7', r['products'][0]
            r = sp.execute(env=env, run=None, query='zz lampazo test nº 15')
            assert r['products'] and r['products'][0]['id'] == by_name['Nº15'].id, r['products'][:3]
            p = mk_lc('Variantes numeradas', 'Rio Cuarto')
            r = cso.execute(env=env, run=None, partner_id=p.id,
                            lines=[{'product_name': 'ZZ Lampazo Test numero 5', 'qty': 1}])
            assert r.get('order_id'), r
            line = SaleOrder.browse(r['order_id']).order_line.filtered(lambda l: l.product_id.product_tmpl_id == tmpl)
            assert len(line) == 1 and line.product_id == by_name['Nº5'], line.mapped('product_id.display_name')
            r = cso.execute(env=env, run=None, partner_id=p.id,
                            lines=[{'product_name': 'ZZ Lampazo Test', 'qty': 1}])
            assert 'varias variantes' in ' '.join(r.get('problems') or []), r
            tmpl2 = env['product.template'].sudo().create({
                'name': 'ZZ Bidon Test', 'type': 'consu', 'list_price': 900.0, 'is_storable': False,
                'sale_ok': True, 'taxes_id': [(6, 0, [])], 'default_code': 'ZZ0468'})
            r = sp.execute(env=env, run=None, query='ZZ0468')
            assert r['products'] and r['products'][0]['id'] == tmpl2.product_variant_id.id, r['products'][:2]
            r = sp.execute(env=env, run=None, query='468')
            assert any(x['id'] == tmpl2.product_variant_id.id for x in r['products']), r['products'][:3]
            return ("'lampazo 7' → Nº7 primero · 'nº 15' → Nº15 · 'numero 5' carga la Nº5 (no la Nº15) · "
                    "sin número → pregunta · '468' encuentra el código ZZ0468")
        self._case(results, "49. Variantes numeradas y códigos", c_variantes_numeradas)

        # 50) Envío a domicilio en Río Cuarto y sugerencias en la misma cotización (caso Jorge S06972)
        def c_envio_rc():
            if 'delivery.carrier' not in env:
                return "módulo delivery no instalado: salteado"
            carrier = env['delivery.carrier'].sudo().browse(cso.MAY_CARRIER_ID).exists()
            assert carrier, f"no existe el método de envío mayorista id {cso.MAY_CARRIER_ID}"
            p = mk_lc('Envio RC', 'Rio Cuarto')
            p.street = 'Calle Envio 1'
            r = cso.execute(env=env, run=None, partner_id=p.id,
                            lines=[{'product_id': product.id, 'qty': 1, 'price_unit': 52000}])
            assert r.get('order_id'), r
            o = SaleOrder.browse(r['order_id'])
            ship = o.order_line.filtered(lambda l: getattr(l, 'is_delivery', False))
            assert len(ship) == 1, o.order_line.mapped('product_id.display_name')
            assert r.get('envio') and r['envio']['precio'] == ship.price_unit, (r.get('envio'), ship.price_unit)
            if carrier.free_over and carrier.amount and 52000 < carrier.amount:
                assert ship.price_unit == carrier.fixed_price > 0, (ship.price_unit, carrier.fixed_price)
                assert 'ENVÍO A DOMICILIO' in (r.get('shipping_note') or ''), r.get('shipping_note')
                assert r['envio']['falta_para_gratis'] > 0, r['envio']
            assert any('Env' in d['product'] for d in r['lines']), r['lines']
            assert 'TOTAL' in r['client_summary'] and o.amount_total == r['total_amount'], r['client_summary']
            # El mínimo se mide sin el envío: 45.000 en productos sigue bajo $50.000 aunque el total lo pase.
            r2 = cso.execute(env=env, run=None, partner_id=p.id,
                             lines=[{'product_id': product.id, 'qty': 1, 'price_unit': 45000}])
            assert r2.get('upsell') and 'mínima' in r2['upsell'], r2.get('upsell')
            # Retiro: sin línea de envío.
            r3 = cso.execute(env=env, run=None, partner_id=p.id, delivery_mode='retiro',
                             lines=[{'product_id': product.id, 'qty': 1, 'price_unit': 52000}])
            o3 = SaleOrder.browse(r3['order_id'])
            assert not o3.order_line.filtered(lambda l: getattr(l, 'is_delivery', False)), "retiro con envío"
            # Sugerencias dentro de la respuesta cuando hay historia.
            _confirmed(p, 30, amount=15000)
            other = env['product.product'].sudo().create({
                'name': 'ZZ Autotest Jabon Test', 'type': 'consu', 'list_price': 1000.0,
                'is_storable': False, 'sale_ok': True, 'taxes_id': [(6, 0, [])]})
            r4 = cso.execute(env=env, run=None, partner_id=p.id,
                             lines=[{'product_id': other.id, 'qty': 1, 'price_unit': 52000}])
            assert r4.get('sugerencias') and r4.get('upsell_note'), (r4.get('sugerencias'), r4.get('upsell_note'))
            assert any(s['product_id'] == product.id for s in r4['sugerencias']), r4['sugerencias']
            return ("envío a domicilio en la cotización y en el total · mínimo medido sin envío · retiro sin "
                    "envío · sugerencias en la misma respuesta")
        self._case(results, "50. Envío a domicilio RC y sugerencias en la cotización", c_envio_rc)

        # 51) Beneficio por nivel: PLATA 5 % / ORO 10 % solos; el 20 % de primera compra manda
        # Producto a precio de lista (sin price_unit: un precio cerrado nunca lleva descuento).
        prod60 = env['product.product'].sudo().create({
            'name': 'ZZ Autotest Nivel', 'type': 'consu', 'list_price': 60000.0, 'is_storable': False,
            'sale_ok': True, 'taxes_id': [(6, 0, [])]})
        env['product.pricelist.item'].sudo().create({
            'pricelist_id': env['product.pricelist'].sudo().search([('name', '=', 'Lista Mayorista')], limit=1).id,
            'applied_on': '0_product_variant', 'product_id': prod60.id,
            'product_tmpl_id': prod60.product_tmpl_id.id, 'compute_price': 'fixed', 'fixed_price': 60000.0})

        def c_niveles():
            cfg.write({'level_plata_discount': 5.0, 'level_oro_discount': 10.0})
            p = mk_lc('Nivel plata', 'Rio Cuarto')
            p.write({'agent_level': 'plata', 'street': 'Calle Nivel 1'})
            _confirmed(p, 40, amount=60000)   # ya compró: no hay 20 % de primera compra
            r = cso.execute(env=env, run=None, partner_id=p.id, delivery_mode='retiro',
                            lines=[{'product_id': prod60.id, 'qty': 1}])
            assert r.get('order_id') and r.get('auto_discount', {}).get('percent') == 5.0, r.get('auto_discount')
            lines = SaleOrder.browse(r['order_id']).order_line.filtered(lambda l: l.product_id == prod60)
            assert lines and all(abs(l.discount - 5.0) < 0.01 for l in lines), lines.mapped('discount')
            assert 'nivel PLATA' in (r.get('auto_discount_note') or ''), r.get('auto_discount_note')
            p.agent_level = 'oro'
            r = cso.execute(env=env, run=None, partner_id=p.id, delivery_mode='retiro',
                            lines=[{'product_id': prod60.id, 'qty': 2}])
            lines = SaleOrder.browse(r['order_id']).order_line.filtered(lambda l: l.product_id == prod60)
            assert all(abs(l.discount - 10.0) < 0.01 for l in lines), lines.mapped('discount')
            # Precio cerrado (price_unit): nunca lleva descuento, y no se informa ninguno.
            r = cso.execute(env=env, run=None, partner_id=p.id, delivery_mode='retiro',
                            lines=[{'product_id': product.id, 'qty': 1, 'price_unit': 50000}])
            lines = SaleOrder.browse(r['order_id']).order_line.filtered(lambda l: l.product_id == product)
            assert all(not l.discount for l in lines) and not r.get('auto_discount'), \
                (lines.mapped('discount'), r.get('auto_discount'))
            p2 = mk_lc('Nivel primera compra', 'Rio Cuarto')
            p2.write({'agent_level': 'plata', 'street': 'Calle Nivel 2'})
            r = cso.execute(env=env, run=None, partner_id=p2.id, discount_percent=20, delivery_mode='retiro',
                            lines=[{'product_id': prod60.id, 'qty': 1}])
            lines = SaleOrder.browse(r['order_id']).order_line.filtered(lambda l: l.product_id == prod60)
            assert all(abs(l.discount - 20.0) < 0.01 for l in lines) and not r.get('auto_discount'), \
                (lines.mapped('discount'), r.get('auto_discount'))
            # Borrador reutilizado con 20 %: al sumar un producto sin discount_percent, el 20 % se mantiene.
            r = cso.execute(env=env, run=None, partner_id=p2.id, delivery_mode='retiro',
                            lines=[{'product_id': prod60.id, 'qty': 1}, {'product_id': product.id, 'qty': 1}])
            lines = SaleOrder.browse(r['order_id']).order_line.filtered(lambda l: l.product_id == prod60)
            assert all(abs(l.discount - 20.0) < 0.01 for l in lines) and not r.get('auto_discount'), \
                (lines.mapped('discount'), r.get('auto_discount'))
            return ("PLATA → 5 % solo · ORO → 10 % · precio cerrado sin descuento · con 20 % de primera "
                    "compra no se acumula ni se pisa al reutilizar")
        self._case(results, "51. Beneficio por nivel en la cotización", c_niveles)

        # 52) Referidos: registro, crédito del referido, premio a quien recomendó al confirmar
        def c_referidos():
            cfg.write({'referral_discount': 5.0, 'referral_max_per_month': 3})
            viejo = mk_lc('Referidor', 'Rio Cuarto')
            viejo.street = 'Calle Ref 1'
            _confirmed(viejo, 20, amount=60000)
            nuevo = mk_lc('Referido', 'Rio Cuarto')
            nuevo.street = 'Calle Ref 2'
            rr = ToolRegistry.get('register_referral')
            r = rr.execute(env=env, run=None, partner_id=nuevo.id, referrer_partner_id=viejo.id)
            assert r.get('ok') and nuevo.agent_referred_by_id == viejo, r
            assert abs(nuevo.agent_referral_credit_pct - 5.0) < 0.01, nuevo.agent_referral_credit_pct
            r = rr.execute(env=env, run=None, partner_id=nuevo.id, referrer_name='ZZ Autotest Referidor')
            assert r.get('ok') and r['referrer']['partner_id'] == viejo.id, r
            q = cso.execute(env=env, run=None, partner_id=nuevo.id, delivery_mode='retiro',
                            lines=[{'product_id': prod60.id, 'qty': 1}])
            assert q.get('auto_discount', {}).get('reason') == 'crédito por referido', q.get('auto_discount')
            o = SaleOrder.browse(q['order_id'])
            acts_before = env['mail.activity'].sudo().search_count(
                [('res_model', '=', 'res.partner'), ('res_id', '=', viejo.id)])
            o.action_confirm()
            assert not nuevo.agent_referral_credit_pct and nuevo.agent_referral_rewarded, \
                (nuevo.agent_referral_credit_pct, nuevo.agent_referral_rewarded)
            assert abs(viejo.agent_referral_credit_pct - 5.0) < 0.01, viejo.agent_referral_credit_pct
            acts = env['mail.activity'].sudo().search([('res_model', '=', 'res.partner'), ('res_id', '=', viejo.id)])
            assert len(acts) == acts_before + 1 and any('Premio por referido' in (a.summary or '') for a in acts), \
                acts.mapped('summary')
            assert nuevo.agent_referral_rewarded_date, "sin fecha de premio"
            q2 = cso.execute(env=env, run=None, partner_id=viejo.id, delivery_mode='retiro',
                             lines=[{'product_id': prod60.id, 'qty': 1}])
            assert q2.get('auto_discount', {}).get('percent') == 5.0, q2.get('auto_discount')
            return ("registro por id y por nombre · 5 % al referido en su primer pedido · al confirmar, "
                    "crédito y aviso a quien recomendó · el crédito se usa en su próxima cotización")
        self._case(results, "52. Referidos", c_referidos)

        # ═════════════════ v1.57 — Reenganche de ruta, encuesta, ritual Oro ═════════════════
        # 53) Ruta: no pidió en la última pasada y el camión vuelve en pocos días
        def c_ruta_proxima():
            Dep = env['cristal.agent.route.departure'].sudo()
            zc = Circuit.create({'name': 'ZZ Autotest Reenganche', 'sequence': 96,
                                 'first_departure_date': today_ar})
            prev = Dep.create({'circuit_id': zc.id, 'date': today_ar - timedelta(days=4),
                               'state': 'realizada'})
            # Rescate: el cierre es el día anterior a las 12:00 → siempre futuro con +3.
            nxt = Dep.create({'circuit_id': zc.id, 'date': today_ar + timedelta(days=3),
                              'state': 'rescate'})
            assert zc.get_next_departure() == nxt, "la próxima salida no es la esperada"
            # Pedidos como cliente de Río Cuarto (sin el camino de la ruta); recién después
            # pasa al circuito. 20 y 50 días: fuera del ciclo y de la ventana de encuesta.
            p = mk_lc('Ruta saltó', 'Rio Cuarto')
            _confirmed(p, 20)
            _confirmed(p, 50)
            o = SaleOrder.browse(cso.execute(env=env, run=None, partner_id=p.id, delivery_mode='retiro',
                                             lines=[{'product_id': product.id, 'qty': 1,
                                                     'price_unit': 30000}])['order_id'])
            p.write({'agent_zone': 'ruta_camion', 'truck_circuit_id': zc.id})
            Life.recompute(p, today_ar)
            assert p.agent_lifecycle in ('active', 'at_risk'), p.agent_lifecycle
            st = Life.gather(p, today_ar)

            def cand():
                return NBA._candidate(p, st[p.id], today_ar, cfg)
            c = cand()
            assert c and c[0] == 'a_ruta_proxima', c
            # Ya pidió para la próxima salida → no se lo molesta
            o.route_departure_id = nxt.id
            c = cand()
            assert not c or c[0] != 'a_ruta_proxima', ("ya pidió y se lo avisaría", c)
            o.route_departure_id = False
            # Ya recibió el aviso masivo de esa salida → tampoco
            nxt.aviso_partner_ids = [(4, p.id)]
            c = cand()
            assert not c or c[0] != 'a_ruta_proxima', ("ya tuvo el aviso masivo", c)
            nxt.aviso_partner_ids = [(3, p.id)]
            # Una vez por salida: con el aviso ya registrado no se repite
            NBA.create({'partner_id': p.id, 'date': today_ar - timedelta(days=1),
                        'action_code': 'a_ruta_proxima', 'state': 'done'})
            c = cand()
            assert not c or c[0] != 'a_ruta_proxima', ("repite el aviso de la misma salida", c)
            return "sin pedido en la pasada anterior → aviso · con pedido o aviso masivo → nada · una vez por salida"
        self._case(results, "53. Ruta: reenganche a la próxima salida", c_ruta_proxima)

        # 54) Encuesta post-compra: candidato, envío por plantilla (en seco) y captura de la respuesta
        def c_encuesta():
            p = mk_lc('Encuesta', 'Rio Cuarto')
            _confirmed(p, 10)
            _confirmed(p, 50)
            _confirmed(p, 90)
            Life.recompute(p, today_ar)
            st = Life.gather(p, today_ar)
            assert p.agent_lifecycle == 'active', p.agent_lifecycle
            c = NBA._candidate(p, st[p.id], today_ar, cfg)
            tpl = NBA._survey_template()
            if not tpl:
                assert c is None or c[0] != 'a_encuesta', c
                return "sin plantilla cristal_satisfaccion aprobada: no se propone la encuesta"
            assert c and c[0] == 'a_encuesta', c
            created = NBA.plan(p, st, today_ar, cfg)     # modo en seco: registra, no manda
            assert created and created.channel == 'template' and created.state == 'dry_run', \
                (created.channel, created.state)
            # Captura de la respuesta: solo con encuesta mandada (done) hace poco
            assert p.agent_capture_survey('Regular') is None, "capturó sin encuesta mandada"
            created.state = 'done'
            for noise in ('Hola, quería saber el precio de la lavandina por 20 litros',
                          'Buen día', 'Buenas tardes, me pasás la lista?', '10 bidones',
                          'ahí te mando', 'no está mal el precio pero quiero 20 lts'):
                assert p.agent_capture_survey(noise) is None, f"tomó «{noise}» como respuesta"
            assert p.agent_capture_survey('Regular') == 'regular' and p.agent_survey_answer == 'regular', \
                p.agent_survey_answer
            assert p.agent_capture_survey('Mal') is None, "registró dos respuestas a la misma encuesta"
            # 90 días: no se repite
            assert NBA._candidate(p, st[p.id], today_ar, cfg) is None or \
                NBA._candidate(p, st[p.id], today_ar, cfg)[0] != 'a_encuesta', "repite la encuesta"
            return "activo 10 días después del pedido → encuesta · en seco no manda · respuesta corta registrada · una cada 90 días"
        self._case(results, "54. Encuesta post-compra", c_encuesta)

        # 55) Ritual Oro: primera semana del mes, una vez por mes
        def c_ritual_oro():
            p = mk_lc('Oro ritual', 'Rio Cuarto')
            p.agent_level = 'oro'
            _confirmed(p, 10)
            _confirmed(p, 40)
            Life.recompute(p, today_ar)
            st = Life.gather(p, today_ar)
            day1 = today_ar.replace(day=3)
            c = NBA._candidate(p, st[p.id], day1, cfg)
            assert c and c[0] == 'o_ritual', c
            NBA.create({'partner_id': p.id, 'date': day1, 'action_code': 'o_ritual', 'state': 'done'})
            c = NBA._candidate(p, st[p.id], day1 + timedelta(days=2), cfg)
            assert not c or c[0] != 'o_ritual', c
            day20 = today_ar.replace(day=20)
            c = NBA._candidate(p, st[p.id], day20, cfg)
            assert not c or c[0] != 'o_ritual', c
            p.agent_level = 'plata'
            c = NBA._candidate(p, st[p.id], day1, cfg)
            assert not c or c[0] != 'o_ritual', c
            return "ORO el día 3 → ritual · ya hecho este mes → no · día 20 → no · PLATA → no"
        self._case(results, "55. Ritual mensual ORO", c_ritual_oro)

        # ═════════════════ v1.58 — Pauta Cristal: contenido por salida ═════════════════
        # 56) Placas por ángulo + copys + guion para una salida a 7 días, idempotente
        def c_pauta_contenido():
            Dep = env['cristal.agent.route.departure'].sudo()
            Pauta = env['cristal.agent.pauta']
            Creative = env['cristal.agent.creative'].sudo()
            zc = Circuit.create({'name': 'ZZ Autotest Pauta', 'sequence': 95,
                                 'first_departure_date': today_ar})
            for n in ('La Carlota', 'Ucacha', 'Chazón'):
                env['cristal.agent.circuit.town'].sudo().create({'name': f'ZZ {n}', 'circuit_id': zc.id})
            dep = Dep.create({'circuit_id': zc.id, 'date': today_ar + timedelta(days=7),
                              'state': 'preventa'})
            cfg.write({'pauta_enabled': True, 'pauta_route_lead_days': 7,
                       'pauta_route_promo_qty': 7, 'pauta_route_free_from': 150000.0})
            ctx = Pauta.route_context(dep, cfg)
            assert 'ZZ La Carlota' in ctx['pueblos'] and ctx['promo_l1'] == '7 BIDONES DE 20 L', ctx
            assert '150.000' in ctx['condiciones'], ctx['condiciones']
            created = Pauta.generate_route_content(dep, config=cfg)
            assert len(created) == 5, f"{len(created)} creativos (esperaba 5)"
            for c in created:
                assert c.attachment_id and c.attachment_id.public and c.attachment_id.file_size > 20000, \
                    (c.angle, c.attachment_id.file_size)
                assert c.body and 'ZZ La Carlota' in c.body and c.headline, c.angle
                assert c.name.startswith('[RUTA-ZZ-AUTOTEST-PAUTA] ' + c.angle), c.name
            urg = created.filtered(lambda c: c.angle == 'URGENCIA')
            assert urg.activate_on == today_ar + timedelta(days=5), urg.activate_on
            assert created.filtered(lambda c: c.angle == 'REGALO').script, "sin guion"
            # Idempotente: el cron no repite
            n_before = Creative.search_count([('departure_id', '=', dep.id)])
            assert Pauta.cron_route_content() is True
            assert Creative.search_count([('departure_id', '=', dep.id)]) == n_before, "duplicó creativos"
            cfg.pauta_enabled = False
            assert Pauta.cron_route_content() is False, "con la pauta apagada igual corrió"
            cfg.pauta_enabled = True
            return ("salida a 7 días → 5 placas públicas por ángulo (> 20 KB), copy y título por ángulo, "
                    "guion en REGALO, URGENCIA programada a D-2 · cron idempotente · interruptor")
        self._case(results, "56. Pauta: contenido por salida", c_pauta_contenido)

        # ═════════════════ v1.59 — orgánico mensual y revisión mensual ═════════════════
        # 57) Calendario orgánico del mes siguiente: martes y viernes, placas públicas, idempotente
        def c_pauta_organico():
            Pauta = env['cristal.agent.pauta']
            Creative = env['cristal.agent.creative'].sudo()
            ms, nxt = Pauta._month_bounds(today_ar)
            target, after = Pauta._month_bounds(nxt)
            Creative.search([('format', '=', 'organico'), ('planned_date', '>=', target),
                             ('planned_date', '<', after)]).unlink()
            dates = Pauta._organic_dates(target)
            assert 8 <= len(dates) <= 10 and all(d.weekday() in (1, 4) for d in dates), dates
            created = Pauta.generate_organic_month(target, config=cfg)
            assert len(created) == len(dates), f"{len(created)} posteos (esperaba {len(dates)})"
            for c in created:
                assert c.format == 'organico' and c.planned_date in dates, (c.name, c.planned_date)
                assert c.attachment_id.public and c.attachment_id.file_size > 20000, c.name
                assert '#QuímicaCristal' in (c.body or '') and c.name.startswith('[ORGANICO] '), c.name
            angles = set(created.mapped('angle'))
            assert len(angles) >= 3, angles
            assert not Pauta.generate_organic_month(target, config=cfg), "duplicó posteos"
            assert Pauta.cron_organic_content(force=True) is True
            spec_angle, spec, body = Pauta.organic_spec('PRODUCTO', {'mes': 'X', 'mes_min': 'x',
                                                                    'clientes': 0, 'salidas': []})
            assert spec_angle == 'FABRICA', "PRODUCTO sin oferta debería caer en FABRICA"
            return (f"{len(created)} posteos martes/viernes con placa pública y texto, "
                    f"ángulos {', '.join(sorted(angles))} · idempotente · sin oferta → FABRICA")
        self._case(results, "57. Pauta: orgánico mensual", c_pauta_organico)

        # 58) Revisión mensual: arma, guarda snapshot y recomienda con reglas fijas
        def c_monthly_review():
            Review = env['cristal.agent.monthly.review'].sudo()
            prev_month = (today_ar.replace(day=1) - timedelta(days=1)).replace(day=1)
            Review.search([('month', '=', prev_month)]).unlink()
            r = Review.build(prev_month, post=False)
            assert r and 'Revisión mensual' in (r.body_html or ''), r.body_html
            data = json.loads(r.snapshot)
            assert {'sales', 'funnel', 'nba', 'route', 'claudio'} <= set(data), list(data)
            assert r.recommendations, "sin recomendaciones"
            fake = json.loads(r.snapshot)
            fake['nba']['by_action'] = {'c_promo': {'label': 'Promo', 'reached': 40, 'reached_conv': 2,
                                                    'holdout': 10, 'holdout_conv': 3, 'amount': 0}}
            fake['route'] = [{'name': 'ZZ', 'date': '2026-11-05', 'state': 'realizada',
                              'orders': 1, 'amount': 0}]
            rec = Review.recommend(fake, prev={'stages': {}, 'sales': {'amount': 0}})
            assert any('no vende más' in x for x in rec), rec
            assert any('ZZ' in x for x in rec), rec
            r2 = Review.build(prev_month, post=False)
            assert r2 == r, "duplicó la revisión del mes"
            return "arma HTML + snapshot, regla de control y de salida flojas, una sola por mes"
        self._case(results, "58. Revisión mensual", c_monthly_review)

        # 48) confirm_order: confirma solo lo que cumple la lista de control
        def c_confirm_order():
            co = ToolRegistry.get('confirm_order')
            cfg.write({'auto_confirm_enabled': True, 'auto_confirm_max_amount': 150000.0})
            p = mk_lc('Confirma OK', 'Rio Cuarto')
            p.street = 'Calle Falsa 123'
            oid = quote(p, 60000)['order_id']
            r = co.execute(env=env, run=None, partner_id=p.id, order_id=oid, payment='efectivo')
            assert r.get('confirmed') and SaleOrder.browse(oid).state == 'sale', r
            p2 = mk_lc('Confirma monto', 'Rio Cuarto')
            p2.street = 'Calle Falsa 456'
            o2 = quote(p2, 200000)['order_id']
            r = co.execute(env=env, run=None, partner_id=p2.id, order_id=o2, payment='transferencia')
            assert r.get('not_confirmed') and any('supera' in x for x in r['problems']), r
            p3 = mk_lc('Confirma sin dirección', 'Rio Cuarto')
            o3 = quote(p3, 60000)['order_id']
            r = co.execute(env=env, run=None, partner_id=p3.id, order_id=o3, payment='efectivo')
            assert r.get('not_confirmed') and any('dirección' in x for x in r['problems']), r
            p4 = mk_lc('Confirma ruta', 'Sampacho')
            p4.write({'agent_zone': 'ruta_camion', 'truck_circuit_id': so.id, 'street': 'Ruta 8'})
            o4 = cso.execute(env=env, run=None, partner_id=p4.id,
                             lines=[{'product_id': product.id, 'qty': 1, 'price_unit': 90000}])['order_id']
            r = co.execute(env=env, run=None, partner_id=p4.id, order_id=o4, payment='efectivo')
            assert r.get('not_confirmed'), r
            r = co.execute(env=env, run=None, partner_id=p.id, order_id=oid, payment='cheque')
            assert r.get('not_confirmed'), r
            cfg.auto_confirm_enabled = False
            o5 = quote(mk_lc('Confirma apagado', 'Rio Cuarto'), 60000)['order_id']
            r = co.execute(env=env, run=None, partner_id=SaleOrder.browse(o5).partner_id.id, order_id=o5, payment='efectivo')
            assert r.get('tool_disabled') or r.get('not_confirmed'), r
            cfg.auto_confirm_enabled = True
            return ("Río Cuarto con dirección y $60.000 → confirmado · $200.000 → no · sin dirección → no · "
                    "ruta del camión → no · cheque → no · apagado → no")
        self._case(results, "48. confirm_order: lista de control", c_confirm_order)
