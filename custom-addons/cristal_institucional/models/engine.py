import logging
from datetime import timedelta
from statistics import median

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Valores por defecto; se cambian en Ajustes → Técnico → Parámetros del sistema
# con la clave "cristal_institucional.<nombre>".
DEFAULTS = {
    'kit_followup_days': 5,            # a los cuántos días del kit se llama
    'first_purchase_deadline_days': 30,  # fecha límite para la primera compra, desde el kit
    'reorder_deadline_days': 30,       # fecha límite para el segundo pedido, desde la primera compra
    'reorder_call_days': 21,           # cuándo se llama para la reposición
    'default_cycle_days': 30,          # ritmo de compra si todavía no hay historial
    'risk_factor_pct': 150,            # en riesgo: pasó 1,5 veces su ritmo
    'dormant_cycles': 3,               # dormido: pasó 3 veces su ritmo...
    'dormant_min_days': 90,            # ...o al menos 90 días
    'inactive_days': 365,              # sin comprar hace más de un año: pasa a Inactivo (hay que volver a ganarlo)
    'daily_calls': 15,                 # contactos por día y por persona
    'daily_new': 5,                    # de esos, cuántos se reservan para empresas nuevas (prospectos y captación)
    'default_user_id': 18,             # responsable cuando la empresa no tiene vendedor
}
KIT_TAG_PARAM = 'cristal_institucional.kit_tag'
KIT_TAG_DEFAULT = 'Regalo captación'


