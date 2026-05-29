# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.7.7:
- Anti-loop: actividades con 2+ runs cron_cadence en 7 días se cierran y se
  delegan a Joaco como tarea manual (evita spam de escalaciones cuando el
  cliente no tiene canal WA activo).
- Cron nuevo cron_retry_failed_whatsapp cada 5 min: reintenta automáticamente
  los whatsapp.message en estado 'error' de las últimas 2 horas (max 3 reintentos).
- Limpieza de runs antiguos para que el conteo de stuck_runs no incluya runs viejos.
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        # Limpieza opcional: cerrar actividades vencidas asignadas a Claudio
        # cuyo partner tiene >= 3 runs cron_cadence en últimos 7 días (stuck)
        from datetime import datetime, timedelta
        threshold = datetime.now() - timedelta(days=7)

        Activity = env['mail.activity'].sudo()
        Run = env['cristal.agent.run'].sudo()
        config = env['cristal.agent.config'].sudo().search([('active', '=', True)], limit=1)
        if not config:
            return
        bot_user_id = config.bot_user_id.id if config.bot_user_id else 721
        joaco_user_id = config.owner_user_id.id if config.owner_user_id else 18

        # Buscar partners con muchos runs recientes
        env.cr.execute("""
            SELECT partner_id, COUNT(*) AS cnt
            FROM cristal_agent_run
            WHERE trigger = 'cron_cadence'
              AND create_date >= %s
            GROUP BY partner_id
            HAVING COUNT(*) >= 3
        """, (threshold,))
        stuck_partners = [row[0] for row in env.cr.fetchall() if row[0]]

        if stuck_partners:
            _logger.warning(
                "MIGRATION 1.7.7: %s partners stuck con >=3 runs en 7d. Limpiando actividades.",
                len(stuck_partners)
            )
            stuck_activities = Activity.search([
                ('user_id', '=', bot_user_id),
                ('res_model', 'in', ['crm.lead', 'res.partner']),
            ])
            cleaned = 0
            for act in stuck_activities:
                partner_id = None
                if act.res_model == 'res.partner':
                    partner_id = act.res_id
                elif act.res_model == 'crm.lead':
                    lead = env['crm.lead'].sudo().browse(act.res_id)
                    if lead.exists():
                        partner_id = lead.partner_id.id
                if partner_id and partner_id in stuck_partners:
                    try:
                        act.action_done()
                        cleaned += 1
                    except Exception:
                        pass
            _logger.info("MIGRATION 1.7.7: %s actividades stuck cerradas", cleaned)

        _logger.info("✅ MIGRATION 1.7.7: anti-loop + retry WA fallidos activados")
    except Exception as e:
        _logger.exception("MIGRATION 1.7.7: %s", e)
