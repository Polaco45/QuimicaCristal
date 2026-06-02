# -*- coding: utf-8 -*-
import json
import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from calendar import monthrange

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURACIÓN: Mapeo de product.category → macro categoría
# ============================================================
# Validado en Odoo el 01/06/2026 contra los 53 product.category reales.
# Para mantener: si Joaco crea una categoría nueva en Odoo, agregarla acá.
# Cualquier producto cuya categoría NO esté mapeada cae automáticamente
# en "Varios" (no rompe el reporte, solo no clasifica fino).
CATEGORIAS_REPORTE = {
    'liquidos': [
        # Marca propia Crilimp (Fabricación)
        34,  # Detergente
        9,   # Desengrasante
        16,  # Limpiador Desinf Desod
        21,  # Linea Lavandería
        15,  # Perfumeria/Higiene Personal
        18,  # Quimicos p/Piletas
        11,  # Bases Concentradas
        # Crilimp envasado (Fraccionado)
        32,  # Cloro
        50,  # Lavandina
        12,  # Mantenimiento de pisos
        # Distribución (reventa de tercero)
        51,  # Liquidos
        22,  # Aerosoles Aromatizantes
        10,  # Aromatizantes de Ambientes
        39,  # Limpia Vidrios
    ],
    'papeles': [
        30,  # Distribución/Servilletas y Papel Higiénico
    ],
    'bolsas': [
        27,  # Distribución/Bolsas
    ],
    'accesorios': [
        24,  # Baldes y fuentones
        19,  # Barrenderos y Mopas Institucionales
        28,  # Cabos
        29,  # Cestos y contenedores
        26,  # Dispensers y accesorios
        31,  # Escobillones y cepillos
        35,  # Esponjas
        33,  # Gatillos y pulverizadores
        37,  # Guantes
        38,  # Lampazos-Mopas-Pasaceras
        40,  # Palas
        41,  # Plumeros
        44,  # Secadores y sopapas
        36,  # Trapos-Gamuzas-Repasadores
        17,  # Alfombras y Felpudos
        25,  # Envases
    ],
    'varios': [
        13,  # Accesorios p/piletas
        8,   # Bazar
        20,  # Casa y Jardin
        23,  # Linea Automotor
        53,  # Combos y Kit
    ],
    'consumo_masivo': [
        7,   # Consumo Masivo (marcas líder: Blem, Raid, Glade, Cif, Lysoform...)
    ],
}

# Labels visuales para el reporte
CATEGORIAS_LABELS = {
    'liquidos': 'Líquidos',
    'papeles': 'Papeles',
    'bolsas': 'Bolsas',
    'accesorios': 'Accesorios',
    'varios': 'Varios',
    'consumo_masivo': 'Consumo Masivo',
}

# Partners internos a excluir SIEMPRE (consumo propio)
PARTNERS_INTERNOS = [3, 60023, 65371, 65374, 75679, 79526, 79653, 80799, 64675]

# Company operativa única
COMPANY_OPERATIVA = 1

MESES_ES = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
    5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
    9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre',
}


def macro_categoria(categ_id, product_name=None):
    """Mapea product.category.id a una macro categoría del reporte.
    Default: 'varios' (no rompe nada si la categoría no está mapeada).

    Override papeles: la categoría 26 'Dispensers y accesorios' de Odoo mezcla
    dispensers reales (accesorios) con bobinas / papel higiénico / toallas de
    papel (que son PAPELES). Como no se puede partir la categoría sin tocar la
    data maestra de Odoo (con riesgo contable), se reclasifican acá por nombre:
    los productos de papel de esa categoría van a 'papeles', los dispensers y
    porta-rollos siguen en 'accesorios'.
    """
    name = (product_name or '').lower()
    if categ_id == 26 and name:
        es_dispenser = ('dispenser' in name) or ('porta rollo' in name)
        es_papel = (
            'bobina' in name or 'papel hig' in name
            or 'toalla inter' in name or 'toalla pack' in name
        )
        if es_papel and not es_dispenser:
            return 'papeles'
    if not categ_id:
        return 'varios'
    for macro, ids in CATEGORIAS_REPORTE.items():
        if categ_id in ids:
            return macro
    return 'varios'


