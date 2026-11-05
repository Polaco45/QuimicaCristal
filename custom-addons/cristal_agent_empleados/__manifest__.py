{
    "name": "Cristal Agent · Asistente de empleados",
    "summary": "Claudio contesta en el chatter las consultas de los empleados sobre sus actividades y escala a Sergio lo que no sabe",
    "description": """
Química Cristal — modo «asistente de empleados» del Cristal Agent (pedido de Sergio, 05/11/2026).

* Cuando un empleado (Guillermo, Adrián…) escribe en el chatter de un registro donde tiene
  una actividad abierta, Claudio le contesta ahí mismo con el contexto de la actividad.
* Horario: lunes a sábado de 8 a 13 y de 17 a 20 (Córdoba); fuera de horario la pregunta
  espera a la próxima apertura.
* Lo que no sabe o necesita decisión de Sergio se lo pasa por actividad + WhatsApp, y cuando
  Sergio contesta le reenvía la respuesta al empleado.
* Solo herramientas de lectura, agendar y cerrar la actividad propia: nunca le escribe a un
  cliente ni toca pedidos.

Va aparte de cristal_agent: usa su motor (ClaudeClient, herramientas, corridas y tope diario)
pero el bot de ventas no ve este modo ni la herramienta escalate_to_sergio.
""",
    "version": "18.0.1.0.0",
    "author": "Química Cristal",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": ["cristal_agent", "mail", "mrp", "stock", "sale"],
    "data": [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "views/employee_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
}
