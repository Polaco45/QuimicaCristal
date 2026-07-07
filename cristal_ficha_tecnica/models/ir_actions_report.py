import base64
import logging

import requests

from odoo import models
from odoo.tools.pdf import merge_pdf

_logger = logging.getLogger(__name__)

# report_name del reporte "Cotización + Ficha Técnica" definido en
# report/sale_report_ficha.xml. Solo ese reporte dispara el adjuntado de fichas.
FICHA_REPORT_NAME = "cristal_ficha_tecnica.report_saleorder_ficha"

# Tiempo máximo para descargar cada ficha técnica alojada por URL.
_FETCH_TIMEOUT = 25


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        """Renderiza la cotización estándar y le adjunta, debajo, las fichas
        técnicas (PDF) de los productos incluidos en la orden.

        Solo actúa sobre el reporte ``FICHA_REPORT_NAME``; el resto de los
        reportes PDF se comportan igual que siempre. Ante cualquier problema
        al obtener o mergear las fichas, devuelve la cotización sola para no
        romper la impresión.
        """
        pdf_content, report_type = super()._render_qweb_pdf(
            report_ref, res_ids=res_ids, data=data
        )

        report = self._get_report(report_ref)
        if not report or report.report_name != FICHA_REPORT_NAME or not res_ids:
            return pdf_content, report_type

        try:
            ficha_pdfs = self._collect_seiq_datasheets(res_ids)
        except Exception:  # noqa: BLE001 - nunca romper la impresión
            _logger.exception(
                "cristal_ficha_tecnica: fallo al recolectar fichas técnicas; "
                "se imprime la cotización sin fichas."
            )
            return pdf_content, report_type

        if not ficha_pdfs:
            return pdf_content, report_type

        try:
            merged = merge_pdf([pdf_content] + ficha_pdfs)
        except Exception:  # noqa: BLE001
            _logger.exception(
                "cristal_ficha_tecnica: fallo al mergear las fichas técnicas; "
                "se imprime la cotización sin fichas."
            )
            return pdf_content, report_type

        return merged, report_type

    def _collect_seiq_datasheets(self, res_ids):
        """Devuelve, en orden de aparición en las líneas, el contenido binario
        (bytes) de la ficha técnica de cada producto de las órdenes que tenga
        una cargada. Un producto repetido se incluye una sola vez.
        """
        orders = self.env["sale.order"].browse(res_ids)
        Attachment = self.env["ir.attachment"].sudo()

        ficha_pdfs = []
        seen_templates = set()
        for order in orders:
            for line in order.order_line:
                product = line.product_id
                if not product:
                    continue
                template = product.product_tmpl_id
                if template.id in seen_templates:
                    continue
                seen_templates.add(template.id)

                attachment = Attachment.search(
                    [
                        ("res_model", "=", "product.template"),
                        ("res_id", "=", template.id),
                        ("mimetype", "=", "application/pdf"),
                        ("name", "ilike", "ficha"),
                    ],
                    order="id desc",
                    limit=1,
                )
                if not attachment:
                    continue

                content = self._fetch_attachment_pdf(attachment)
                if content:
                    ficha_pdfs.append(content)

        return ficha_pdfs

    def _fetch_attachment_pdf(self, attachment):
        """Obtiene los bytes del PDF de un adjunto.

        - Adjunto tipo URL (fichas SEIQ alojadas en seiqgroupsa.com.ar): se
          descarga siempre al vuelo para reflejar la versión vigente de la
          ficha (SEIQ publica versiones nuevas del PDF).
        - Adjunto binario: se usa el contenido almacenado en Odoo.

        Devuelve ``None`` (y loguea) si no se pudo obtener.
        """
        if attachment.type == "url":
            return self._fetch_pdf_from_url(attachment)

        if attachment.datas:
            try:
                return base64.b64decode(attachment.datas)
            except Exception:  # noqa: BLE001
                _logger.warning(
                    "cristal_ficha_tecnica: no se pudo decodificar la ficha "
                    "binaria '%s' (id %s).",
                    attachment.name,
                    attachment.id,
                )
        return None

    def _fetch_pdf_from_url(self, attachment):
        url = attachment.url
        if not url:
            return None
        try:
            response = requests.get(
                url,
                timeout=_FETCH_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 (OdooReport)"},
            )
            response.raise_for_status()
        except Exception:  # noqa: BLE001
            _logger.warning(
                "cristal_ficha_tecnica: no se pudo descargar la ficha '%s' "
                "desde %s.",
                attachment.name,
                url,
            )
            return None

        content = response.content
        # Validación mínima: que el contenido descargado sea realmente un PDF
        # (evita mergear una página de error HTML).
        if not content or not content[:5].startswith(b"%PDF"):
            _logger.warning(
                "cristal_ficha_tecnica: el contenido de '%s' (%s) no es un PDF "
                "válido; se omite.",
                attachment.name,
                url,
            )
            return None

        return content