def _build_donut_svg(liq_pct=0, pap_pct=0, bol_pct=0, acc_pct=0, var_pct=0, cm_pct=0):
    """Construye un SVG inline del donut con 5 segmentos.

    Compatible con wkhtmltopdf (que NO soporta conic-gradient).
    Cada segmento es un path con dos arcos (exterior + interior) que forma
    una porción del donut. Si un segmento es 0%, no se incluye.

    Returns:
        str: SVG inline listo para insertar en HTML.
    """
    cx, cy = 46, 46            # centro
    r_outer = 46               # radio exterior
    r_inner = 24               # radio interior (hueco central)

    segmentos = [
        (liq_pct, '#ee7b1f'),  # Líquidos
        (pap_pct, '#d86b0f'),  # Papeles
        (bol_pct, '#1a1a1a'),  # Bolsas
        (acc_pct, '#7a7a7a'),  # Accesorios
        (var_pct, '#bababa'),  # Varios
        (cm_pct,  '#4a4a4a'),  # Consumo Masivo
    ]

    # Filtrar segmentos en 0
    total = sum(p for p, _c in segmentos)
    if total <= 0:
        # Sin datos: donut gris
        return (
            '<svg width="92" height="92" viewBox="0 0 92 92" xmlns="http://www.w3.org/2000/svg">'
            f'<circle cx="{cx}" cy="{cy}" r="{r_outer}" fill="#e5e5e5"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r_inner}" fill="#fff"/>'
            '</svg>'
        )

    paths = []
    start_angle_deg = -90.0    # empezar arriba (12 o'clock)

    for pct, color in segmentos:
        if pct <= 0:
            continue

        end_angle_deg = start_angle_deg + (pct * 3.6)  # 100% = 360°

        start_rad = math.radians(start_angle_deg)
        end_rad = math.radians(end_angle_deg)

        # Puntos exteriores (radio r_outer)
        x1 = cx + r_outer * math.cos(start_rad)
        y1 = cy + r_outer * math.sin(start_rad)
        x2 = cx + r_outer * math.cos(end_rad)
        y2 = cy + r_outer * math.sin(end_rad)

        # Puntos interiores (radio r_inner)
        x3 = cx + r_inner * math.cos(end_rad)
        y3 = cy + r_inner * math.sin(end_rad)
        x4 = cx + r_inner * math.cos(start_rad)
        y4 = cy + r_inner * math.sin(start_rad)

        large_arc = 1 if (end_angle_deg - start_angle_deg) > 180 else 0

        # Caso especial: si pct >= 99.5%, dibujar un anillo completo
        if pct >= 99.5:
            paths.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r_outer}" fill="{color}"/>'
            )
        else:
            d = (
                f'M {x1:.3f} {y1:.3f} '
                f'A {r_outer} {r_outer} 0 {large_arc} 1 {x2:.3f} {y2:.3f} '
                f'L {x3:.3f} {y3:.3f} '
                f'A {r_inner} {r_inner} 0 {large_arc} 0 {x4:.3f} {y4:.3f} '
                f'Z'
            )
            paths.append(f'<path d="{d}" fill="{color}"/>')

        start_angle_deg = end_angle_deg

    # Hueco central blanco encima
    paths.append(f'<circle cx="{cx}" cy="{cy}" r="{r_inner}" fill="#fff"/>')

    return (
        '<svg width="92" height="92" viewBox="0 0 92 92" xmlns="http://www.w3.org/2000/svg">'
        + ''.join(paths) +
        '</svg>'
    )