class CristalInstEngine(models.AbstractModel):
    _name = 'cristal.inst.engine'
    _description = 'Institucional: motor de etapas, alertas y próximo paso'

    # ------------------------------------------------------------------ config
    @api.model
    def _params(self):
        icp = self.env['ir.config_parameter'].sudo()
        out = {}
        for key, default in DEFAULTS.items():
            try:
                out[key] = int(icp.get_param('cristal_institucional.%s' % key, default))
            except (TypeError, ValueError):
                out[key] = default
        out['kit_tag'] = icp.get_param(KIT_TAG_PARAM, KIT_TAG_DEFAULT)
        # espera: los WhatsApp no se piden a mano, quedan listos para cuando el número esté conectado
        # manual: aparecen como paso para mandarlos a mano
        out['whatsapp_mode'] = icp.get_param('cristal_institucional.whatsapp_mode', 'espera')
        # Quiénes trabajan cuentas institucionales (ids de usuario separados por coma)
        raw = icp.get_param('cristal_institucional.team_user_ids', str(out['default_user_id']))
        out['team_user_ids'] = {int(x) for x in raw.replace(' ', '').split(',') if x.isdigit()}
        return out

    # ------------------------------------------------------------------- datos
    @api.model
    def _gather(self, partners, params):
        """Devuelve por empresa: compras reales (fecha, monto, margen) y el kit."""
        data = {p.id: {'orders': [], 'kit_order': False, 'kit_date': False, 'fams': {}, 'quote': 0.0}
                for p in partners}
        if not partners:
            return data
        since = fields.Date.context_today(self) - timedelta(days=365)
        recent = {}
        SaleOrder = self.env['sale.order'].sudo()
        orders = SaleOrder.search([
            ('partner_id', 'child_of', partners.ids),
            ('state', '!=', 'cancel'),
        ])
        has_tags = 'tag_ids' in SaleOrder._fields
        kit_tag = (params['kit_tag'] or '').strip().lower()
        for order in orders:
            pid = order.partner_id.commercial_partner_id.id
            if pid not in data:
                continue
            is_kit = bool(has_tags and kit_tag and any(
                (t.name or '').strip().lower() == kit_tag for t in order.tag_ids))
            if is_kit:
                delivered = False
                if order.state in ('sale', 'done'):
                    done = order.picking_ids.filtered(lambda pk: pk.state == 'done' and pk.date_done)
                    if done:
                        delivered = max(done.mapped('date_done')).date()
                current = data[pid]
                if not current['kit_order'] or (delivered and not current['kit_date']):
                    current['kit_order'] = order.id
                    current['kit_date'] = delivered
                continue
            if order.state in ('sale', 'done') and order.amount_untaxed > 0:
                data[pid]['orders'].append(
                    (order.date_order.date(), order.amount_untaxed, order.margin or 0.0))
                if order.date_order.date() >= since:
                    recent[order.id] = pid
            elif order.state in ('draft', 'sent') and order.amount_untaxed > 0:
                data[pid]['quote'] = max(data[pid]['quote'], order.amount_untaxed)
        # Qué familias de productos compró cada empresa en los últimos 12 meses
        if recent:
            lines = self.env['sale.order.line'].sudo().search([
                ('order_id', 'in', list(recent)),
                ('display_type', '=', False),
                ('price_subtotal', '>', 0),
                ('product_id', '!=', False),
            ])
            for line in lines:
                if line.product_id.type == 'service':
                    continue        # fletes y servicios no son "lo que compra"
                fams = data[recent[line.order_id.id]]['fams']
                fam = self._family(line.product_id.categ_id)
                fams[fam] = fams.get(fam, 0.0) + line.price_subtotal
        if 'pos.order' in self.env:
            PosOrder = self.env['pos.order'].sudo()
            pos_orders = PosOrder.search([
                ('partner_id', 'child_of', partners.ids),
                ('state', 'in', ('paid', 'done', 'invoiced')),
                ('amount_total', '>', 0),
            ])
            for order in pos_orders:
                pid = order.partner_id.commercial_partner_id.id
                if pid in data:
                    untaxed = (order.amount_total or 0.0) - (order.amount_tax or 0.0)
                    margin = order.margin if 'margin' in PosOrder._fields else 0.0
                    data[pid]['orders'].append((order.date_order.date(), untaxed, margin or 0.0))
        return data

    @api.model
    def _family(self, categ):
        """Familia = los dos primeros niveles de la categoría (ej. 'Fabricación / Detergente')."""
        parts = [p.strip() for p in (categ.complete_name or '').split(' / ') if p.strip()]
        return ' / '.join(parts[:2]) if parts else ''

    @api.model
    def _reference_families(self):
        """Familias de fabricación propia: son las que más margen dejan y las que conviene sumar."""
        Categ = self.env['product.category'].sudo()
        roots = Categ.search([('parent_id', '=', False), ('name', '=ilike', 'Fabricaci%')])
        if not roots:
            roots = Categ.search([('name', '=ilike', 'Fabricaci%')], limit=1)
        children = Categ.search([('parent_id', 'in', roots.ids)]) if roots else Categ
        return sorted({self._family(c) for c in children if self._family(c)})

    # ------------------------------------------------------------ clasificación
    @api.model
    def _classify(self, partner, info, params, today):
        orders = sorted(info['orders'])
        dates = sorted({d for d, _a, _m in orders})
        count = len(dates)
        vals = {
            'inst_order_count': count,
            'inst_first_order': dates[0] if dates else False,
            'inst_last_order': dates[-1] if dates else False,
            'inst_kit_order_id': info['kit_order'] or False,
        }
        kit_date = partner.inst_kit_date or info['kit_date'] or False
        if info['kit_date'] and not partner.inst_kit_date:
            vals['inst_kit_date'] = info['kit_date']
        contactado = partner.inst_contactado
        if not contactado and (partner.inst_decisor_id or kit_date or info['kit_order']):
            contactado = today
            vals['inst_contactado'] = today

        # Indicadores de los últimos 12 meses
        since = today - timedelta(days=365)
        amount = sum(a for d, a, _m in orders if d >= since)
        margin = sum(m for d, _a, m in orders if d >= since)
        months = 12.0
        if dates and dates[0] > since:
            months = max(1.0, (today - dates[0]).days / 30.0)
        vals.update({
            'inst_amount_12m': amount,
            'inst_margin_12m': margin,
            'inst_margin_month': margin / months if margin else 0.0,
            'inst_margin_pct': (100.0 * margin / amount) if amount else 0.0,
        })

        # Ritmo de compra propio de la empresa
        gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        cycle = max(7, int(median(gaps))) if gaps else params['default_cycle_days']
        days_since = (today - dates[-1]).days if dates else 0
        vals['inst_cycle_days'] = cycle if dates else 0

        # Qué compra y qué le falta sumar (fabricación propia)
        fams = info.get('fams') or {}
        short = lambda fam: fam.split(' / ')[-1]
        gaps = [short(f) for f in params.get('ref_fams', []) if f not in fams] if count else []
        top = sorted(fams, key=lambda f: -fams[f])[:5]      # lo que más compra, primero
        vals['inst_buys'] = ', '.join(short(f) for f in top)[:250] or False
        vals['inst_gaps'] = ', '.join(gaps)[:250] or False

        alert = 'ok'
        step, step_date, deadline, expected, late = False, False, False, False, 0

        if partner.inst_discarded:
            stage = 'descartado'
            reason = partner.inst_discard_reason or 'Descartado'
            alert = False
        elif count and days_since > params['inactive_days']:
            # Compró alguna vez pero hace más de un año: no es un cliente atrasado,
            # hay que volver a ganarlo. Tiene su propio camino, con kit.
            stage = 'inactivo'
            reason = 'Compró %s %s; la última, hace %s meses' % (
                count, 'vez' if count == 1 else 'veces', days_since // 30)
            kit_again = bool(kit_date and kit_date > dates[-1])
            if kit_again:
                step = 'Llamar: cómo les fue con el kit y pasar la propuesta para que vuelvan a comprar'
                step_date = kit_date + timedelta(days=params['kit_followup_days'])
                deadline = kit_date + timedelta(days=params['first_purchase_deadline_days'])
            elif info['kit_order']:
                step = 'Entregar el kit de prueba'
                step_date = today
            elif partner.inst_last_result == 'kit':
                step = 'Cargar el kit de prueba y entregarlo'
                step_date = today
            else:
                step = 'Reactivar: saber por qué dejó de comprar y ofrecerle el kit con la nueva formulación'
                step_date = today
        elif count >= 2:
            stage = 'recurrente'
            expected = dates[-1] + timedelta(days=cycle)
            late = max(0, (today - expected).days)
            reason = '%s compras; compra cada %s días' % (count, cycle)
            if days_since > max(params['dormant_cycles'] * cycle, params['dormant_min_days']):
                alert = 'dormido'
                step = 'Llamar: lleva %s días sin comprar. Saber por qué dejó de comprar' % days_since
                step_date = today
            elif days_since > cycle * params['risk_factor_pct'] / 100.0:
                alert = 'riesgo'
                step = 'Llamar: se atrasó %s días respecto de su ritmo de compra' % late
                step_date = today
            else:
                step = 'Reposición esperada: confirmar el pedido'
                if gaps:
                    step += ' y ofrecerle %s' % ' o '.join(gaps[:2]).lower()
                step_date = expected
        elif count == 1:
            stage = 'pedido_formal'
            reason = 'Una compra, el %s' % dates[-1].strftime('%d/%m/%Y')
            step = 'Llamada de reposición: cómo les fue y armar el mismo pedido'
            step_date = dates[-1] + timedelta(days=params['reorder_call_days'])
            deadline = dates[-1] + timedelta(days=params['reorder_deadline_days'])
            expected = deadline
            if days_since > params['dormant_min_days']:
                alert = 'dormido'
                step = 'Llamar: compró una vez hace %s días y no volvió. Saber por qué' % days_since
                step_date = today
                deadline = False
        elif kit_date:
            stage = 'primera_compra'
            reason = 'Kit entregado el %s, todavía no compró' % kit_date.strftime('%d/%m/%Y')
            step = 'Llamar: cómo les fue con el kit y pasar la propuesta de primera compra'
            step_date = kit_date + timedelta(days=params['kit_followup_days'])
            deadline = kit_date + timedelta(days=params['first_purchase_deadline_days'])
        elif contactado:
            stage = 'captacion'
            if info['kit_order']:
                reason = 'Kit cargado, falta entregarlo'
                step = 'Entregar el kit de prueba'
            elif partner.inst_last_result == 'kit':
                reason = 'Aceptó el kit, falta cargarlo'
                step = 'Cargar el kit de prueba y entregarlo'
            elif partner.inst_ficha_falta:
                reason = 'Falta en la ficha: %s' % partner.inst_ficha_falta
                step = 'Completar la ficha y ofrecer el kit de prueba'
            else:
                reason = 'Ficha completa, falta cargar el kit'
                step = 'Cargar y entregar el kit de prueba'
            step_date = today
        else:
            stage = 'prospecto'
            reason = 'Todavía no hablamos con nadie de la empresa'
            step = 'Llamar: conseguir a quien decide las compras'
            step_date = today

        # Cola de llamadas: prospectos y captación sin un paso con fecha propia se reparten
        # de a pocos por día hábil. La fecha la pone _fill_queue.
        kit_running = bool(stage == 'inactivo' and kit_date and dates and kit_date > dates[-1])
        pool = (stage in ('prospecto', 'captacion', 'inactivo') and not info['kit_order'] and not kit_running
                and partner.inst_last_result != 'kit')
        if pool:
            step_date = partner.inst_queue_date or False
            if partner.inst_attempts and not step_date:
                step_date = today       # un reintento no vuelve al final de la cola

        # Cadena de avisos: después del kit, después de la primera compra, o recurrente atrasado
        chain, anchor = False, False
        if kit_date and (stage == 'primera_compra' or kit_running):
            chain, anchor = 'kit', kit_date
        elif stage == 'pedido_formal' and dates:
            chain, anchor = 'reposicion', dates[-1]
        elif stage == 'recurrente' and expected and late > 0:
            chain, anchor = 'atraso', expected
        same = chain and partner.inst_chain == chain and partner.inst_chain_anchor == anchor
        done = partner.inst_chain_done if same else 0
        chain_step = False
        auto_step = False
        if chain:
            steps = params.get('chains', {}).get(chain, [])
            pending = [s for s in steps if s['sequence'] > done]
            if params.get('whatsapp_mode') == 'manual':
                nxt = pending[0] if pending else None
            else:
                # Los WhatsApp no se le piden a una persona: quedan listos para salir solos.
                # El próximo paso de la persona es la primera llamada o visita de la cadena.
                manual = [s for s in pending if s['channel'] != 'whatsapp']
                nxt = manual[0] if manual else None
                elapsed = (today - anchor).days
                limit = nxt['day'] if nxt else 10 ** 6
                ready = [s for s in pending
                         if s['channel'] == 'whatsapp' and s['day'] <= elapsed and s['day'] < limit]
                if ready and elapsed < limit:
                    auto_step = ready[-1]['id']
            if nxt:
                chain_step = nxt['id']
                step = '%s: %s' % (nxt['channel_label'], nxt['name'])
                if chain == 'atraso' and alert == 'ok':
                    step = 'Si no repone antes de esta fecha: %s' % nxt['channel_label'].lower()
                step_date = anchor + timedelta(days=nxt['day'])
                # Entre un aviso y el siguiente se respeta la espera de la cadena,
                # aunque el cliente venga muy atrasado.
                if done and partner.inst_last_call:
                    prev = next((s for s in steps if s['sequence'] == done), None)
                    gap = max(1, nxt['day'] - (prev['day'] if prev else 0))
                    step_date = max(step_date, partner.inst_last_call + timedelta(days=gap))
            elif steps:
                step = 'Se terminó la cadena de avisos sin respuesta: llamar, posponer o descartar'
                step_date = today
        vals.update({
            'inst_chain': chain,
            'inst_chain_anchor': anchor,
            'inst_chain_done': done,
            'inst_chain_step_id': chain_step,
            'inst_auto_step_id': auto_step,
        })

        # Lo que contestó el cliente la última vez define el paso, por encima de la cadena.
        # Se limpia solo si después de esa respuesta entró una compra.
        custom_on = False
        if partner.inst_custom_step and stage != 'descartado':
            set_on = partner.inst_custom_set
            if dates and set_on and dates[-1] >= set_on:
                vals['inst_custom_step'] = False
                vals['inst_custom_set'] = False
            else:
                custom_on = True
                step = partner.inst_custom_step
                step_date = today
                pool = False

        # Posponer: corre el paso y la fecha límite
        postponed = partner.inst_postponed_until
        if postponed and stage != 'descartado':
            if postponed > today:
                step_date = postponed
                pool = False
                if partner.inst_last_result == 'whatsapp' and step:
                    step = 'Esperando respuesta al WhatsApp. Si no contesta: %s%s' % (step[:1].lower(), step[1:])
                if deadline and deadline < postponed:
                    deadline = postponed
                if alert in ('riesgo', 'dormido'):
                    alert = 'ok'
            else:
                vals['inst_postponed_until'] = False
        if stage != 'descartado' and alert == 'ok' and deadline and deadline < today and not custom_on:
            alert = 'vence'
            step = 'Venció el plazo. %s' % (step or 'Posponer con nueva fecha o descartar')
            step_date = today
        if stage == 'descartado':
            step, step_date, deadline = False, False, False

        # Cuánto se atrasó, para que el paso diga algo concreto
        if chain == 'atraso' and late > 0 and step and alert in ('riesgo', 'dormido') and not custom_on:
            step = '%s (%s días de atraso)' % (step, late)

        # Sin forma de contactarla: el paso es conseguir el dato, y no ocupa lugar en la fila de llamadas
        decisor = partner.inst_decisor_id
        has_phone = bool(partner.phone or partner.mobile or decisor.phone or decisor.mobile)
        no_phone = bool(stage != 'descartado' and not has_phone)
        vals['inst_no_phone'] = no_phone
        if (no_phone or partner.inst_missing_data) and step and stage != 'descartado':
            step = 'Conseguir un teléfono o contacto válido'
            if no_phone and pool:
                pool = False
                current = partner.inst_next_step_date
                step_date = current if (current and current > today) else today + timedelta(days=30)

        # Intentos sin respuesta: al tercero se cambia de canal
        attempts = partner.inst_attempts
        if step and attempts and stage != 'descartado':
            if attempts >= 3:
                step = 'No atiende hace %s intentos: escribirle por WhatsApp o pasar por el local' % attempts
            else:
                step = '%s (intento %s)' % (step, attempts + 1)

        # Prioridad para ordenar "Mi día": primero lo que se puede perder y lo que más margen deja
        weights = {
            ('recurrente', 'riesgo'): 9, ('recurrente', 'dormido'): 6, ('recurrente', 'ok'): 2,
            ('primera_compra', 'vence'): 8, ('primera_compra', 'ok'): 7,
            ('pedido_formal', 'vence'): 8, ('pedido_formal', 'ok'): 7, ('pedido_formal', 'dormido'): 5,
            ('captacion', 'ok'): 4, ('prospecto', 'ok'): 3, ('inactivo', 'ok'): 5, ('inactivo', 'vence'): 6,
        }
        weight = weights.get((stage, alert), 0)
        if stage == 'captacion' and info['kit_order']:
            weight = 6
        margin_points = min(999.0, (vals.get('inst_margin_12m') or 0.0) / 10000.0)
        if pool:
            # En la cola van primero los que ya tienen con quién hablar, teléfono y una cotización pedida
            margin_points = 0.0
            if partner.inst_attempts:
                margin_points += 500
            if partner.inst_decisor_id:
                margin_points += 200
            if partner.phone or partner.mobile:
                margin_points += 150
            margin_points += min(99.0, (info.get('quote') or 0.0) / 10000.0)
        vals['inst_priority'] = round(weight * 1000 + margin_points, 2) if weight else 0.0
        vals['inst_in_pool'] = bool(pool and stage != 'descartado')
        if not vals['inst_in_pool']:
            vals['inst_queue_date'] = False
        elif step_date and not partner.inst_queue_date:
            vals['inst_queue_date'] = step_date

        vals.update({
            'inst_stage': stage,
            'inst_reason': reason,
            'inst_alert': alert,
            'inst_next_step': step,
            'inst_next_step_date': step_date,
            'inst_deadline': deadline,
            'inst_next_expected': expected,
            'inst_days_late': late,
        })
        if stage != partner.inst_stage:
            vals['inst_stage_date'] = today
        if not step_date or step_date > today:
            vals['inst_today'] = False      # ya no es para hoy: sale de "Mi día"
        # Lo que la persona decidió a mano manda sobre el cálculo
        if partner.inst_skip_date == today:
            vals['inst_today'] = False
        elif partner.inst_pinned_date == today and stage != 'descartado':
            vals['inst_today'] = True
            if not step:
                vals['inst_next_step'] = 'Llamar'
            if not step_date or step_date > today:
                vals['inst_next_step_date'] = today
        if partner.inst_skip_date and partner.inst_skip_date < today:
            vals['inst_skip_date'] = False
        if partner.inst_pinned_date and partner.inst_pinned_date < today:
            vals['inst_pinned_date'] = False
        # Responsable: el vendedor de la empresa si forma parte del equipo institucional;
        # si no, el responsable por defecto. Nadie queda sin asignar.
        seller = partner.user_id
        if seller and seller.active and seller.id in params.get('team_user_ids', ()):
            vals['inst_user_id'] = seller.id
        else:
            vals['inst_user_id'] = params.get('default_user_id') or False
        return vals

    @api.model
    def _pick_today(self, params, today):
        """"Mi día" de verdad: de todo lo que vence, solo lo más importante, hasta el cupo diario.
        Lo que no entra hoy no se pierde: queda primero en la fila de mañana."""
        quota = max(1, params.get('daily_calls') or 15)
        Partner = self.env['res.partner'].sudo().with_context(inst_engine=True, tracking_disable=True)
        if today.weekday() >= 5:
            Partner.search([('inst_today', '=', True)]).write({'inst_today': False})
            return
        new_share = min(quota, max(0, params.get('daily_new') or 0))
        due = Partner.search([
            ('inst_is', '=', True), ('inst_stage', '!=', 'descartado'),
            ('inst_next_step', '!=', False), ('inst_next_step_date', '<=', today),
            '|', ('inst_skip_date', '=', False), ('inst_skip_date', '!=', today),
        ], order='inst_priority desc, inst_next_step_date, id')
        # Lo que la persona agregó a mano entra siempre
        chosen = Partner.search([('inst_is', '=', True), ('inst_pinned_date', '=', today),
                                 ('inst_stage', '!=', 'descartado')])
        # Cada responsable tiene su propio día. Se reserva un lugar para empresas nuevas,
        # así cuidar a los clientes no deja la captación en cero.
        for user in due.mapped('inst_user_id'):
            mine = due.filtered(lambda p, u=user: p.inst_user_id == u)
            accounts = mine.filtered(lambda p: not p.inst_in_pool)
            fresh = mine.filtered('inst_in_pool')
            take_new = fresh[:new_share]
            take_acc = accounts[:quota - len(take_new)]
            rest = quota - len(take_new) - len(take_acc)
            if rest > 0:
                take_new |= (fresh - take_new)[:rest]
            chosen |= take_acc | take_new
        (Partner.search([('inst_today', '=', True)]) - chosen).write({'inst_today': False})
        chosen.filtered(lambda p: not p.inst_today).write({'inst_today': True})

    # ---------------------------------------------------------------- cálculo
    @api.model
    def recompute(self, partners=None):
        Partner = self.env['res.partner'].sudo()
        full = partners is None
        if partners is None:
            partners = Partner.search([('inst_is', '=', True)])
        else:
            partners = partners.sudo().filtered('inst_is')
        if not partners:
            return 0
        params = self._params()
        params['ref_fams'] = self._reference_families()
        Step = self.env['cristal.inst.chain.step'].sudo()
        channel_labels = dict(Step._fields['channel'].selection)
        params['chains'] = {}
        for chain_step in Step.search([('active', '=', True)], order='chain, sequence, id'):
            params['chains'].setdefault(chain_step.chain, []).append({
                'id': chain_step.id, 'sequence': chain_step.sequence, 'day': chain_step.day,
                'name': chain_step.name, 'channel_label': channel_labels.get(chain_step.channel, ''),
                'channel': chain_step.channel,
            })
        StageLog = self.env['cristal.inst.stage.log'].sudo()
        today = fields.Date.context_today(self)
        now = fields.Datetime.now()
        data = self._gather(partners, params)
        changed = 0
        for partner in partners.with_context(tracking_disable=True, inst_engine=True):
            vals = self._classify(partner, data[partner.id], params, today)
            diff = {}
            for key, value in vals.items():
                current = partner[key]
                if partner._fields[key].type == 'many2one':
                    current = current.id
                if (current or False) != (value or False):
                    diff[key] = value
            if diff:
                changed += 1
                diff['inst_computed_at'] = now
                if 'inst_stage' in diff:
                    previous_date = partner.inst_stage_date
                    StageLog.create({
                        'partner_id': partner.id,
                        'date': today,
                        'stage_from': partner.inst_stage or False,
                        'stage_to': diff['inst_stage'],
                        'days_in_previous': (today - previous_date).days if previous_date else 0,
                    })
                partner.write(diff)
        if full:
            self._fill_queue(params, today)
            self._pick_today(params, today)
        self._sync_crm(partners, params)
        _logger.info('Institucional: %s empresas evaluadas, %s con cambios', len(partners), changed)
        return changed

    @api.model
    def _cron_refresh(self):
        self._scope()
        self.recompute()

    @api.model
    def _touch(self, partners):
        """Recalcula en el momento las empresas tocadas por un pedido o una entrega.
        Nunca frena la operación de ventas o de depósito: si algo falla, queda en el log
        y se corrige en la corrida de la noche."""
        try:
            partners = partners.sudo().filtered('inst_is')
            if partners:
                with self.env.cr.savepoint():
                    self.recompute(partners)
        except Exception:  # noqa: BLE001
            _logger.exception('Institucional: no se pudo recalcular en el momento')
        return True

    @api.model
    def _resync(self, partners):
        """Vuelve a poner la tarjeta en su columna si alguien o algo la movió."""
        try:
            partners = partners.sudo().filtered('inst_is')
            if partners:
                with self.env.cr.savepoint():
                    self._sync_crm(partners, self._params())
        except Exception:  # noqa: BLE001
            _logger.exception('Institucional: no se pudo reacomodar la tarjeta')
        return True

    # ------------------------------------------------- quién entra al sistema
    @api.model
    def _scope(self):
        """Suma al flujo institucional a toda empresa que corresponde:
        la que tiene la etiqueta EMPRESA, y la que no la tiene pero es una persona jurídica
        que nos compró y no es revendedora. Las segundas quedan marcadas "para revisar"."""
        Partner = self.env['res.partner'].sudo().with_context(inst_engine=True, tracking_disable=True)
        Category = self.env['res.partner.category'].sudo()
        tag_inst = Category.search([('name', '=ilike', 'EMPRESA')])
        tag_whole = Category.search([('name', 'ilike', 'mayorista')])
        company_partners = self.env['res.company'].sudo().search([]).mapped('partner_id')
        internal = self.env['res.users'].sudo().with_context(active_test=False).search(
            [('share', '=', False)]).mapped('partner_id')
        skip = (company_partners | internal).ids
        Partner.search([('inst_is', '=', True), ('inst_source', '=', False)]).write({'inst_source': 'alejandra'})
        added = 0
        if tag_inst:
            tagged = Partner.search([
                ('category_id', 'in', tag_inst.ids), ('parent_id', '=', False),
                ('inst_is', '=', False), ('inst_excluded', '=', False), ('id', 'not in', skip)])
            if tagged:
                tagged.write({'inst_is': True, 'inst_source': 'etiqueta'})
                added += len(tagged)
        # Sin etiqueta: personas jurídicas (CUIT 30, 33 o 34, o marcadas como empresa)
        # con al menos una compra confirmada, que no sean mayoristas.
        buyers = self.env['sale.order'].sudo()._read_group(
            [('state', 'in', ('sale', 'done')), ('amount_untaxed', '>', 0)],
            groupby=['partner_id'])
        buyer_ids = self.env['res.partner'].sudo().browse(
            [p.id for (p,) in buyers]).mapped('commercial_partner_id').ids
        if buyer_ids:
            domain = [
                ('id', 'in', buyer_ids), ('parent_id', '=', False),
                ('inst_is', '=', False), ('inst_excluded', '=', False), ('id', 'not in', skip),
                '|', '|', '|', ('is_company', '=', True),
                ('vat', '=like', '30%'), ('vat', '=like', '33%'), ('vat', '=like', '34%'),
            ]
            if tag_whole:
                domain.append(('category_id', 'not in', tag_whole.ids))
            candidates = Partner.search(domain)
            if 'agent_level' in Partner._fields:
                candidates = candidates.filtered(lambda p: p.agent_level in (False, 'none'))
            if candidates:
                candidates.write({'inst_is': True, 'inst_source': 'criterio', 'inst_review': True})
                added += len(candidates)
        if added:
            _logger.info('Institucional: %s empresas nuevas entraron al flujo', added)
        self._enrich()
        return added

    # ------------------------------------------- completar solo lo que se puede
    RUBRO_RULES = [
        # (comienzos de palabra que delatan el rubro, texto para encontrar el rubro en Odoo)
        (('gastronom', 'restaurant', 'resto', 'restobar', 'parrilla', 'pizz', 'panader', 'helader', 'cafe',
          'rotiser', 'comedor', 'catering', 'cervecer', 'bar', 'bodegon', 'confiter', 'sandwich', 'empanad',
          'pastas', 'hamburgues', 'lomiter', 'cantina', 'pasteler'), 'gastronom'),
        (("hotel", "apart", "hosteria", "hostel", "cabanas"), "hotel"),
        (("colegio", "instituto", "escuela", "jardin", "universidad", "educa", "academia"), "educaci"),
        (('clinica', 'sanatorio', 'hospital', 'medic', 'consultorio', 'geriatr', 'salud', 'odontolog',
          'laboratorio', 'farmacia', 'veterinar', 'rehabilita'), 'salud'),
        (('club', 'complejo', 'gimnasio', 'gym', 'fitness', 'deport', 'autodromo'), 'club'),
        (('estacion de servicio', 'ypf', 'shell', 'axion', 'gulf'), 'estaci'),
        (('carnicer', 'frigorif', 'carnes', 'granja', 'poller', 'fiambr', 'chacinad'), 'carne'),
        (('logistic', 'transporte', 'industria', 'fabrica', 'metalurg', 'agro', 'constru'), 'industria'),
    ]

    @api.model
    def _plain(self, text):
        import unicodedata
        text = unicodedata.normalize('NFD', (text or '').lower())
        return ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')

    @api.model
    def _enrich(self):
        """Completa lo que se puede deducir: el rubro (por etiquetas y nombre) y un posible contacto
        (por los contactos cargados en la empresa o el nombre anotado en oportunidades viejas).
        Nunca pisa lo que una persona cargó."""
        import re
        Partner = self.env['res.partner'].sudo().with_context(inst_engine=True, tracking_disable=True)
        Industry = self.env['res.partner.industry'].sudo()
        industries = Industry.search([])
        # El nombre del rubro se lee en todos los idiomas instalados: la tarea nocturna corre
        # sin idioma y vería "Education" en vez de "Educación".
        langs = [code for code, _name in self.env['res.lang'].sudo().get_installed()]
        names = {
            industry.id: ' '.join(self._plain(industry.with_context(lang=lang).name) for lang in langs)
            for industry in industries
        }
        rules = []
        for words, key in self.RUBRO_RULES:
            industry = industries.filtered(lambda i, k=key: k in names[i.id])[:1]
            if industry:
                # Las palabras cortas van enteras ("bar" no tiene que agarrar "barrio")
                rules.append((re.compile(r'\b(%s)' % '|'.join(
                    re.escape(w) + (r'\b' if len(w) <= 4 else '') for w in words)), industry.id))
        if rules:
            for partner in Partner.search([('inst_is', '=', True), ('industry_id', '=', False)]):
                text = self._plain(' '.join(partner.category_id.mapped('name')) + ' ' + (partner.name or ''))
                for pattern, industry_id in rules:
                    if pattern.search(text):
                        partner.write({'industry_id': industry_id, 'inst_rubro_auto': True})
                        break

        Lead = self.env['crm.lead'].sudo().with_context(active_test=False)
        pending = Partner.search([('inst_is', '=', True), ('inst_decisor_id', '=', False)])
        lead_names = {}
        for lead in Lead.search([('inst_partner_id', 'in', pending.ids), ('contact_name', '!=', False)],
                                order='id'):
            lead_names[lead.inst_partner_id.id] = lead.contact_name
        for partner in pending:
            contacts = partner.child_ids.filtered(lambda c: c.type == 'contact' and c.active and c.name)
            hint = False
            if contacts:
                parts = []
                for contact in contacts[:2]:
                    number = contact.mobile or contact.phone
                    label = contact.name
                    if contact.function:
                        label += ' (%s)' % contact.function
                    if number:
                        label += ', %s' % number
                    parts.append(label)
                hint = ' · '.join(parts)
            elif lead_names.get(partner.id):
                hint = lead_names[partner.id]
            if (partner.inst_contact_hint or False) != (hint or False):
                partner.write({'inst_contact_hint': hint})
        Partner.search([('inst_decisor_id', '!=', False), ('inst_contact_hint', '!=', False)]).write(
            {'inst_contact_hint': False})
        return True

    @api.model
    def _pull_more(self, count):
        """Suma a "Mi día" las cuentas que siguen en prioridad."""
        today = fields.Date.context_today(self)
        Partner = self.env['res.partner'].sudo().with_context(inst_engine=True, tracking_disable=True)
        more = Partner.search([
            ('inst_is', '=', True), ('inst_stage', '!=', 'descartado'), ('inst_today', '=', False),
            ('inst_next_step', '!=', False),
            '|', ('inst_skip_date', '=', False), ('inst_skip_date', '!=', today),
            '|', ('inst_next_step_date', '<=', today), ('inst_in_pool', '=', True),
        ], order='inst_priority desc, id', limit=count)
        if not more:
            return 0
        more.filtered('inst_in_pool').write({'inst_queue_date': today, 'inst_next_step_date': today})
        more.write({'inst_today': True})
        self._sync_crm(more, self._params())
        return len(more)

    # ------------------------------------------------------- cola de llamadas
    @api.model
    def _next_workday(self, day):
        nxt = day + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        return nxt

    @api.model
    def _fill_queue(self, params, today):
        """Reparte prospectos y captación de a pocos por día hábil, por prioridad.
        Así todos tienen un próximo paso con fecha y "Mi día" no explota."""
        quota = max(1, params.get('daily_new') or params.get('daily_calls') or 5)
        Partner = self.env['res.partner'].sudo().with_context(inst_engine=True, tracking_disable=True)
        pool = Partner.search([('inst_is', '=', True), ('inst_in_pool', '=', True)], order='inst_priority desc, id')
        start = today
        while start.weekday() >= 5:
            start += timedelta(days=1)
        plan = {}
        for user in pool.mapped('inst_user_id'):
            mine = pool.filtered(lambda p, u=user: p.inst_user_id == u)
            fixed = mine.filtered(lambda p: p.inst_queue_date and p.inst_queue_date <= start)
            load = {start: len(fixed)}
            day = start
            for partner in mine - fixed:
                while load.get(day, 0) >= quota:
                    day = self._next_workday(day)
                load[day] = load.get(day, 0) + 1
                if partner.inst_queue_date != day or partner.inst_next_step_date != day:
                    plan.setdefault(day, []).append(partner.id)
        for day, ids in plan.items():
            Partner.browse(ids).write({'inst_queue_date': day, 'inst_next_step_date': day})
        return True

    # ----------------------------------------------------------- CRM
    INST_STAGE_NAMES = [
        ('prospecto', 'Prospecto', 100),
        ('captacion', '1 · Captación', 101),
        ('primera_compra', '2 · Primera compra', 102),
        ('pedido_formal', '3 · Pedido formal', 103),
        ('recurrente', '4 · Recurrente', 104),
        ('inactivo', 'Inactivo', 105),
        ('descartado', 'Descartado', 106),
    ]

    @api.model
    def _inst_team(self, create=True):
        Team = self.env['crm.team'].sudo()
        team = Team.search([('name', '=', 'Institucional')], limit=1)
        if not team and create:
            team = Team.create({'name': 'Institucional'})
        return team

    @api.model
    def _inst_stages(self, team):
        Stage = self.env['crm.stage'].sudo()
        existing = {s.name: s for s in Stage.search([('team_id', '=', team.id)])}
        out = {}
        for key, name, sequence in self.INST_STAGE_NAMES:
            stage = existing.get(name)
            if not stage:
                stage = Stage.create({
                    'name': name, 'team_id': team.id, 'sequence': sequence,
                    'fold': key == 'descartado',
                })
            elif stage.sequence != sequence:
                stage.write({'sequence': sequence})
            out[key] = stage
        return out

    @api.model
    def action_pipeline(self):
        """Abre el flujo institucional del CRM con sus columnas propias."""
        team = self._inst_team()
        self._inst_stages(team)
        ref = lambda xmlid: self.env.ref('cristal_institucional.%s' % xmlid).id
        return {
            'type': 'ir.actions.act_window',
            'name': 'Institucional',
            'res_model': 'crm.lead',
            'view_mode': 'kanban,list,form,activity',
            'views': [(ref('view_lead_inst_kanban'), 'kanban'), (ref('view_lead_inst_list'), 'list'),
                      (False, 'form'), (False, 'activity')],
            'search_view_id': [ref('view_lead_inst_search'), 'search'],
            'domain': [('inst_account', '=', True)],
            'context': {'default_team_id': team.id, 'default_type': 'opportunity',
                        'search_default_inst_open': 1},
        }

    @api.model
    def action_refresh_now(self):
        """Botón "Actualizar ahora": suma empresas nuevas y recalcula todo."""
        self._scope()
        self.recompute()
        return self.action_pipeline()

    @api.model
    def _sync_crm(self, partners, params):
        """Una tarjeta por empresa en el CRM, en la columna de su etapa, con el
        próximo paso como actividad. El prospecto vive como lead; desde captación es oportunidad."""
        if not partners:
            return
        team = self._inst_team()
        stages = self._inst_stages(team)
        act_type = self.env.ref('cristal_institucional.mail_activity_type_inst', raise_if_not_found=False)
        Lead = self.env['crm.lead'].sudo().with_context(
            active_test=False, tracking_disable=True, mail_create_nosubscribe=True,
            mail_create_nolog=True, mail_notrack=True, mail_auto_subscribe_no_notify=True, inst_sync=True)
        Users = self.env['res.users'].sudo()
        default_user = Users.browse(params.get('default_user_id') or 0).exists()

        accounts = {}
        for lead in Lead.search([('inst_account', '=', True), ('inst_partner_id', 'in', partners.ids)],
                                order='id'):
            if lead.inst_partner_id.id in accounts:
                lead.write({'inst_account': False})      # nunca dos tarjetas para la misma empresa
            else:
                accounts[lead.inst_partner_id.id] = lead
        missing = partners.filtered(lambda p: p.id not in accounts)
        if missing:
            candidates = Lead.search([('inst_partner_id', 'in', missing.ids), ('team_id', '=', team.id)])
            best = {}
            for lead in candidates:
                rank = (lead.active, lead.type == 'opportunity', lead.id)
                pid = lead.inst_partner_id.id
                if pid not in best or rank > best[pid][0]:
                    best[pid] = (rank, lead)
            for partner in missing:
                if partner.id in best:
                    lead = best[partner.id][1]
                    lead.write({'inst_account': True})
                else:
                    owner = partner.user_id if (partner.user_id and not partner.user_id.share
                                                and partner.user_id.active) else default_user
                    lead = Lead.create({
                        'name': partner.name,
                        'partner_id': partner.id,
                        'team_id': team.id,
                        'user_id': owner.id or False,
                        'type': 'lead' if partner.inst_stage == 'prospecto' else 'opportunity',
                        'stage_id': stages.get(partner.inst_stage or 'prospecto').id,
                        'inst_account': True,
                    })
                accounts[partner.id] = lead

        Activity = self.env['mail.activity'].sudo().with_context(mail_activity_quick_update=True)
        lead_model_id = self.env['ir.model']._get_id('crm.lead')
        current = {}
        if act_type:
            for activity in Activity.search([
                    ('res_model', '=', 'crm.lead'), ('res_id', 'in', [l.id for l in accounts.values()]),
                    ('activity_type_id', '=', act_type.id)]):
                if activity.res_id in current:
                    activity.unlink()
                else:
                    current[activity.res_id] = activity

        for partner in partners:
            lead = accounts.get(partner.id)
            if not lead:
                continue
            stage = stages.get(partner.inst_stage or 'prospecto')
            vals = {}
            if lead.stage_id != stage:
                vals['stage_id'] = stage.id
            wanted_type = 'lead' if partner.inst_stage == 'prospecto' else 'opportunity'
            if lead.type != wanted_type:
                vals['type'] = wanted_type
            if not lead.active:
                vals['active'] = True
            if lead.team_id != team:
                vals['team_id'] = team.id
            owner = partner.inst_user_id or default_user
            if owner and lead.user_id != owner:
                vals['user_id'] = owner.id      # toda cuenta tiene un responsable
            if vals:
                lead.write(vals)
            if not act_type:
                continue
            activity = current.get(lead.id)
            if partner.inst_next_step and partner.inst_next_step_date:
                owner = lead.user_id or default_user
                # En la lista de actividades de Odoo solo queda "para hoy" lo que entró en Mi día;
                # lo demás que venció pasa a mañana, así no se acumula en rojo.
                when = partner.inst_next_step_date
                today = fields.Date.context_today(self)
                if when <= today:
                    when = today if partner.inst_today else self._next_workday(today)
                avals = {
                    'summary': partner.inst_next_step[:240],
                    'date_deadline': when,
                    'user_id': owner.id or self.env.uid,
                }
                if activity:
                    diff = {k: v for k, v in avals.items()
                            if (activity[k].id if k == 'user_id' else activity[k]) != v}
                    if diff:
                        activity.write(diff)
                else:
                    avals.update({
                        'res_model_id': lead_model_id, 'res_id': lead.id,
                        'activity_type_id': act_type.id, 'automated': True,
                    })
                    Activity.create(avals)
            elif activity:
                activity.unlink()

    # ---------------------------------------------------------- informe semanal
    @api.model
    def _weekly_data(self):
        Partner = self.env['res.partner'].sudo()
        today = fields.Date.context_today(self)
        week_ago = today - timedelta(days=7)
        partners = Partner.search([('inst_is', '=', True)])
        labels = dict(Partner._fields['inst_stage'].selection)
        rows = []
        for key, label in Partner._fields['inst_stage'].selection:
            group = partners.filtered(lambda p, k=key: p.inst_stage == k)
            rows.append({
                'key': key, 'label': label, 'count': len(group),
                'at_risk': len(group.filtered(lambda p: p.inst_alert == 'riesgo')),
                'dormant': len(group.filtered(lambda p: p.inst_alert == 'dormido')),
                'overdue': len(group.filtered(lambda p: p.inst_alert == 'vence')),
                'margin_month': sum(group.mapped('inst_margin_month')),
            })
        logs = self.env['cristal.inst.stage.log'].sudo().search([
            ('date', '>', week_ago), ('stage_from', '!=', False)])
        moves = {}
        for log in logs:
            pair = '%s → %s' % (labels.get(log.stage_from, '?'), labels.get(log.stage_to, '?'))
            moves[pair] = moves.get(pair, 0) + 1
        calls = self.env['cristal.inst.call'].sudo().search([('date', '>', fields.Datetime.now() - timedelta(days=7))])
        top = Partner.search(
            [('inst_is', '=', True), ('inst_stage', '!=', 'descartado'), ('inst_next_step', '!=', False)],
            order='inst_priority desc', limit=8)
        return {
            'today': today, 'rows': rows, 'moves': moves,
            'calls': len(calls), 'talks': len(calls.filtered('is_contact')),
            'kits': len(partners.filtered(lambda p: p.inst_kit_date and p.inst_kit_date > week_ago)),
            'first_orders': len(partners.filtered(lambda p: p.inst_first_order and p.inst_first_order > week_ago)),
            'top': top,
        }

    @api.model
    def _weekly_html(self, data):
        from markupsafe import Markup, escape
        money = lambda v: '$ {:,.0f}'.format(v or 0).replace(',', '.')
        html = Markup('<p><strong>Institucional: resumen de la semana</strong></p>')
        html += Markup('<p>Llamadas registradas: %s (%s con conversación). Kits entregados: %s. '
                       'Primeras compras: %s.</p>') % (data['calls'], data['talks'], data['kits'], data['first_orders'])
        html += Markup('<p><strong>Embudo hoy</strong></p><ul>')
        for row in data['rows']:
            extra = []
            if row['at_risk']:
                extra.append('%s en riesgo' % row['at_risk'])
            if row['dormant']:
                extra.append('%s dormidas' % row['dormant'])
            if row['overdue']:
                extra.append('%s con fecha límite vencida' % row['overdue'])
            if row['margin_month']:
                extra.append('margen por mes %s' % money(row['margin_month']))
            html += Markup('<li>%s: %s%s</li>') % (
                row['label'], row['count'], (' (%s)' % ', '.join(extra)) if extra else '')
        html += Markup('</ul>')
        if data['moves']:
            html += Markup('<p><strong>Cambios de etapa en la semana</strong></p><ul>')
            for pair, qty in sorted(data['moves'].items(), key=lambda kv: -kv[1]):
                html += Markup('<li>%s: %s</li>') % (pair, qty)
            html += Markup('</ul>')
        else:
            html += Markup('<p>Ninguna empresa cambió de etapa esta semana.</p>')
        if data['top']:
            html += Markup('<p><strong>Lo más importante para esta semana</strong></p><ol>')
            for partner in data['top']:
                html += Markup('<li>%s: %s</li>') % (escape(partner.name), escape(partner.inst_next_step))
            html += Markup('</ol>')
        return html

    @api.model
    def _cron_weekly_report(self):
        self.recompute()
        data = self._weekly_data()
        Snapshot = self.env['cristal.inst.snapshot'].sudo()
        Snapshot.search([('date', '=', data['today'])]).unlink()
        Snapshot.create([{
            'date': data['today'], 'stage': row['key'], 'count': row['count'],
            'at_risk': row['at_risk'], 'dormant': row['dormant'], 'overdue': row['overdue'],
            'margin_month': row['margin_month'],
        } for row in data['rows']])
        icp = self.env['ir.config_parameter'].sudo()
        raw = icp.get_param('cristal_institucional.report_user_ids', '18')
        user_ids = [int(x) for x in raw.replace(' ', '').split(',') if x.isdigit()]
        users = self.env['res.users'].sudo().browse(user_ids).exists()
        if users:
            self.env['mail.thread'].sudo().message_notify(
                partner_ids=users.mapped('partner_id').ids,
                subject='Institucional: resumen de la semana',
                body=self._weekly_html(data),
            )
        return True
