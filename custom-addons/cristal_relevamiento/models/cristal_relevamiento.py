# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CristalRelevamientoOpcion(models.Model):
    """Catálogo de opciones para los campos multi-selección del relevamiento.
    Un solo modelo con 'tipo' para no crear un modelo por dimensión."""
    _name = 'cristal.relevamiento.opcion'
    _description = 'Cristal Relevamiento — Opción de catálogo'
    _order = 'tipo, sequence, name'

    name = fields.Char(string='Nombre', required=True)
    tipo = fields.Selection([
        ('sector', 'Sector'),
        ('piso', 'Piso'),
        ('superficie', 'Superficie'),
        ('dispenser', 'Dispenser'),
        ('equipo', 'Equipo'),
        ('herramienta', 'Herramienta'),
        ('falencia', 'Falencia'),
        ('mejora', 'Mejora del proveedor'),
        ('valora', 'Qué valora'),
        ('forma_pago', 'Forma de pago'),
    ], string='Tipo', required=True, index=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activa', default=True)


class CristalRelevamiento(models.Model):
    _name = 'cristal.relevamiento'
    _description = 'Cristal — Relevamiento Plan Control'
    _order = 'fecha_relevamiento desc, id desc'

    name = fields.Char(string='Referencia', compute='_compute_name', store=True)
    partner_id = fields.Many2one(
        'res.partner', string='Cliente', required=True, index=True,
        ondelete='cascade')
    lead_id = fields.Many2one(
        'crm.lead', string='Lead de origen', index=True, ondelete='set null')
    fecha_relevamiento = fields.Date(
        string='Fecha del relevamiento', default=fields.Date.context_today)
    operador_id = fields.Many2one(
        'res.users', string='Operador del relevamiento',
        default=lambda self: self.env.user)
    state = fields.Selection([
        ('borrador', 'Borrador'),
        ('completado', 'Completado'),
    ], string='Estado', default='borrador')
    es_remedicion = fields.Boolean(
        string='Es re-medición (3 meses)',
        help='Marcar si este relevamiento es el control posterior para comparar mejora.')
    relevamiento_origen_id = fields.Many2one(
        'cristal.relevamiento', string='Relevamiento inicial',
        help='Foto inicial contra la que se compara esta re-medición.')

    # --- Identificación / cliente ---
    nombre_fantasia = fields.Char(string='Nombre de fantasía')
    rubro_ids = fields.Many2many(
        'res.partner.category', relation='cristal_relevamiento_rubro_rel',
        column1='relevamiento_id', column2='category_id', string='Rubros',
        domain="[('parent_id.name', '=', 'Rubros')]",
        help='Se sincroniza con las etiquetas de rubro de la ficha del cliente.')
    canal_source_id = fields.Many2one(
        related='lead_id.source_id', string='Canal de entrada', readonly=True)

    # --- Infraestructura ---
    superficie_total = fields.Selection([
        ('lt100', '<100 m²'), ('100_300', '100–300 m²'), ('300_800', '300–800 m²'),
        ('800_2000', '800–2.000 m²'), ('gt2000', '2.000+ m²')], string='Superficie total')
    cantidad_banos = fields.Selection([
        ('1', '1'), ('2', '2'), ('3_5', '3–5'), ('6plus', '6+')], string='Cantidad de baños')
    personal_total = fields.Selection([
        ('1_5', '1–5'), ('6_15', '6–15'), ('16_50', '16–50'), ('50plus', '50+')],
        string='Personal total aprox.')
    circulacion_dia = fields.Selection([
        ('lt50', '<50'), ('50_200', '50–200'), ('200_500', '200–500'), ('500plus', '500+')],
        string='Personas que circulan/día')
    dias_uso_semana = fields.Selection([
        ('1_5', '1–5'), ('6', '6'), ('7', '7')], string='Días de uso por semana')
    horario_operacion = fields.Selection([
        ('manana', 'Mañana'), ('tarde', 'Tarde'), ('completo', 'Completo'),
        ('24hs', '24 hs'), ('turnos', 'Turnos')], string='Horario de operación')
    frecuencia_limpieza = fields.Selection([
        ('varias_dia', 'Varias veces/día'), ('diaria', 'Diaria'),
        ('alternos', 'Días alternos'), ('semanal', 'Semanal')], string='Frecuencia de limpieza')
    sector_ids = fields.Many2many(
        'cristal.relevamiento.opcion', relation='cristal_relevamiento_sector_rel',
        column1='relevamiento_id', column2='opcion_id', string='Sectores presentes',
        domain="[('tipo', '=', 'sector')]")
    piso_ids = fields.Many2many(
        'cristal.relevamiento.opcion', relation='cristal_relevamiento_piso_rel',
        column1='relevamiento_id', column2='opcion_id', string='Pisos dominantes',
        domain="[('tipo', '=', 'piso')]")
    superficie_dom_ids = fields.Many2many(
        'cristal.relevamiento.opcion', relation='cristal_relevamiento_superf_rel',
        column1='relevamiento_id', column2='opcion_id', string='Superficies dominantes',
        domain="[('tipo', '=', 'superficie')]")

    # --- Personal de limpieza actual ---
    personal_cantidad = fields.Selection([
        ('0', '0'), ('1', '1'), ('2_3', '2–3'), ('4plus', '4+')],
        string='Cantidad de personal de limpieza')
    personal_relacion = fields.Selection([
        ('propias', 'Propias'), ('tercerizadas', 'Tercerizadas'), ('mixto', 'Mixto')],
        string='Relación laboral')
    encargado_interno = fields.Boolean(string='Tiene encargado de limpieza interno')
    capacitacion_previa = fields.Selection([
        ('si', 'Sí'), ('no', 'No'), ('parcial', 'Parcial')], string='Recibió capacitación')

    # --- Insumos / equipamiento / herramientas ---
    producto_ids = fields.One2many(
        'cristal.relevamiento.producto', 'relevamiento_id', string='Productos que usa hoy')
    calidad_general = fields.Selection([
        ('estandar', 'Estándar'), ('premium', 'Premium')],
        string='Calidad que usa (general)')
    dispenser_ids = fields.Many2many(
        'cristal.relevamiento.opcion', relation='cristal_relevamiento_dispenser_rel',
        column1='relevamiento_id', column2='opcion_id', string='Dispensers instalados',
        domain="[('tipo', '=', 'dispenser')]")
    equipo_ids = fields.Many2many(
        'cristal.relevamiento.opcion', relation='cristal_relevamiento_equipo_rel',
        column1='relevamiento_id', column2='opcion_id', string='Equipamiento (máquinas)',
        domain="[('tipo', '=', 'equipo')]")
    herramienta_ids = fields.Many2many(
        'cristal.relevamiento.opcion', relation='cristal_relevamiento_herram_rel',
        column1='relevamiento_id', column2='opcion_id', string='Herramientas de trabajo',
        domain="[('tipo', '=', 'herramienta')]")

    # --- Proveedor y situación comercial ---
    tiene_proveedor = fields.Boolean(string='Trabaja con un proveedor en particular')
    proveedor_actual = fields.Char(string='Proveedor actual')
    proveedor_antiguedad = fields.Selection([
        ('lt6m', '<6 meses'), ('6_12m', '6–12 meses'),
        ('1_3a', '1–3 años'), ('3plus', '3+ años')], string='Hace cuánto trabaja con él')
    quien_compra = fields.Selection([
        ('dueno', 'Dueño/a'), ('encargado', 'Encargado/a'), ('admin', 'Administración'),
        ('compras', 'Compras'), ('otro', 'Otro')], string='Quién realiza la compra')
    frecuencia_compra = fields.Selection([
        ('semanal', 'Semanal'), ('quincenal', 'Quincenal'), ('mensual', 'Mensual'),
        ('cuando_acaba', 'Cuando se acaba')], string='Frecuencia de compra')
    responsable_compras = fields.Char(string='Responsable de compras (nombre)')
    responsable_contacto = fields.Char(string='Contacto del responsable (tel/WhatsApp)')
    presupuesto_estimado_mensual_actual = fields.Selection([
        ('lt50k', '<$50k'), ('50_150k', '$50–150k'),
        ('150_400k', '$150–400k'), ('400kplus', '$400k+')],
        string='Presupuesto estimado mensual actual')
    forma_pago_ids = fields.Many2many(
        'cristal.relevamiento.opcion', relation='cristal_relevamiento_pago_rel',
        column1='relevamiento_id', column2='opcion_id', string='Forma de pago habitual',
        domain="[('tipo', '=', 'forma_pago')]")
    plazo_pago = fields.Selection([
        ('contado', 'Contado'), ('15d', '15 días'), ('30d', '30 días'), ('otro', 'Otro')],
        string='Plazo de pago habitual')

    # --- Falencias, expectativas y prioridades ---
    falencia_ids = fields.Many2many(
        'cristal.relevamiento.opcion', relation='cristal_relevamiento_falencia_rel',
        column1='relevamiento_id', column2='opcion_id', string='Falencias de la situación actual',
        domain="[('tipo', '=', 'falencia')]")
    mejora_ids = fields.Many2many(
        'cristal.relevamiento.opcion', relation='cristal_relevamiento_mejora_rel',
        column1='relevamiento_id', column2='opcion_id', string='Qué mejoraría del proveedor',
        domain="[('tipo', '=', 'mejora')]")
    valora_ids = fields.Many2many(
        'cristal.relevamiento.opcion', relation='cristal_relevamiento_valora_rel',
        column1='relevamiento_id', column2='opcion_id', string='Qué valora al elegir proveedor',
        domain="[('tipo', '=', 'valora')]")
    prioridad_1 = fields.Selection([
        ('gasto', 'Bajar el gasto'), ('calidad', 'Mejor calidad'), ('entrega', 'Entrega rápida'),
        ('financiacion', 'Financiación'), ('asesoramiento', 'Asesoramiento'),
        ('stock', 'Stock asegurado')], string='Prioridad #1 a resolver')
    conformidad_proveedor = fields.Selection([
        ('1', '1 Muy mala'), ('2', '2'), ('3', '3'), ('4', '4'), ('5', '5 Excelente')],
        string='Conformidad con proveedor actual')

    # --- Muestras ---
    muestra_entregada = fields.Boolean(string='Se dejaron muestras')
    muestra_ids = fields.One2many(
        'cristal.relevamiento.muestra', 'relevamiento_id', string='Muestras entregadas')

    # --- Cierre con el cliente (checklist de lo comunicado) ---
    com_propuesta = fields.Boolean(string='Propuesta a medida en 48 hs hábiles')
    com_reporte = fields.Boolean(string='Reporte mensual de consumo (Plan Control)')
    com_revision = fields.Boolean(string='Revisión trimestral del servicio')
    com_entrega = fields.Boolean(string='Entrega < 24 hs hábiles (RC y Las Higueras)')
    com_descuento = fields.Boolean(string='20% OFF primera compra (válido 15 días)')
    com_lista = fields.Boolean(string='Lista institucional Premium / Estándar')

    # --- Diagnóstico por sector (interno, solo vendedor) ---
    sector_diag_ids = fields.One2many(
        'cristal.relevamiento.sector', 'relevamiento_id',
        string='Diagnóstico por sector (interno)')
    promedio_limpieza = fields.Float(
        string='Promedio limpieza inicial', compute='_compute_promedio', store=True)
    observacion_general = fields.Text(string='Observación general (interna)')

    @api.depends('partner_id', 'fecha_relevamiento')
    def _compute_name(self):
        for rec in self:
            fecha = rec.fecha_relevamiento or ''
            partner = rec.partner_id.display_name or 'Nuevo'
            rec.name = 'Relevamiento — %s — %s' % (partner, fecha)

    @api.depends('sector_diag_ids.puntaje')
    def _compute_promedio(self):
        for rec in self:
            puntajes = [int(s.puntaje) for s in rec.sector_diag_ids if s.puntaje]
            rec.promedio_limpieza = (sum(puntajes) / len(puntajes)) if puntajes else 0.0

    # --- Sincronización de rubros con la ficha del cliente ---
    def _all_rubro_cats(self):
        parent = self.env['res.partner.category'].search(
            [('name', '=', 'Rubros'), ('parent_id', '=', False)], limit=1)
        if not parent:
            return self.env['res.partner.category']
        return self.env['res.partner.category'].search([('parent_id', '=', parent.id)])

    def _sync_rubros(self):
        rubro_all = self._all_rubro_cats()
        for rec in self:
            if not rec.partner_id:
                continue
            no_rubro = rec.partner_id.category_id - rubro_all
            rec.partner_id.category_id = no_rubro + rec.rubro_ids

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            rubro_all = self._all_rubro_cats()
            self.rubro_ids = self.partner_id.category_id & rubro_all

    @api.model_create_multi
    def create(self, vals_list):
        rubro_all = self._all_rubro_cats()
        for vals in vals_list:
            # Sembrar rubros del cliente si no vienen, para que el sync no los borre
            if vals.get('partner_id') and not vals.get('rubro_ids'):
                partner = self.env['res.partner'].browse(vals['partner_id'])
                seed = partner.category_id & rubro_all
                if seed:
                    vals['rubro_ids'] = [(6, 0, seed.ids)]
        records = super().create(vals_list)
        records._sync_rubros()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'rubro_ids' in vals or 'partner_id' in vals:
            self._sync_rubros()
        return res


class CristalRelevamientoProducto(models.Model):
    _name = 'cristal.relevamiento.producto'
    _description = 'Cristal Relevamiento — Producto que usa'
    _order = 'relevamiento_id, id'

    relevamiento_id = fields.Many2one(
        'cristal.relevamiento', required=True, ondelete='cascade')
    categoria = fields.Selection([
        ('deterg', 'Detergente / Desengrasante'),
        ('lavand', 'Lavandina / Desinfectante'),
        ('papel', 'Papel / Bobinas'),
        ('bolsas', 'Bolsas de residuos'),
        ('manos', 'Jabón / Alcohol manos'),
        ('aero', 'Aerosoles / Ambiente'),
        ('insect', 'Insecticidas'),
        ('ceras', 'Ceras / Pisos'),
        ('pileta', 'Químico pileta'),
    ], string='Categoría', required=True)
    marca = fields.Char(string='Marca / referencia')
    volumen_mes = fields.Char(string='Lts-kg / mes')


class CristalRelevamientoMuestra(models.Model):
    _name = 'cristal.relevamiento.muestra'
    _description = 'Cristal Relevamiento — Muestra entregada'
    _order = 'relevamiento_id, id'

    relevamiento_id = fields.Many2one(
        'cristal.relevamiento', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Producto')
    producto_texto = fields.Char(string='Producto (si no está en catálogo)')
    presentacion = fields.Char(string='Presentación')
    cantidad = fields.Float(string='Cantidad', default=1.0)


class CristalRelevamientoSector(models.Model):
    _name = 'cristal.relevamiento.sector'
    _description = 'Cristal Relevamiento — Diagnóstico por sector'
    _order = 'relevamiento_id, id'

    relevamiento_id = fields.Many2one(
        'cristal.relevamiento', required=True, ondelete='cascade')
    sector_id = fields.Many2one(
        'cristal.relevamiento.opcion', string='Sector',
        domain="[('tipo', '=', 'sector')]")
    puntaje = fields.Selection([
        ('1', '1'), ('2', '2'), ('3', '3'), ('4', '4'), ('5', '5')],
        string='Estado (1-5)')
    observaciones = fields.Char(string='Observaciones')