class QuimicaCristalReporteMensual(models.Model):
    _name = 'quimica.cristal.reporte.mensual'
    _description = 'Reporte mensual Plan Control'
    _order = 'period_year desc, period_month desc, partner_id'
    _rec_name = 'display_name'

    # ============================================================
    # CAMPOS BÁSICOS
    # ============================================================
    display_name = fields.Char(compute='_compute_display_name', store=True)
    partner_id = fields.Many2one(
        'res.partner', string='Cliente', required=True, ondelete='restrict',
        domain=[('parent_id', '=', False)],
        index=True,
    )
    period_year = fields.Integer(string='Año', required=True, index=True)
    period_month = fields.Integer(
        string='Mes', required=True, index=True,
    )
    date_from = fields.Date(string='Desde', compute='_compute_period_dates', store=True)
    date_to = fields.Date(string='Hasta', compute='_compute_period_dates', store=True)
    company_id = fields.Many2one(
        'res.company', string='Compañía', default=lambda self: self.env.company,
        required=True,
    )

    state = fields.Selection([
        ('draft', 'Borrador'),
        ('generated', 'Generado'),
        ('sent', 'Enviado'),
    ], default='draft', required=True)

    # ============================================================
    # KPIs CALCULADOS (TOTAL con IVA, NC restada)
    # ============================================================
    amount_total = fields.Monetary(
        string='Total del mes',
        currency_field='currency_id',
        help='TOTAL con IVA, restando notas de crédito',
    )
    pedidos = fields.Integer(string='Cantidad de facturas (sin contar NC)')
    notas_credito = fields.Integer(string='Cantidad de notas de crédito')
    productos_distintos = fields.Integer(string='Productos distintos')
    ticket_promedio = fields.Monetary(
        string='Ticket promedio', currency_field='currency_id',
    )
    vs_anterior_pct = fields.Float(
        string='Variación vs mes anterior (%)', digits=(5, 2),
    )

    currency_id = fields.Many2one(
        'res.currency', string='Moneda',
        default=lambda self: self.env.company.currency_id,
    )

    # ============================================================
    # MULTI-SUCURSAL
    # ============================================================
    is_multi_sucursal = fields.Boolean(string='Multi-sucursal')
    sucursal_ids = fields.One2many(
        'quimica.cristal.reporte.mensual.sucursal', 'reporte_id',
        string='Sucursales',
    )
    sucursales_count = fields.Integer(
        compute='_compute_sucursales_count', store=True,
    )

    # ============================================================
    # CATEGORÍAS (montos consolidados)
    # ============================================================
    cat_liquidos = fields.Monetary(string='Líquidos', currency_field='currency_id')
    cat_papeles = fields.Monetary(string='Papeles', currency_field='currency_id')
    cat_bolsas = fields.Monetary(string='Bolsas', currency_field='currency_id')
    cat_accesorios = fields.Monetary(string='Accesorios', currency_field='currency_id')
    cat_varios = fields.Monetary(string='Varios', currency_field='currency_id')
    cat_consumo_masivo = fields.Monetary(string='Consumo Masivo', currency_field='currency_id')

    cat_liquidos_pct = fields.Float(string='Líquidos %', digits=(5, 2))
    cat_papeles_pct = fields.Float(string='Papeles %', digits=(5, 2))
    cat_bolsas_pct = fields.Float(string='Bolsas %', digits=(5, 2))
    cat_accesorios_pct = fields.Float(string='Accesorios %', digits=(5, 2))
    cat_varios_pct = fields.Float(string='Varios %', digits=(5, 2))
    cat_consumo_masivo_pct = fields.Float(string='Consumo Masivo %', digits=(5, 2))

    # ============================================================
    # TENDENCIA 4 MESES (JSON)
    # ============================================================
    trend_data = fields.Text(string='Tendencia 4 meses (JSON)')

    # ============================================================
    # LÍNEAS DE PRODUCTO (single-direccion)
    # ============================================================
    line_ids = fields.One2many(
        'quimica.cristal.reporte.mensual.line', 'reporte_id',
        string='Productos',
        help='Líneas de producto consolidadas (single-dirección)',
    )

    # ============================================================
    # OBSERVACIÓN MANUAL OPCIONAL (sin auto-cómputo)
    # ============================================================
    # Queda vacío por default. Si Joaco quiere agregar nota a un
    # reporte específico, edita esto desde la UI antes de mandar.
    # El cron automático NUNCA escribe acá.
    observation = fields.Text(
        string='Observación (opcional, manual)',
        help='Si tiene contenido, aparece en el PDF. Vacío por default.',
    )

    # ============================================================
    # CAMPOS DE AUDITORÍA
    # ============================================================
    generation_log = fields.Text(string='Log de generación', readonly=True)
    sent_date = fields.Datetime(string='Fecha de envío', readonly=True)
    sent_email = fields.Char(string='Email destino', readonly=True)

    _sql_constraints = [
        ('unique_partner_period',
         'UNIQUE(partner_id, period_year, period_month, company_id)',
         '¡Ya existe un reporte para este cliente en este período!'),
    ]

    # ============================================================
    # COMPUTE
    # ============================================================
    @api.depends('partner_id', 'period_year', 'period_month')
    def _compute_display_name(self):
        for rec in self:
            if rec.partner_id and rec.period_year and rec.period_month:
                mes_nombre = MESES_ES.get(rec.period_month, str(rec.period_month))
                rec.display_name = f"{rec.partner_id.name} · {mes_nombre} {rec.period_year}"
            else:
                rec.display_name = 'Reporte Mensual'

    @api.depends('period_year', 'period_month')
    def _compute_period_dates(self):
        for rec in self:
            if rec.period_year and rec.period_month:
                last_day = monthrange(rec.period_year, rec.period_month)[1]
                rec.date_from = date(rec.period_year, rec.period_month, 1)
                rec.date_to = date(rec.period_year, rec.period_month, last_day)
            else:
                rec.date_from = False
                rec.date_to = False

    @api.depends('sucursal_ids')
    def _compute_sucursales_count(self):
        for rec in self:
            rec.sucursales_count = len(rec.sucursal_ids)

    # ============================================================
    # CONSTRAINTS
    # ============================================================
    @api.constrains('period_month')
    def _check_period_month(self):
        for rec in self:
            if rec.period_month and not (1 <= rec.period_month <= 12):
                raise ValidationError(_('El mes debe estar entre 1 y 12.'))

    # ============================================================
    # MÉTODO PRINCIPAL: ACTION_GENERATE
    # ============================================================
    def action_generate(self):
        """Genera todo el contenido del reporte.

        Reglas críticas:
        - TOTAL con IVA (amount_total), NO subtotal
        - Notas de crédito (out_refund) RESTAN
        - Excluye partners internos
        - company_id = 1 (única operativa)
        """
        for rec in self:
            rec._do_generate()
        return True

    def _do_generate(self):
        """Lógica de generación (1 registro a la vez)."""
        self.ensure_one()
        log = []
        log.append(f"=== Generación de reporte {self.display_name} ===")
        log.append(f"Período: {self.date_from} → {self.date_to}")

        # Limpiar contenido anterior
        self.line_ids.unlink()
        self.sucursal_ids.unlink()

        # Reset KPIs
        self.write({
            'amount_total': 0,
            'pedidos': 0,
            'notas_credito': 0,
            'productos_distintos': 0,
            'ticket_promedio': 0,
            'vs_anterior_pct': 0,
            'is_multi_sucursal': False,
            'cat_liquidos': 0, 'cat_papeles': 0, 'cat_bolsas': 0,
            'cat_accesorios': 0, 'cat_varios': 0,
            'cat_liquidos_pct': 0, 'cat_papeles_pct': 0, 'cat_bolsas_pct': 0,
            'cat_accesorios_pct': 0, 'cat_varios_pct': 0,
        })

        # ============================================================
        # PASO 1: Obtener TODOS los account.move del período
        # ============================================================
        moves = self.env['account.move'].search([
            ('commercial_partner_id', '=', self.partner_id.id),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
            ('company_id', '=', self.company_id.id),
        ])
        log.append(f"Account moves encontrados: {len(moves)}")

        if not moves:
            log.append("Sin facturas en el período. Reporte vacío.")
            self.generation_log = '\n'.join(log)
            self.state = 'generated'
            return

        # ============================================================
        # PASO 2: Detectar multi-sucursal
        # ============================================================
        shipping_partners = moves.mapped('partner_shipping_id').filtered(
            lambda p: p and p.id != self.partner_id.id
        )
        unique_shippings = list(set(shipping_partners.ids))

        # Considerar multi si hay 2+ direcciones de envío distintas
        is_multi = len(unique_shippings) >= 2
        self.is_multi_sucursal = is_multi
        log.append(f"Multi-sucursal: {is_multi} ({len(unique_shippings)} shippings)")

        # ============================================================
        # PASO 3: Calcular KPIs CONSOLIDADOS
        # IMPORTANTE: TOTAL c/IVA + NC restada
        # ============================================================
        # amount_total_signed ya viene con el signo correcto:
        # - out_invoice → positivo
        # - out_refund  → negativo
        # Esto resuelve la lógica de NC automáticamente.
        invoices = moves.filtered(lambda m: m.move_type == 'out_invoice')
        refunds = moves.filtered(lambda m: m.move_type == 'out_refund')

        amount_total = sum(invoices.mapped('amount_total')) - sum(refunds.mapped('amount_total'))

        self.amount_total = amount_total
        self.pedidos = len(invoices)
        self.notas_credito = len(refunds)
        self.ticket_promedio = (amount_total / len(invoices)) if invoices else 0

        log.append(f"Facturas (out_invoice): {len(invoices)}")
        log.append(f"Notas de crédito (out_refund): {len(refunds)}")
        log.append(f"TOTAL (c/IVA, NC restada): ${amount_total:,.2f}")

        # ============================================================
        # PASO 4: Calcular variación vs mes anterior
        # ============================================================
        prev_amount = self._compute_previous_month_amount()
        if prev_amount:
            self.vs_anterior_pct = (amount_total / prev_amount - 1) * 100
        else:
            self.vs_anterior_pct = 0
        log.append(f"Mes anterior: ${prev_amount:,.2f} ({self.vs_anterior_pct:+.1f}%)")

        # ============================================================
        # PASO 5: Calcular tendencia 4 meses
        # ============================================================
        trend = self._compute_trend_4_months()
        self.trend_data = json.dumps(trend)
        log.append(f"Tendencia: {trend}")

        # ============================================================
        # PASO 6: Procesar líneas de producto (account.move.line)
        # ============================================================
        if is_multi:
            # Una sucursal por cada partner_shipping_id distinto con facturas
            for shipping_id in unique_shippings:
                self._build_sucursal(shipping_id, moves, log)
            # Líneas consolidadas del doc: necesarias para el ranking de
            # "Productos más consumidos" de la página general. Suma el mismo
            # producto a través de todas las sucursales. (Esto también escribe
            # self.cat_*, pero el bloque de abajo las recalcula por suma de
            # sucursales, que es la fuente de verdad; el amount_total NO se
            # toca acá, así que el total consolidado no cambia.)
            self._build_lineas_consolidadas(moves, log)
            # Productos distintos consolidados
            all_products = self.sucursal_ids.line_ids.mapped('product_id')
            self.productos_distintos = len(all_products)

            # Categorías consolidadas: suma de las sucursales
            for cat in ['liquidos', 'papeles', 'bolsas', 'accesorios', 'varios', 'consumo_masivo']:
                field = f'cat_{cat}'
                total_cat = sum(self.sucursal_ids.mapped(field))
                self[field] = total_cat
        else:
            # Single-dirección: las líneas van al reporte principal
            self._build_lineas_consolidadas(moves, log)
            self.productos_distintos = len(self.line_ids.mapped('product_id'))

        # Calcular porcentajes de categorías
        total_categorias = (
            self.cat_liquidos + self.cat_papeles + self.cat_bolsas
            + self.cat_accesorios + self.cat_varios + self.cat_consumo_masivo
        )
        if total_categorias > 0:
            self.cat_liquidos_pct = self.cat_liquidos / total_categorias * 100
            self.cat_papeles_pct = self.cat_papeles / total_categorias * 100
            self.cat_bolsas_pct = self.cat_bolsas / total_categorias * 100
            self.cat_accesorios_pct = self.cat_accesorios / total_categorias * 100
            self.cat_varios_pct = self.cat_varios / total_categorias * 100
            self.cat_consumo_masivo_pct = self.cat_consumo_masivo / total_categorias * 100

        log.append("=== Generación completada ===")
        self.generation_log = '\n'.join(log)
        self.state = 'generated'

    def _build_sucursal(self, shipping_id, moves, log):
        """Crea una sucursal y la pobla con sus datos."""
        shipping = self.env['res.partner'].browse(shipping_id)
        # Filtrar moves de esta sucursal
        suc_moves = moves.filtered(lambda m: m.partner_shipping_id.id == shipping_id)
        suc_invoices = suc_moves.filtered(lambda m: m.move_type == 'out_invoice')
        suc_refunds = suc_moves.filtered(lambda m: m.move_type == 'out_refund')

        suc_total = sum(suc_invoices.mapped('amount_total')) - sum(suc_refunds.mapped('amount_total'))

        sucursal = self.env['quimica.cristal.reporte.mensual.sucursal'].create({
            'reporte_id': self.id,
            'partner_shipping_id': shipping_id,
            'amount_total': suc_total,
            'pedidos': len(suc_invoices),
            'notas_credito': len(suc_refunds),
            'ticket_promedio': suc_total / len(suc_invoices) if suc_invoices else 0,
            'pct_total': (suc_total / self.amount_total * 100) if self.amount_total else 0,
        })

        # Variación vs mes anterior de esta sucursal
        prev_suc = self._compute_previous_month_amount(shipping_id=shipping_id)
        if prev_suc:
            sucursal.vs_anterior_pct = (suc_total / prev_suc - 1) * 100

        # Tendencia 4 meses de la sucursal
        trend_suc = self._compute_trend_4_months(shipping_id=shipping_id)
        sucursal.trend_data = json.dumps(trend_suc)

        # Procesar líneas de producto de esta sucursal
        self._build_lineas_consolidadas(suc_moves, log, sucursal=sucursal)
        sucursal.productos_distintos = len(sucursal.line_ids.mapped('product_id'))

        log.append(f"  Sucursal {shipping.name}: ${suc_total:,.2f} ({sucursal.pct_total:.1f}%)")

    def _build_lineas_consolidadas(self, moves, log, sucursal=False):
        """Agrupa account.move.line por producto y crea las líneas del reporte.

        Lógica:
        - Tomar account.move.line con display_type='product' (no notas, ni secciones)
        - Para out_invoice: sumar price_total (TOTAL con IVA)
        - Para out_refund: restar price_total
        - Agrupar por product_id
        """
        # Obtener todas las líneas de producto reales
        lines = self.env['account.move.line'].search([
            ('move_id', 'in', moves.ids),
            ('display_type', '=', 'product'),
            ('product_id', '!=', False),
        ])

        # Agrupar por producto
        productos = defaultdict(lambda: {
            'product_id': None,
            'quantity': 0.0,
            'amount_total': 0.0,  # TOTAL c/IVA, ya con signo (NC negativa)
        })

        for line in lines:
            move = line.move_id
            sign = 1 if move.move_type == 'out_invoice' else -1
            pid = line.product_id.id
            productos[pid]['product_id'] = line.product_id
            productos[pid]['quantity'] += line.quantity * sign
            # price_total = subtotal + impuestos = total c/IVA de la línea
            productos[pid]['amount_total'] += line.price_total * sign

        # Filtrar productos con monto > 0 (si la NC iguala o supera, no aparece)
        productos_filtrados = [
            p for p in productos.values()
            if p['amount_total'] > 0.01
        ]

        # Calcular total para porcentajes
        total_lineas = sum(p['amount_total'] for p in productos_filtrados)

        # Crear las líneas en el reporte (ordenadas por monto desc)
        productos_ordenados = sorted(
            productos_filtrados, key=lambda p: p['amount_total'], reverse=True
        )

        # Acumuladores de categoría
        cat_acum = {k: 0.0 for k in CATEGORIAS_REPORTE.keys()}

        for p in productos_ordenados:
            prod = p['product_id']
            cat_key = macro_categoria(prod.categ_id.id if prod.categ_id else None, prod.name)
            pct = (p['amount_total'] / total_lineas * 100) if total_lineas else 0

            cat_acum[cat_key] += p['amount_total']

            vals = {
                'product_id': prod.id,
                'product_default_code': prod.default_code or '',
                'product_name': prod.name,
                'categoria': cat_key,
                'quantity': p['quantity'],
                'amount_total': p['amount_total'],
                'pct_mes': pct,
            }
            if sucursal:
                vals['sucursal_id'] = sucursal.id
            else:
                vals['reporte_id'] = self.id

            self.env['quimica.cristal.reporte.mensual.line'].create(vals)

        # Guardar categorías
        if sucursal:
            sucursal.write({
                'cat_liquidos': cat_acum['liquidos'],
                'cat_papeles': cat_acum['papeles'],
                'cat_bolsas': cat_acum['bolsas'],
                'cat_accesorios': cat_acum['accesorios'],
                'cat_varios': cat_acum['varios'],
                'cat_consumo_masivo': cat_acum['consumo_masivo'],
            })
            total_suc_cat = sum(cat_acum.values())
            if total_suc_cat > 0:
                sucursal.write({
                    'cat_liquidos_pct': cat_acum['liquidos'] / total_suc_cat * 100,
                    'cat_papeles_pct': cat_acum['papeles'] / total_suc_cat * 100,
                    'cat_bolsas_pct': cat_acum['bolsas'] / total_suc_cat * 100,
                    'cat_accesorios_pct': cat_acum['accesorios'] / total_suc_cat * 100,
                    'cat_varios_pct': cat_acum['varios'] / total_suc_cat * 100,
                    'cat_consumo_masivo_pct': cat_acum['consumo_masivo'] / total_suc_cat * 100,
                })
        else:
            self.write({
                'cat_liquidos': cat_acum['liquidos'],
                'cat_papeles': cat_acum['papeles'],
                'cat_bolsas': cat_acum['bolsas'],
                'cat_accesorios': cat_acum['accesorios'],
                'cat_varios': cat_acum['varios'],
                'cat_consumo_masivo': cat_acum['consumo_masivo'],
            })

    def _compute_previous_month_amount(self, shipping_id=None):
        """Calcula el TOTAL del mes anterior (para cálculo de variación)."""
        if not self.period_year or not self.period_month:
            return 0
        # Mes anterior
        if self.period_month == 1:
            prev_year, prev_month = self.period_year - 1, 12
        else:
            prev_year, prev_month = self.period_year, self.period_month - 1

        last_day = monthrange(prev_year, prev_month)[1]
        date_from = date(prev_year, prev_month, 1)
        date_to = date(prev_year, prev_month, last_day)

        domain = [
            ('commercial_partner_id', '=', self.partner_id.id),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', date_from),
            ('invoice_date', '<=', date_to),
            ('company_id', '=', self.company_id.id),
        ]
        if shipping_id:
            domain.append(('partner_shipping_id', '=', shipping_id))

        moves = self.env['account.move'].search(domain)
        invoices = moves.filtered(lambda m: m.move_type == 'out_invoice')
        refunds = moves.filtered(lambda m: m.move_type == 'out_refund')
        return sum(invoices.mapped('amount_total')) - sum(refunds.mapped('amount_total'))

    def _compute_trend_4_months(self, shipping_id=None):
        """Calcula los totales de los últimos 4 meses (incluido el actual)."""
        trend = []
        for i in range(3, -1, -1):
            # Retroceder i meses
            year = self.period_year
            month = self.period_month - i
            while month <= 0:
                month += 12
                year -= 1

            last_day = monthrange(year, month)[1]
            df = date(year, month, 1)
            dt = date(year, month, last_day)

            domain = [
                ('commercial_partner_id', '=', self.partner_id.id),
                ('move_type', 'in', ['out_invoice', 'out_refund']),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', df),
                ('invoice_date', '<=', dt),
                ('company_id', '=', self.company_id.id),
            ]
            if shipping_id:
                domain.append(('partner_shipping_id', '=', shipping_id))

            moves = self.env['account.move'].search(domain)
            invs = moves.filtered(lambda m: m.move_type == 'out_invoice')
            refs = moves.filtered(lambda m: m.move_type == 'out_refund')
            total = sum(invs.mapped('amount_total')) - sum(refs.mapped('amount_total'))

            trend.append({
                'month_name': MESES_ES.get(month, ''),
                'month': month,
                'year': year,
                'total': float(total),
            })
        return trend

    # ============================================================
    # ENVÍO POR EMAIL
    # ============================================================
    def action_send_email(self):
        """Envía el reporte por email al cliente."""
        for rec in self:
            rec._do_send_email()
        return True

    def _do_send_email(self):
        self.ensure_one()
        if self.state == 'draft':
            self._do_generate()

        # Buscar email destino
        email = self.partner_id.email
        if not email:
            # Buscar en sub-contactos
            contact = self.env['res.partner'].search([
                ('parent_id', '=', self.partner_id.id),
                ('email', '!=', False),
            ], limit=1)
            if contact:
                email = contact.email

        if not email:
            raise UserError(_(
                'El cliente %s no tiene email cargado. Cargá un email en la '
                'ficha del cliente antes de enviar.'
            ) % self.partner_id.name)

        # Generar PDF y adjuntar
        pdf_attachment = self._generate_pdf_attachment()

        # Disparar mail template
        template = self.env.ref(
            'quimica_cristal_reporte_mensual.mail_template_reporte_mensual',
            raise_if_not_found=False,
        )
        if template:
            template.with_context(
                attachment_ids=[pdf_attachment.id],
            ).send_mail(self.id, force_send=True)
        else:
            # Fallback manual si no existe el template
            mes_nombre = MESES_ES.get(self.period_month, '')
            self.env['mail.mail'].create({
                'subject': f'Reporte mensual de consumo - {mes_nombre} {self.period_year} - Quimica Cristal',
                'email_to': email,
                'body_html': self._get_default_body_html(),
                'attachment_ids': [(4, pdf_attachment.id)],
            }).send()

        self.write({
            'state': 'sent',
            'sent_date': fields.Datetime.now(),
            'sent_email': email,
        })

    def _get_default_body_html(self):
        mes_nombre = MESES_ES.get(self.period_month, '')
        return f"""
        <p>Hola,</p>
        <p>Adjuntamos el reporte mensual de consumo de <b>{mes_nombre} {self.period_year}</b>
        correspondiente a <b>{self.partner_id.name}</b>.</p>
        <p>Cualquier consulta, escribinos al WhatsApp 358 548 1199.</p>
        <p><i>Quimica Cristal · Limpieza profesional · Río Cuarto, Córdoba</i></p>
        """

    def _generate_pdf_attachment(self):
        """Genera el PDF del reporte y lo devuelve como ir.attachment."""
        self.ensure_one()
        report = self.env.ref(
            'quimica_cristal_reporte_mensual.action_report_reporte_mensual'
        )
        pdf_content, content_type = report._render_qweb_pdf(
            'quimica_cristal_reporte_mensual.action_report_reporte_mensual',
            res_ids=[self.id],
        )
        mes_nombre = MESES_ES.get(self.period_month, '')
        filename = f'Reporte_{self.partner_id.name}_{mes_nombre}_{self.period_year}.pdf'.replace(' ', '_')

        return self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': pdf_content if isinstance(pdf_content, str) else __import__('base64').b64encode(pdf_content).decode(),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

    def action_download_pdf(self):
        """Genera y devuelve el PDF para descargar."""
        self.ensure_one()
        if self.state == 'draft':
            self._do_generate()
        return self.env.ref(
            'quimica_cristal_reporte_mensual.action_report_reporte_mensual'
        ).report_action(self)

    # ============================================================
    # CRON MENSUAL
    # ============================================================
    @api.model
    def _cron_generate_and_send_monthly(self):
        """Cron del día 1 de cada mes a las 8 AM.

        Lógica:
        1. Calcular mes anterior (el que se va a reportar)
        2. Buscar partners con tag 'Plan Control'
        3. Para cada uno: crear reporte si no existe + generar + enviar
        4. Saltear partners sin facturas en el mes
        """
        today = fields.Date.today()
        if today.month == 1:
            prev_year, prev_month = today.year - 1, 12
        else:
            prev_year, prev_month = today.year, today.month - 1

        _logger.info(
            f'[CRON Reporte Mensual] Procesando período {prev_month}/{prev_year}'
        )

        # Buscar tag Plan Control
        tag = self.env['res.partner.category'].search([
            ('name', '=', 'Plan Control'),
        ], limit=1)
        if not tag:
            _logger.warning(
                '[CRON Reporte Mensual] No existe la etiqueta "Plan Control". '
                'Saltando ejecución.'
            )
            return

        # Buscar partners con esa etiqueta (excluyendo internos)
        partners = self.env['res.partner'].search([
            ('category_id', 'in', [tag.id]),
            ('id', 'not in', PARTNERS_INTERNOS),
            ('parent_id', '=', False),
        ])
        _logger.info(
            f'[CRON Reporte Mensual] {len(partners)} partners con tag Plan Control'
        )

        success, failed, skipped = [], [], []
        for partner in partners:
            try:
                # ¿Ya existe el reporte de este período?
                existing = self.search([
                    ('partner_id', '=', partner.id),
                    ('period_year', '=', prev_year),
                    ('period_month', '=', prev_month),
                ], limit=1)

                if existing:
                    _logger.info(
                        f'[CRON Reporte Mensual] {partner.name}: ya existe, salteo'
                    )
                    skipped.append(partner.name)
                    continue

                # Verificar que tenga facturas en el período
                last_day = monthrange(prev_year, prev_month)[1]
                df = date(prev_year, prev_month, 1)
                dt = date(prev_year, prev_month, last_day)
                count = self.env['account.move'].search_count([
                    ('commercial_partner_id', '=', partner.id),
                    ('move_type', 'in', ['out_invoice', 'out_refund']),
                    ('state', '=', 'posted'),
                    ('invoice_date', '>=', df),
                    ('invoice_date', '<=', dt),
                    ('company_id', '=', COMPANY_OPERATIVA),
                ])
                if count == 0:
                    _logger.info(
                        f'[CRON Reporte Mensual] {partner.name}: sin facturas, salteo'
                    )
                    skipped.append(partner.name)
                    continue

                # Crear + generar + enviar
                reporte = self.create({
                    'partner_id': partner.id,
                    'period_year': prev_year,
                    'period_month': prev_month,
                })
                reporte._do_generate()
                reporte._do_send_email()
                success.append(partner.name)
                _logger.info(f'[CRON Reporte Mensual] {partner.name}: OK')

            except Exception as e:
                _logger.error(
                    f'[CRON Reporte Mensual] Error en {partner.name}: {e}'
                )
                failed.append((partner.name, str(e)))

        _logger.info(
            f'[CRON Reporte Mensual] FINALIZADO. '
            f'OK: {len(success)} · Fallidos: {len(failed)} · Salteados: {len(skipped)}'
        )

    # ============================================================
    # HELPERS PARA QWEB TEMPLATE
    # ============================================================
    def get_trend_data(self):
        """Devuelve los datos de tendencia parseados (para QWeb)."""
        self.ensure_one()
        if not self.trend_data:
            return []
        try:
            return json.loads(self.trend_data)
        except (ValueError, TypeError):
            return []

    def get_mes_nombre(self):
        self.ensure_one()
        return MESES_ES.get(self.period_month, '')

    def get_donut_gradient_css(self):
        """[DEPRECATED desde v1.0.4] Devuelve el conic-gradient (no soportado por wkhtmltopdf).
        Mantengo el método por si en el futuro se usa otro motor PDF.
        Para el reporte se usa get_donut_svg() que sí es compatible con wkhtmltopdf.
        """
        self.ensure_one()
        liq = self.cat_liquidos_pct or 0
        pap = self.cat_papeles_pct or 0
        bol = self.cat_bolsas_pct or 0
        acc = self.cat_accesorios_pct or 0
        e1 = liq
        e2 = e1 + pap
        e3 = e2 + bol
        e4 = e3 + acc
        return (
            'background: conic-gradient('
            f'#ee7b1f 0% {e1:.2f}%,'
            f'#d86b0f {e1:.2f}% {e2:.2f}%,'
            f'#1a1a1a {e2:.2f}% {e3:.2f}%,'
            f'#7a7a7a {e3:.2f}% {e4:.2f}%,'
            f'#bababa {e4:.2f}% 100%'
            ')'
        )

    def get_donut_svg(self):
        """Devuelve un SVG inline del donut con 5 segmentos (Markup safe).

        Usado por el template QWeb (compatible con wkhtmltopdf, que NO soporta
        conic-gradient ni CSS Grid). Los segmentos se calculan con paths
        trigonométricos. Se wrappea con Markup() para que QWeb no escape el HTML.
        """
        self.ensure_one()
        svg = _build_donut_svg(
            liq_pct=self.cat_liquidos_pct or 0,
            pap_pct=self.cat_papeles_pct or 0,
            bol_pct=self.cat_bolsas_pct or 0,
            acc_pct=self.cat_accesorios_pct or 0,
            var_pct=self.cat_varios_pct or 0,
            cm_pct=self.cat_consumo_masivo_pct or 0,
        )
        return Markup(svg)


