from datetime import date

from . import models


def post_init_hook(env):
    """Carga inicial: marca como institucionales las empresas que ya se venían
    trabajando (equipo Institucional del CRM y oportunidades con etiqueta E1-E4)
    y calcula su etapa con el historial real de pedidos."""
    Lead = env['crm.lead'].sudo().with_context(active_test=False)
    team = env['crm.team'].sudo().search([('name', '=', 'Institucional')], limit=1)
    tags = env['crm.tag'].sudo().search([('name', '=like', 'E_ · %')])
    conds = []
    if team:
        conds.append(('team_id', '=', team.id))
    if tags:
        conds.append(('tag_ids', 'in', tags.ids))
    if not conds:
        return
    domain = [('partner_id', '!=', False)] + ['|'] * (len(conds) - 1) + conds
    leads = Lead.search(domain)
    today = date.today()
    by_partner = {}
    for lead in leads:
        by_partner.setdefault(lead.partner_id.commercial_partner_id, []).append(lead)
    has_prod = 'x_studio_que_productos_usan' in Lead._fields
    for partner, pleads in by_partner.items():
        vals = {'inst_is': True}
        stage_names = [(l.stage_id.name or '').strip().lower() for l in pleads]
        if any(n and not n.startswith(('nuev', 'new')) for n in stage_names):
            vals['inst_contactado'] = today
        lost = [l for l in pleads if (not l.active and not l.probability)
                or (l.stage_id.name or '').strip().lower().startswith('perdid')]
        if lost and len(lost) == len(pleads):
            vals['inst_discarded'] = True
            reason = lost[0].lost_reason_id.name if 'lost_reason_id' in Lead._fields else False
            vals['inst_discard_reason'] = reason or 'Perdido en el CRM'
        if has_prod and not partner.inst_productos:
            txt = next((l.x_studio_que_productos_usan for l in pleads if l.x_studio_que_productos_usan), False)
            if txt:
                vals['inst_productos'] = txt
        partner.with_context(tracking_disable=True, inst_engine=True).write(vals)
    env['cristal.inst.engine'].recompute()
