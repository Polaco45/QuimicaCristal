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
        "Podés pasar only_level='oro' (o 'plata'/'bronce') para generar la lista con UNA "
        "sola columna de precio de ese nivel (descuento ya aplicado) — ideal para mandarle "
        "a un cliente preferencial su precio final sin mostrar los otros niveles. "
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
            "only_level": {
                "type": "string",
                "enum": ["bronce", "plata", "oro"],
                "description": "(Opcional) Genera la lista con UNA sola columna de precio "
                               "de ese nivel (con el descuento ya aplicado: plata −5%, oro "
                               "−10%). Útil para mandarle a un cliente preferencial su precio "
                               "final sin mostrar los otros niveles. Si se omite, salen las 3 "
                               "columnas (Bronce/Plata/Oro).",
            },
        },
    }

    def _execute(self, env, run=None, pricelist_name='Lista Mayorista',
                 pricelist_id=None, only_level=None, **kwargs):
        if only_level:
            only_level = str(only_level).strip().lower()
            if only_level not in LEVEL_DISCOUNTS:
                return {"error": f"only_level inválido: '{only_level}'. Usá bronce, plata u oro."}
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
            pdf_content = self._build_pdf(env, pricelist, templates, only_level=only_level)
        except ImportError as e:
            return {"error": f"reportlab no instalado: {e}"}
        except Exception as e:
            _logger.exception("Error generando PDF: %s", e)
            return {"error": f"Error PDF: {e}"}

        fname_suffix = f"_{only_level.capitalize()}" if only_level else "_Mayorista"
        try:
            attachment = env['ir.attachment'].sudo().create({
                'name': f"Lista_{pricelist.name.replace(' ', '_')}{fname_suffix}.pdf",
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
                f"PDF Lista '{pricelist.name}'"
                f"{' — solo nivel ' + only_level.upper() if only_level else ''} "
                f"generado con {len(templates)} productos del Catálogo Mayorista. "
                f"attachment_id={attachment.id}."
            ),
        }

    def _build_pdf(self, env, pricelist, templates, only_level=None):
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

        # Modo "un solo nivel" (ej: Oro para cliente preferencial): una sola
        # columna de precio con el descuento del nivel ya aplicado.
        single = bool(only_level)
        LEVEL_LABEL = {'bronce': 'BRONCE', 'plata': 'PLATA', 'oro': 'ORO'}
        LEVEL_OFF = {'bronce': 'precio base', 'plata': '5% OFF', 'oro': '10% OFF'}
        LEVEL_HEX = {'bronce': '#CD7F32', 'plata': '#9CA3AF', 'oro': '#D4AF37'}
        sel_disc = LEVEL_DISCOUNTS.get(only_level, 0.0)
        ncols = 4 if single else 6

        def _blank_row(para):
            """Fila que ocupa todo el ancho (section/line/tmpl) con el nº de columnas correcto."""
            return [para] + [''] * (ncols - 1)

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
        if single:
            elements.append(Paragraph('PRECIO PREFERENCIAL', section_label))
            level_cells = [
                [Paragraph(
                    f'<font color="{LEVEL_HEX[only_level]}">●</font> &nbsp;NIVEL '
                    f'{LEVEL_LABEL[only_level]}', level_title)],
                [Paragraph(f'{LEVEL_RANGES[only_level]} / mes', level_range)],
                [Paragraph(f'{LEVEL_OFF[only_level]} — precio final ya aplicado',
                           level_discount)],
            ]
            levels_table = Table(level_cells, colWidths=[190 * mm])
            level_style = [
                ('BOX', (0, 0), (-1, -1), 0.5, GREY),
                ('BACKGROUND', (0, 0), (-1, -1), LIGHT_GREY),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ]
        else:
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
            level_style = [
                ('BOX', (0, 0), (-1, -1), 0.5, GREY),
                ('LINEAFTER', (0, 0), (-2, -1), 0.5, GREY),
                ('BACKGROUND', (0, 0), (-1, -1), LIGHT_GREY),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ]
        levels_table.setStyle(TableStyle(level_style))
        elements.append(levels_table)
        elements.append(Spacer(1, 12))

        # ═══ Tabla de productos (segmentada) ═══
        # v1.11: rediseño. Dos secciones grandes:
        #   1) LÍQUIDOS A GRANEL (Fabricación + Fraccionado) — PRIMERO
        #   2) DISTRIBUCIÓN (reventa / línea seca)
        # Dentro de cada sección, sub-headers por LÍNEA (nombre de categoría hoja
        # visible). Columna de UNIDAD (litro/unidad) + 1 precio claro por fila.
        from collections import defaultdict

        NAVY = colors.HexColor('#1F2A44')        # banner de sección
        LINE_BG = colors.HexColor('#FFE7C2')     # header de línea (naranja suave)

        st_section = ParagraphStyle(
            'Sec', parent=styles['Normal'], fontSize=12, textColor=colors.white,
            fontName='Helvetica-Bold', leading=15, alignment=TA_LEFT,
        )
        st_line = ParagraphStyle(
            'Line', parent=styles['Normal'], fontSize=10.5, textColor=ORANGE_DARK,
            fontName='Helvetica-Bold', leading=13, alignment=TA_LEFT,
        )
        st_tmpl = ParagraphStyle(
            'Tmpl', parent=styles['Normal'], fontSize=9.5, textColor=DARK,
            fontName='Helvetica-Bold', leading=12,
        )
        st_variant = ParagraphStyle(
            'Var', parent=styles['Normal'], fontSize=9, textColor=DARK,
            leading=11, leftIndent=12,
        )
        st_simple = ParagraphStyle(
            'Simp', parent=styles['Normal'], fontSize=9.5, textColor=DARK, leading=11,
        )
        st_code = ParagraphStyle(
            'Cod', parent=styles['Normal'], fontSize=7.5, textColor=GREY,
            alignment=TA_CENTER, leading=9,
        )
        st_unit = ParagraphStyle(
            'Unit', parent=styles['Normal'], fontSize=8.5, textColor=GREY,
            alignment=TA_CENTER, leading=10,
        )
        st_price = ParagraphStyle(
            'Prc', parent=styles['Normal'], fontSize=10, textColor=DARK,
            alignment=TA_RIGHT, fontName='Helvetica-Bold', leading=12,
        )
        st_hdr = ParagraphStyle(
            'Hdr', parent=styles['Normal'], fontSize=8.5, textColor=colors.white,
            fontName='Helvetica-Bold', leading=10,
        )

        LIQUID_ROOTS = {'fabricación', 'fabricacion', 'fraccionado'}
        LIQUID_LINE_ORDER = {
            'linea lavandería': 1, 'linea lavanderia': 1,
            'detergente': 2,
            'desengrasante': 3,
            'lavandina': 4,
            'cloro': 5,
            'bases concentradas': 6,
            'mantenimiento de pisos': 7,
            'perfumeria/higiene personal': 8, 'perfumería/higiene personal': 8,
        }

        def _section_of(t):
            cn = (t.categ_id.complete_name or t.categ_id.name or '').lower()
            root = cn.split('/')[0].strip()
            return 'liquidos' if root in LIQUID_ROOTS else 'distribucion'

        def _unit_of(variant):
            name = (variant.name or '').lower()
            uom = (variant.uom_id.name or '').strip().lower()
            if 'granel' in name or uom in ('l', 'lt', 'litro', 'litros') or 'lit' in uom:
                return 'x litro'
            return 'x unidad'

        def _price_strings(variant):
            """Devuelve la lista de strings de precio: 1 en modo single, 3 en modo full."""
            base = _get_pricelist_price(pricelist, variant)
            if not base or base <= 0:
                return ['a consultar'] + ([] if single else ['', ''])
            if single:
                return [f"${base * (1 - sel_disc):,.0f}"]
            return [
                f"${base * (1 - LEVEL_DISCOUNTS['bronce']):,.0f}",
                f"${base * (1 - LEVEL_DISCOUNTS['plata']):,.0f}",
                f"${base * (1 - LEVEL_DISCOUNTS['oro']):,.0f}",
            ]

        # Agrupar: sección → línea (nombre hoja) → [templates]
        groups = {'liquidos': defaultdict(list), 'distribucion': defaultdict(list)}
        for tmpl in templates:
            if not tmpl.product_variant_ids.filtered(lambda v: v.sale_ok):
                continue
            line = tmpl.categ_id.name if tmpl.categ_id else 'Otros'
            groups[_section_of(tmpl)][line].append(tmpl)

        st_hdr_r = ParagraphStyle('hr', parent=st_hdr, alignment=TA_RIGHT)
        LEVEL_HDR = {'bronce': 'BRONCE', 'plata': 'PLATA −5%', 'oro': 'ORO −10%'}
        if single:
            price_headers = [Paragraph(LEVEL_HDR[only_level], st_hdr_r)]
        else:
            price_headers = [
                Paragraph('BRONCE', st_hdr_r),
                Paragraph('PLATA −5%', st_hdr_r),
                Paragraph('ORO −10%', st_hdr_r),
            ]
        header_row = [
            Paragraph('CÓDIGO', st_hdr),
            Paragraph('PRODUCTO', st_hdr),
            Paragraph('UNIDAD', ParagraphStyle('hu', parent=st_hdr, alignment=TA_CENTER)),
        ] + price_headers
        rows = [header_row]
        row_meta = []

        SECTIONS = [
            ('liquidos', 'LÍQUIDOS A GRANEL · FABRICACIÓN PROPIA'),
            ('distribucion', 'DISTRIBUCIÓN · LÍNEA SECA Y REVENTA'),
        ]

        for sec_key, sec_title in SECTIONS:
            lines = groups[sec_key]
            if not lines:
                continue
            rows.append(_blank_row(Paragraph(sec_title, st_section)))
            row_meta.append('section')

            def _line_key(l):
                ll = l.lower()
                return (LIQUID_LINE_ORDER.get(ll, 99), ll) if sec_key == 'liquidos' else (0, ll)

            for line in sorted(lines.keys(), key=_line_key):
                rows.append(_blank_row(Paragraph(line.upper(), st_line)))
                row_meta.append('line')

                tmpls = sorted(
                    lines[line],
                    key=lambda t: (-(t.mayorista_priority or 0), t.name),
                )
                for tmpl in tmpls:
                    variants = tmpl.product_variant_ids.filtered(lambda v: v.sale_ok)
                    multi = len(variants) > 1
                    if multi:
                        rows.append(_blank_row(Paragraph(tmpl.name, st_tmpl)))
                        row_meta.append('tmpl')
                    for v in variants:
                        if multi:
                            attrs = v.product_template_attribute_value_ids.mapped('name')
                            label = ' / '.join(attrs) if attrs else (
                                v.display_name.replace(tmpl.name, '').strip(' ()') or v.display_name)
                            name_para = Paragraph(f"↳ {label}", st_variant)
                        else:
                            name_para = Paragraph(v.display_name, st_simple)
                        price_cells = [Paragraph(p, st_price) for p in _price_strings(v)]
                        rows.append([
                            Paragraph(v.default_code or '—', st_code),
                            name_para,
                            Paragraph(_unit_of(v), st_unit),
                        ] + price_cells)
                        row_meta.append('variant' if multi else 'simple')

        # Anchos: total 190mm. 6 columnas (3 niveles) o 4 columnas (1 nivel).
        if single:
            col_widths = [20 * mm, 110 * mm, 24 * mm, 36 * mm]
        else:
            col_widths = [18 * mm, 78 * mm, 20 * mm, 24 * mm, 24 * mm, 26 * mm]
        products_table = Table(rows, colWidths=col_widths, repeatRows=1)

        style_cmds = [
            # header
            ('BACKGROUND', (0, 0), (-1, 0), ORANGE),
            ('LINEBELOW', (0, 0), (-1, 0), 1, ORANGE_DARK),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]

        for idx, meta in enumerate(row_meta, start=1):
            if meta == 'section':
                style_cmds += [
                    ('SPAN', (0, idx), (-1, idx)),
                    ('BACKGROUND', (0, idx), (-1, idx), NAVY),
                    ('TOPPADDING', (0, idx), (-1, idx), 9),
                    ('BOTTOMPADDING', (0, idx), (-1, idx), 9),
                    ('LEFTPADDING', (0, idx), (-1, idx), 10),
                ]
            elif meta == 'line':
                style_cmds += [
                    ('SPAN', (0, idx), (-1, idx)),
                    ('BACKGROUND', (0, idx), (-1, idx), LINE_BG),
                    ('TOPPADDING', (0, idx), (-1, idx), 6),
                    ('BOTTOMPADDING', (0, idx), (-1, idx), 6),
                    ('LEFTPADDING', (0, idx), (-1, idx), 10),
                ]
            elif meta == 'tmpl':
                style_cmds += [
                    ('SPAN', (0, idx), (-1, idx)),
                    ('BACKGROUND', (0, idx), (-1, idx), colors.HexColor('#FBFBFB')),
                    ('TOPPADDING', (0, idx), (-1, idx), 5),
                    ('BOTTOMPADDING', (0, idx), (-1, idx), 1),
                ]
            elif meta == 'variant':
                style_cmds.append(('LINEBELOW', (0, idx), (-1, idx), 0.25, colors.HexColor('#EFEFEF')))
            else:  # simple
                if idx % 2 == 0:
                    style_cmds.append(('BACKGROUND', (0, idx), (-1, idx), LIGHT_GREY))
                style_cmds.append(('LINEBELOW', (0, idx), (-1, idx), 0.25, colors.HexColor('#E5E5E5')))

        products_table.setStyle(TableStyle(style_cmds))
        elements.append(products_table)

        # ═══ Footer ═══
        elements.append(Spacer(1, 12))
        if single:
            elements.append(Paragraph(
                f'<b>Precios nivel {LEVEL_LABEL[only_level]} ({LEVEL_OFF[only_level]}) — '
                f'ya aplicado sobre esta lista.</b> '
                'Granel = precio por litro · Envasados = precio por unidad.',
                footer_style
            ))
        else:
            elements.append(Paragraph(
                '<b>Precios BRONCE (base).</b> Tu nivel define el descuento: PLATA −5% · ORO −10%. '
                'Granel = precio por litro · Envasados = precio por unidad.',
                footer_style
            ))
        elements.append(Paragraph(
            'Precios en pesos argentinos · IVA incluido · Sujetos a modificación sin previo aviso',
            footer_style
        ))
        elements.append(Paragraph(
            '<b>Compra mínima mayorista:</b> $50.000 &nbsp;·&nbsp; '
            '<b>Mínimo de producto a granel:</b> 20 litros',
            footer_style
        ))

        doc.build(elements)
        return buf.getvalue()