class QuimicaCristalReporteMensualSucursal(models.Model):
    _name = 'quimica.cristal.reporte.mensual.sucursal'
    _description = 'Sucursal del reporte mensual'
    _order = 'amount_total desc'

    reporte_id = fields.Many2one(
        'quimica.cristal.reporte.mensual', string='Reporte',
        required=True, ondelete='cascade',
    )
    partner_shipping_id = fields.Many2one(
        'res.partner', string='Dirección de envío', required=True,
    )
    name = fields.Char(related='partner_shipping_id.name', store=True)
    direccion = fields.Char(compute='_compute_direccion')

    amount_total = fields.Monetary(currency_field='currency_id')
    pedidos = fields.Integer()
    notas_credito = fields.Integer()
    productos_distintos = fields.Integer()
    ticket_promedio = fields.Monetary(currency_field='currency_id')
    pct_total = fields.Float(string='% del consolidado', digits=(5, 2))
    vs_anterior_pct = fields.Float(digits=(5, 2))

    # Categorías
    cat_liquidos = fields.Monetary(currency_field='currency_id')
    cat_papeles = fields.Monetary(currency_field='currency_id')
    cat_bolsas = fields.Monetary(currency_field='currency_id')
    cat_accesorios = fields.Monetary(currency_field='currency_id')
    cat_varios = fields.Monetary(currency_field='currency_id')
    cat_consumo_masivo = fields.Monetary(currency_field='currency_id')

    cat_liquidos_pct = fields.Float(digits=(5, 2))
    cat_papeles_pct = fields.Float(digits=(5, 2))
    cat_bolsas_pct = fields.Float(digits=(5, 2))
    cat_accesorios_pct = fields.Float(digits=(5, 2))
    cat_varios_pct = fields.Float(digits=(5, 2))
    cat_consumo_masivo_pct = fields.Float(digits=(5, 2))

    trend_data = fields.Text()

    line_ids = fields.One2many(
        'quimica.cristal.reporte.mensual.line', 'sucursal_id',
        string='Productos',
    )

    observation = fields.Text(
        string='Observación sucursal (opcional manual)',
    )

    currency_id = fields.Many2one(
        'res.currency', related='reporte_id.currency_id', store=True,
    )

    def _compute_direccion(self):
        for rec in self:
            p = rec.partner_shipping_id
            parts = [p.street, p.city]
            rec.direccion = ' · '.join(filter(None, parts))

    def get_trend_data(self):
        self.ensure_one()
        if not self.trend_data:
            return []
        try:
            return json.loads(self.trend_data)
        except (ValueError, TypeError):
            return []

    def get_donut_gradient_css(self):
        """[DEPRECATED] Ver doc en el modelo principal."""
        self.ensure_one()
        liq = self.cat_liquidos_pct or 0
        pap = self.cat_papeles_pct or 0
        bol = self.cat_bolsas_pct or 0
        acc = self.cat_accesorios_pct or 0
        e1 = liq
        e2 = e1 + pap
        e3 = e2 + bol
        e4 = e3 + acc
        return (
            'background: conic-gradient('
            f'#ee7b1f 0% {e1:.2f}%,'
            f'#d86b0f {e1:.2f}% {e2:.2f}%,'
            f'#1a1a1a {e2:.2f}% {e3:.2f}%,'
            f'#7a7a7a {e3:.2f}% {e4:.2f}%,'
            f'#bababa {e4:.2f}% 100%'
            ')'
        )

    def get_donut_svg(self):
        """SVG inline del donut (compatible wkhtmltopdf). Ver modelo principal."""
        self.ensure_one()
        svg = _build_donut_svg(
            liq_pct=self.cat_liquidos_pct or 0,
            pap_pct=self.cat_papeles_pct or 0,
            bol_pct=self.cat_bolsas_pct or 0,
            acc_pct=self.cat_accesorios_pct or 0,
            var_pct=self.cat_varios_pct or 0,
            cm_pct=self.cat_consumo_masivo_pct or 0,
        )
        return Markup(svg)


