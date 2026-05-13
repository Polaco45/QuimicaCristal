# -*- coding: utf-8 -*-
"""
Tool: generate_pricelist_pdf

PDF profesional de Lista Mayorista con:
- Logo de la empresa arriba a la izquierda
- Box de niveles (Bronce / Plata / Oro) con sus rangos y % off
- Tabla agrupada por template (productos con variantes muestran header + variantes)
- Precio Bronce / Plata / Oro calculados con descuentos
- Precio por litro extraído del nombre del producto
- Footer con políticas

Itera sobre product.template con is_mayorista_catalog=True (ordenado por
mayorista_priority desc) y muestra todas sus variantes vendibles.
"""
import base64
import logging
import re
from io import BytesIO
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

LEVEL_DISCOUNTS = {
    'bronce': 0.0,
    'plata': 0.05,
    'oro': 0.10,
}

LEVEL_RANGES = {
    'bronce': '$50.000 – $199.999',
    'plata': '$200.000 – $499.999',
    'oro': '$500.000+',
}


def _extract_liters(name):
    """
    Extrae el volumen en litros del nombre. Patrones soportados:
    "200L", "200 L", "200Lt", "200lts", "200 litros", "5.5L", "0.5L".

    Devuelve float o None.
    """
    if not name:
        return None
    # Busca número (con decimal opcional) seguido de unidad
    match = re.search(
        r'(\d+(?:[.,]\d+)?)\s*(?:L|Lt|lts?|litros?)\b',
        name,
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return float(match.group(1).replace(',', '.'))
    except ValueError:
        return None


def _get_pricelist_price(pricelist, product, qty=1.0):
    """Obtiene precio usando la API actual con fallbacks."""
    try:
        return pricelist._get_product_price(product, qty)
    except Exception:
        pass
    try:
        # Odoo 17/18 legacy
        result = pricelist.price_get(product.id, qty)
        return result.get(pricelist.id, product.lst_price)
    except Exception:
        pass
    return product.lst_price


@ToolRegistry.register
class GeneratePricelistPdf(AgentTool):
    name = "generate_pricelist_pdf"
    description = (
        "Genera PDF profesional de Lista de Precios Mayorista. "
        "Incluye logo de la empresa, box de niveles (Bronce/Plata/Oro con rangos), "
        "precios por nivel con descuento aplicado, precio por litro calculado, "
        "y agrupación de variantes bajo cada producto. "
        "Usa productos con is_mayorista_catalog=True. "
        "Devuelve attachment_id para mandar por send_whatsapp(attachment_ids=[X])."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pricelist_name": {
                "type": "string",
                "description": "Nombre de la pricelist. Default: 'Lista Mayorista'.",
            },
            "pricelist_id": {
                "type": "integer",
                "description": "ID de pricelist (alternativa a pricelist_name).",
            },
        },
    }

    def _execute(self, env, run=None, pricelist_name='Lista Mayorista',
                 pricelist_id=None, **kwargs):
        Pricelist = env['product.pricelist'].sudo()
        if pricelist_id:
            pricelist = Pricelist.browse(int(pricelist_id))
        else:
            pricelist = Pricelist.search([('name', '=', pricelist_name)], limit=1)

        if not pricelist or not pricelist.exists():
            return {
                "error": f"Pricelist no encontrada: '{pricelist_name or pricelist_id}'. "
                         f"Verificá en Ventas → Listas de Precios.",
            }

        ProductTemplate = env['product.template'].sudo()
        templates = ProductTemplate.search([
            ('is_mayorista_catalog', '=', True),
            ('sale_ok', '=', True),
        ])
        templates = templates.sorted(
            key=lambda t: (-(t.mayorista_priority or 0), t.name)
        )

        if not templates:
            return {
                "error": "El Catálogo Mayorista está vacío. Joaco debe marcar productos "
                         "con is_mayorista_catalog=True desde el menú del agente. "
                         "ESCALÁ a Joaco.",
                "products_found": 0,
            }

        _logger.info(
            "📋 generate_pricelist_pdf: pricelist='%s', templates=%s",
            pricelist.name, len(templates)
        )

        try:
            pdf_content = self._build_pdf(env, pricelist, templates)
        except ImportError as e:
            return {"error": f"reportlab no instalado: {e}"}
        except Exception as e:
            _logger.exception("Error generando PDF: %s", e)
            return {"error": f"Error PDF: {e}"}

        try:
            attachment = env['ir.attachment'].sudo().create({
                'name': f"Lista_{pricelist.name.replace(' ', '_')}_Mayorista.pdf",
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': 'product.pricelist',
                'res_id': pricelist.id,
                'mimetype': 'application/pdf',
            })
        except Exception as e:
            return {"error": f"No se pudo guardar attachment: {e}"}

        return {
            "ok": True,
            "attachment_id": attachment.id,
            "filename": attachment.name,
            "pricelist": pricelist.name,
            "templates_count": len(templates),
            "summary": (
                f"PDF Lista '{pricelist.name}' generado con {len(templates)} productos "
                f"del Catálogo Mayorista. attachment_id={attachment.id}."
            ),
        }

    def _build_pdf(self, env, pricelist, templates):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Table, TableStyle,
            Spacer, Image, KeepTogether,
        )
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from datetime import datetime

        ORANGE = colors.HexColor('#FF9C00')
        ORANGE_DARK = colors.HexColor('#CC7D00')
        DARK = colors.HexColor('#2C2C2C')
        GREY = colors.HexColor('#666666')
        LIGHT_GREY = colors.HexColor('#F8F8F8')
        BRONZE = colors.HexColor('#CD7F32')
        SILVER = colors.HexColor('#9CA3AF')
        GOLD = colors.HexColor('#D4AF37')

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            topMargin=12 * mm, bottomMargin=15 * mm,
            leftMargin=10 * mm, rightMargin=10 * mm,
        )

        styles = getSampleStyleSheet()
        elements = []

        title_style = ParagraphStyle(
            'Title', parent=styles['Heading1'],
            fontSize=20, textColor=ORANGE, alignment=TA_LEFT,
            spaceAfter=2, leading=22, fontName='Helvetica-Bold',
        )
        subtitle_style = ParagraphStyle(
            'Sub', parent=styles['Normal'],
            fontSize=9, textColor=GREY, alignment=TA_LEFT,
            spaceAfter=10, leading=11,
        )
        section_label = ParagraphStyle(
            'SectionLabel', parent=styles['Normal'],
            fontSize=9, textColor=GREY, alignment=TA_CENTER,
            fontName='Helvetica-Bold', spaceAfter=4,
        )
        level_title = ParagraphStyle(
            'LevelTitle', parent=styles['Normal'],
            fontSize=12, alignment=TA_CENTER,
            fontName='Helvetica-Bold', leading=14,
        )
        level_range = ParagraphStyle(
            'LevelRange', parent=styles['Normal'],
            fontSize=8, textColor=GREY, alignment=TA_CENTER, leading=10,
        )
        level_discount = ParagraphStyle(
            'LevelDiscount', parent=styles['Normal'],
            fontSize=9, textColor=DARK, alignment=TA_CENTER,
            fontName='Helvetica-Bold', leading=11,
        )
        footer_style = ParagraphStyle(
            'Footer', parent=styles['Normal'],
            fontSize=7.5, textColor=GREY, alignment=TA_CENTER,
            spaceBefore=8, leading=10,
        )

        # ═══ Header con logo + título ═══
        company = env.company or env['res.company'].sudo().search([], limit=1)
        logo_cell = ''
        if company and company.logo:
            try:
                logo_data = base64.b64decode(company.logo)
                logo_io = BytesIO(logo_data)
                logo_img = Image(logo_io, width=28 * mm, height=28 * mm,
                                 kind='proportional')
                logo_cell = logo_img
            except Exception as e:
                _logger.warning("No se pudo cargar logo: %s", e)
                logo_cell = Paragraph('<b>QC</b>', title_style)

        title_block = [
            Paragraph('LISTA MAYORISTA', title_style),
            Paragraph(
                f"Química Cristal &nbsp;·&nbsp; {pricelist.name} &nbsp;·&nbsp; "
                f"Actualizada al {datetime.now().strftime('%d/%m/%Y')}",
                subtitle_style
            ),
        ]

        header_table = Table(
            [[logo_cell, title_block]],
            colWidths=[32 * mm, 158 * mm],
        )
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 8))

        # ═══ Box de niveles ═══
        elements.append(Paragraph('NIVELES DE COMPRA MENSUAL', section_label))

        level_cells = [
            [
                Paragraph(f'<font color="#CD7F32">●</font> &nbsp;BRONCE', level_title),
                Paragraph(f'<font color="#9CA3AF">●</font> &nbsp;PLATA', level_title),
                Paragraph(f'<font color="#D4AF37">●</font> &nbsp;ORO', level_title),
            ],
            [
                Paragraph(LEVEL_RANGES['bronce'] + ' / mes', level_range),
                Paragraph(LEVEL_RANGES['plata'] + ' / mes', level_range),
                Paragraph(LEVEL_RANGES['oro'] + ' / mes', level_range),
            ],
            [
                Paragraph('Precio base', level_discount),
                Paragraph('5% off', level_discount),
                Paragraph('10% off', level_discount),
            ],
        ]
        levels_table = Table(level_cells, colWidths=[63 * mm, 63 * mm, 64 * mm])
        levels_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, GREY),
            ('LINEAFTER', (0, 0), (-2, -1), 0.5, GREY),
            ('BACKGROUND', (0, 0), (-1, -1), LIGHT_GREY),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(levels_table)
        elements.append(Spacer(1, 12))

        # ═══ Tabla de productos ═══
        elements.append(Paragraph('PRODUCTOS', section_label))
        elements.append(Spacer(1, 4))

        product_styles = {
            'tmpl_header': ParagraphStyle(
                'TmplHeader', parent=styles['Normal'],
                fontSize=10, textColor=DARK, fontName='Helvetica-Bold', leading=12,
            ),
            'variant': ParagraphStyle(
                'Variant', parent=styles['Normal'],
                fontSize=9, textColor=DARK, leading=11, leftIndent=12,
            ),
            'simple': ParagraphStyle(
                'Simple', parent=styles['Normal'],
                fontSize=9.5, textColor=DARK, leading=11,
            ),
            'code': ParagraphStyle(
                'Code', parent=styles['Normal'],
                fontSize=8, textColor=GREY, alignment=TA_CENTER, leading=10,
            ),
            'price': ParagraphStyle(
                'Price', parent=styles['Normal'],
                fontSize=9, textColor=DARK, alignment=TA_RIGHT,
                fontName='Helvetica-Bold', leading=11,
            ),
            'perliter': ParagraphStyle(
                'PerLiter', parent=styles['Normal'],
                fontSize=8, textColor=GREY, alignment=TA_RIGHT, leading=10,
            ),
        }

        header_row = [
            Paragraph('<b>CÓDIGO</b>', product_styles['code']),
            Paragraph('<b>PRODUCTO</b>', ParagraphStyle(
                'h', parent=product_styles['simple'],
                fontName='Helvetica-Bold', textColor=colors.white,
            )),
            Paragraph('<b>BRONCE</b>', ParagraphStyle(
                'h', parent=product_styles['price'], textColor=colors.white,
            )),
            Paragraph('<b>PLATA</b>', ParagraphStyle(
                'h', parent=product_styles['price'], textColor=colors.white,
            )),
            Paragraph('<b>ORO</b>', ParagraphStyle(
                'h', parent=product_styles['price'], textColor=colors.white,
            )),
        ]

        rows = [header_row]
        row_meta = []  # 'header_template', 'variant_row', 'simple'

        for tmpl in templates:
            variants = tmpl.product_variant_ids.filtered(lambda v: v.sale_ok)
            if not variants:
                continue

            has_multiple = len(variants) > 1

            if has_multiple:
                rows.append([
                    '',
                    Paragraph(tmpl.name, product_styles['tmpl_header']),
                    '', '', '',
                ])
                row_meta.append('tmpl_header')

            for variant in variants:
                base_price = _get_pricelist_price(pricelist, variant)
                p_bronce = base_price * (1 - LEVEL_DISCOUNTS['bronce'])
                p_plata = base_price * (1 - LEVEL_DISCOUNTS['plata'])
                p_oro = base_price * (1 - LEVEL_DISCOUNTS['oro'])

                if has_multiple:
                    attribute_label = variant.product_template_attribute_value_ids.mapped(
                        'name'
                    )
                    label = ' / '.join(attribute_label) if attribute_label else (
                        variant.display_name.replace(tmpl.name, '').strip().lstrip('(').rstrip(')').strip()
                        or variant.display_name
                    )
                    name_para = Paragraph(f"↳ {label}", product_styles['variant'])
                else:
                    name_para = Paragraph(variant.display_name, product_styles['simple'])

                rows.append([
                    Paragraph(variant.default_code or '—', product_styles['code']),
                    name_para,
                    Paragraph(f"${p_bronce:,.0f}", product_styles['price']),
                    Paragraph(f"${p_plata:,.0f}", product_styles['price']),
                    Paragraph(f"${p_oro:,.0f}", product_styles['price']),
                ])
                row_meta.append('variant_row' if has_multiple else 'simple')

        # Anchos: total 190mm. Sin columna $/L queda más holgado
        col_widths = [25 * mm, 95 * mm, 23 * mm, 23 * mm, 24 * mm]
        products_table = Table(rows, colWidths=col_widths, repeatRows=1)

        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), ORANGE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('LINEBELOW', (0, 0), (-1, 0), 1, ORANGE_DARK),
        ]

        for idx, meta in enumerate(row_meta, start=1):
            if meta == 'tmpl_header':
                style_cmds.append(('BACKGROUND', (0, idx), (-1, idx), colors.HexColor('#FFF5E6')))
                style_cmds.append(('SPAN', (1, idx), (4, idx)))
                style_cmds.append(('TOPPADDING', (0, idx), (-1, idx), 6))
                style_cmds.append(('BOTTOMPADDING', (0, idx), (-1, idx), 2))
            elif meta == 'variant_row':
                style_cmds.append(('LINEBELOW', (0, idx), (-1, idx), 0.25, colors.HexColor('#EFEFEF')))
            else:  # simple
                if idx % 2 == 0:
                    style_cmds.append(('BACKGROUND', (0, idx), (-1, idx), LIGHT_GREY))
                style_cmds.append(('LINEBELOW', (0, idx), (-1, idx), 0.25, colors.HexColor('#E5E5E5')))

        products_table.setStyle(TableStyle(style_cmds))
        elements.append(products_table)

        # ═══ Footer ═══
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(
            'Precios en pesos argentinos · IVA incluido · Sujetos a modificación sin previo aviso',
            footer_style
        ))
        elements.append(Paragraph(
            '<b>Compra mínima mayorista:</b> $50.000',
            footer_style
        ))
        elements.append(Paragraph(
            '<b>Compra mínima de producto a granel:</b> 20 litros',
            footer_style
        ))

        doc.build(elements)
        return buf.getvalue()
