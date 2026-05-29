# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.7.6:
- Fix read_partner.team_id (no existe en res.partner, leer del lead asociado)
- Fix dispatch_agent_for_activity: pasar channel_id resuelto al bot
- Anti-duplicación intra-corrida en cron_pending_activities
- Silenciar email automático de escalate_to_joaco (solo canal interno)
- Filtro geográfico: solo Río Cuarto/Las Higueras + etiqueta "Fuera de zona"
- Prompt v3.1 compactado: Fase 4/5 más concisas, ~3k caracteres menos
- Cache control en tools (ahorro adicional ~3k tokens por llamada)
"""
import os, logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        migration_path = os.path.dirname(os.path.realpath(__file__))
        module_path = os.path.dirname(os.path.dirname(migration_path))
        prompt_path = os.path.join(module_path, 'data', 'prompts', 'claudio_v3_1.md')
        if not os.path.exists(prompt_path):
            return
        with open(prompt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        config = env['cristal.agent.config'].sudo().search(
            [('active', '=', True)], limit=1
        )
        if config:
            config.write({'system_prompt': content, 'prompt_version': 'claudio_v3_1'})
            _logger.info(
                "✅ MIGRATION 1.7.6: prompt compactado (%s chars) cargado",
                len(content)
            )
        # Verificar que la etiqueta "Fuera de zona" exista
        Tag = env['res.partner.category'].sudo()
        if not Tag.search([('name', '=', 'Fuera de zona')], limit=1):
            try:
                Tag.create({'name': 'Fuera de zona', 'color': 2})
                _logger.info("✅ MIGRATION 1.7.6: etiqueta 'Fuera de zona' creada")
            except Exception as e:
                _logger.warning("No se pudo crear etiqueta Fuera de zona: %s", e)
    except Exception as e:
        _logger.exception("MIGRATION 1.7.6: %s", e)