class QuimicaCristalReporteMensualLine(models.Model):
    _name = 'quimica.cristal.reporte.mensual.line'
    _description = 'Línea de producto del reporte mensual'
    _order = 'amount_total desc'

    reporte_id = fields.Many2one(
        'quimica.cristal.reporte.mensual', ondelete='cascade',
    )
    sucursal_id = fields.Many2one(
        'quimica.cristal.reporte.mensual.sucursal', ondelete='cascade',
    )
    product_id = fields.Many2one('product.product', string='Producto')
    product_default_code = fields.Char(string='SKU')
    product_name = fields.Char(string='Producto')

    categoria = fields.Selection([
        ('liquidos', 'Líquidos'),
        ('papeles', 'Papeles'),
        ('bolsas', 'Bolsas'),
        ('accesorios', 'Accesorios'),
        ('varios', 'Varios'),
        ('consumo_masivo', 'Consumo Masivo'),
    ], string='Categoría')

    quantity = fields.Float(string='Cantidad', digits=(12, 2))
    amount_total = fields.Monetary(
        string='Total c/IVA',
        currency_field='currency_id',
        help='Total con IVA, NC ya restada',
    )
    pct_mes = fields.Float(string='% del mes', digits=(5, 2))

    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id', store=True,
    )

    def _compute_currency_id(self):
        for rec in self:
            if rec.reporte_id:
                rec.currency_id = rec.reporte_id.currency_id
            elif rec.sucursal_id:
                rec.currency_id = rec.sucursal_id.currency_id
            else:
                rec.currency_id = self.env.company.currency_id

    def get_categoria_label(self):
        self.ensure_one()
        return CATEGORIAS_LABELS.get(self.categoria, 'Varios')
