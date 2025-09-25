# -*- coding: utf-8 -*-
from odoo import api, fields, models
from dateutil.relativedelta import relativedelta
import logging
import re

_logger = logging.getLogger(__name__)
EMAIL_RE = re.compile(r'<?([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})>?', re.I)

# Clave fija para el lock asesor (32 bits)
_ADVISORY_LOCK_KEY = 2147481001  # constante estable


class AffiliateRequestFollowupService(models.AbstractModel):
    _name = "affiliate.request.followup.service"
    _description = "Affiliate Request Followup Service"

    # ---------------------------------------------------------------------
    # Hardening en instalación/carga del módulo (idempotente)
    # ---------------------------------------------------------------------
    @api.model
    def init(self):
        """Asegura estructuras necesarias sin romper instalaciones previas."""
        cr = self.env.cr
        # Tabla de log (por si la instala alguien sin los datos demo)
        cr.execute("""
            CREATE TABLE IF NOT EXISTS affiliate_request_followup_log (
                id           SERIAL PRIMARY KEY,
                request_id   INTEGER NOT NULL REFERENCES affiliate_request(id) ON DELETE CASCADE,
                stage        VARCHAR(3) NOT NULL,
                create_date  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
                create_uid   INTEGER,
                write_date   TIMESTAMP WITHOUT TIME ZONE,
                write_uid    INTEGER
            )
        """)
        # Único por (request, stage) para idempotencia
        cr.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname = 'affiliate_request_followup_log_req_stage_uniq'
                ) THEN
                    CREATE UNIQUE INDEX affiliate_request_followup_log_req_stage_uniq
                    ON affiliate_request_followup_log (request_id, stage);
                END IF;
            END$$
        """)

    # ---------------------------------------------------------------------
    # Utilidades
    # ---------------------------------------------------------------------
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

    # ---------------------------------------------------------------------
    # Cron principal
    # ---------------------------------------------------------------------
    @api.model
    def cron_send_followups(self):
        """
        Envía recordatorios 12/24/48h. Idempotente, no reentrante y con
        transacciones cortas para evitar bloqueos.
        """
        ICP = self.env["ir.config_parameter"].sudo()

        # Mutex a nivel DB para evitar dos corridas en paralelo
        self.env.cr.execute("SELECT pg_try_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
        locked = self.env.cr.fetchone()[0]
        if not locked:
            _logger.info("affiliate_followups: otra corrida está en progreso; se omite esta ejecución.")
            return True

        # Dentro de la transacción principal, fijamos timeouts acotados
        # (no afectan a otras sesiones; SET LOCAL dura hasta el commit).
        try:
            self.env.cr.execute("SET LOCAL lock_timeout TO '15s'")
            self.env.cr.execute("SET LOCAL statement_timeout TO '90s'")
            self.env.cr.execute("SET LOCAL idle_in_transaction_session_timeout TO '180s'")
        except Exception:
            _logger.debug("affiliate_followups: no se pudieron fijar timeouts locales", exc_info=True)

        try:
            # Plantilla configurada por parámetro
            template_id = int(ICP.get_param("affiliate.followup_template_id", "0") or 0)
            if not template_id:
                _logger.warning("affiliate_followups: sin plantilla configurada (affiliate.followup_template_id).")
                return True

            tmpl = self.env["mail.template"].sudo().browse(template_id)
            if not tmpl or tmpl.model != "affiliate.request":
                _logger.warning("affiliate_followups: plantilla inválida o modelo distinto a affiliate.request.")
                return True

            # Estados terminales a excluir
            raw = ICP.get_param("affiliate.followup_terminal_states", "")
            if raw:
                terminal_states = [s.strip() for s in raw.split(",") if s.strip()]
            else:
                terminal_states = [
                    "aproove", "cancel", "register",
                    "approved", "accepted", "rejected",
                    "cancelled", "done", "active", "valid"
                ]

            now = fields.Datetime.now()
            # Límite por batch + commits frecuentes
            batch_limit = int(ICP.get_param("affiliate.followup_max_batch", "1000") or 1000)
            commit_every = int(ICP.get_param("affiliate.followup_commit_every", "50") or 50)

            # ---------------------------
            # Candidatos por SQL directo
            # ---------------------------
            params = [fields.Datetime.to_string(now - relativedelta(hours=12))]
            where_sql = "create_date <= %s"
            if terminal_states:
                where_sql += " AND COALESCE(state,'') NOT IN %s"
                params.append(tuple(terminal_states))

            self.env.cr.execute(f"""
                SELECT id
                FROM affiliate_request
                WHERE {where_sql}
                ORDER BY create_date DESC
                LIMIT %s
            """, tuple(params + [batch_limit]))
            ids = [r[0] for r in self.env.cr.fetchall()]

            if not ids:
                _logger.info("affiliate_followups: no hay candidatos.")
                return True

            Request = self.env["affiliate.request"].sudo()
            recs = Request.browse(ids)

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

            enviados = 0

            for idx, r in enumerate(candidates, start=1):
                stage = _stage_for(r)

                # Savepoint + timeouts locales cortos sólo para esta sección
                with self.env.cr.savepoint():
                    try:
                        self.env.cr.execute("SET LOCAL lock_timeout TO '5s'")
                        self.env.cr.execute("SET LOCAL statement_timeout TO '30s'")
                    except Exception:
                        pass

                    # Log idempotente; si ya existe, no reenvía
                    self.env.cr.execute("""
                        INSERT INTO affiliate_request_followup_log
                            (request_id, stage, create_date, create_uid, write_date, write_uid)
                        VALUES (%s, %s, NOW(), %s, NOW(), %s)
                        ON CONFLICT (request_id, stage) DO NOTHING
                    """, (r.id, stage, self.env.uid, self.env.uid))

                    if self.env.cr.rowcount == 0:
                        # Ya se había enviado esta etapa
                        continue

                    # Envío
                    try:
                        tmpl.send_mail(r.id, force_send=True, raise_exception=False)
                        enviados += 1
                    except Exception:
                        # Dejamos trazas pero no cortamos el lote
                        _logger.exception("affiliate_followups: error enviando mail para request %s", r.id)

                # Transacciones cortas para soltar locks/buffers periódicamente
                if idx % commit_every == 0:
                    try:
                        self.env.cr.commit()
                    except Exception:
                        _logger.exception("affiliate_followups: error al commit intermedio; se continúa")

            # Commit final del lote
            try:
                self.env.cr.commit()
            finally:
                _logger.info("affiliate_followups: enviados=%s", enviados)

            return True

        finally:
            # Soltar el lock asesor pase lo que pase
            try:
                self.env.cr.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
            except Exception:
                _logger.exception("affiliate_followups: no se pudo liberar el advisory lock")
