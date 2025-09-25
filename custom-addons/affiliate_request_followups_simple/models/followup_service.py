# -*- coding: utf-8 -*-
from odoo import api, fields, models
from dateutil.relativedelta import relativedelta
import logging
import re

_logger = logging.getLogger(__name__)
EMAIL_RE = re.compile(r'<?([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})>?', re.I)


class AffiliateRequestFollowupService(models.AbstractModel):
    _name = "affiliate.request.followup.service"
    _description = "Affiliate Request Followup Service"

    # --------- utilidades ----------
    def _resolve_email(self, r):
        """Devuelve email: r.email || partner.email || email embebido en name."""
        email = getattr(r, "email", False) or (r.partner_id.email if getattr(r, "partner_id", False) else False) or ""
        m = EMAIL_RE.search(email or "")
        if m:
            return m.group(1).lower()
        m2 = EMAIL_RE.search((r.name or ""))
        return (m2.group(1).lower() if m2 else False)

    def _dedup_by_email(self, recs):
        """Único por email. Prefiere con signup_token; si empate, el más nuevo."""
        best = {}
        for r in recs:
            email = self._resolve_email(r)
            if not email:
                continue
            prev = best.get(email)
            if not prev:
                best[email] = r
                continue
            cur_has = bool(getattr(r, "signup_token", False))
            prev_has = bool(getattr(prev, "signup_token", False))
            if cur_has and not prev_has:
                best[email] = r
            elif cur_has == prev_has and r.create_date > prev.create_date:
                best[email] = r
        return list(best.values())

    # --------- cron principal ----------
    @api.model
    def cron_send_followups(self):
        """Envía recordatorios 12/24/48h. Idempotente por (request, etapa)."""
        ICP = self.env["ir.config_parameter"].sudo()

        # 1) Obtener plantilla por ID (configurada manualmente)
        template_id = int(ICP.get_param("affiliate.followup_template_id", "0") or 0)
        if not template_id:
            _logger.warning("affiliate_followups: sin plantilla configurada (affiliate.followup_template_id).")
            return True

        tmpl = self.env["mail.template"].sudo().browse(template_id)
        if not tmpl or tmpl.model != "affiliate.request":
            _logger.warning("affiliate_followups: plantilla inválida o modelo distinto a affiliate.request.")
            return True

        # 2) Estados terminales a excluir (configurable, con fallback seguro)
        #    Para tu flujo: draft/register/cancel/aproove (enviar sólo draft por defecto)
        raw = ICP.get_param("affiliate.followup_terminal_states", "")
        if raw:
            terminal_states = [s.strip() for s in raw.split(",") if s.strip()]
        else:
            # Fallbacks comunes; AJUSTA si lo necesitás
            terminal_states = ["aproove", "cancel", "register", "approved", "accepted", "rejected", "cancelled", "done", "active", "valid"]

        now = fields.Datetime.now()
        Request = self.env["affiliate.request"].sudo()

        # 3) Candidatos: >=12h, no terminales
        domain = [("create_date", "<=", now - relativedelta(hours=12))]
        if terminal_states:
            domain.append(("state", "not in", terminal_states))

        recs = Request.search(domain, order="create_date desc", limit=5000)
        if not recs:
            _logger.info("affiliate_followups: no hay candidatos.")
            return True

        candidates = self._dedup_by_email(recs)
        if not candidates:
            _logger.info("affiliate_followups: no hay candidatos con email válido.")
            return True

        def _stage_for(rec):
            age_h = (now - rec.create_date).total_seconds() / 3600.0
            if age_h >= 48:
                return "48"
            if age_h >= 24:
                return "24"
            return "12"

        # Mapeo de etapa -> campo fecha a marcar en affiliate.request
        stage_field_map = {
            "12": "followup_12h_at",
            "24": "followup_24h_at",
            "48": "followup_48h_at",
        }

        enviados = 0

        for r in candidates:
            stage = _stage_for(r)
            with self.env.cr.savepoint():
                # Idempotencia a nivel SQL: si ya existe (request_id, stage) no repite
                self.env.cr.execute("""
                    INSERT INTO affiliate_request_followup_log
                        (request_id, stage, create_date, create_uid, write_date, write_uid)
                    VALUES (%s, %s, NOW(), %s, NOW(), %s)
                    ON CONFLICT (request_id, stage) DO NOTHING
                """, (r.id, stage, self.env.uid, self.env.uid))

                if self.env.cr.rowcount == 0:
                    # Ya se había enviado esta etapa
                    continue

                try:
                    tmpl.send_mail(r.id, force_send=True, raise_exception=False)
                    enviados += 1

                    # ---- NUEVO: marcar timestamp de la etapa en el registro ----
                    field_name = stage_field_map.get(stage)
                    if field_name and field_name in Request._fields:
                        r.sudo().write({field_name: now})
                    else:
                        _logger.warning("affiliate_followups: campo de etapa no encontrado para stage=%s", stage)
                    # ------------------------------------------------------------

                except Exception:
                    _logger.exception("affiliate_followups: error enviando mail para request %s", r.id)
                    # Si quisieras reintentar, podrías borrar el log insertado aquí.

        _logger.info("affiliate_followups: enviados=%s", enviados)
        return True
