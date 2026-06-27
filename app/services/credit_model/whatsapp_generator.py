"""Mensaje WhatsApp de enrolamiento."""

from __future__ import annotations

from typing import Any

from app.services.credit_model.constants import LINK_ONBOARDING
from app.services.credit_model.helpers import primer_nombre


def generar_mensaje(b: dict[str, Any]) -> str:
    c = b["cliente"]
    don = primer_nombre(c.get("RazonSocial", ""))
    vends = b["sql"]["vendedores"]
    v1 = vends[0] if vends else None
    nombre_vend = primer_nombre(v1["nombre"]) if v1 else "tu vendedor"
    dia = v1["dia_visita"] if v1 else "la semana"
    return (
        "Buenas Don %s! \U0001F44B Le escribe %s, de DIMAX.\n\n"
        "Le tengo una novedad para su bodega: ahora puede hacer sus pedidos "
        "por WhatsApp con Circa. Ve el catalogo completo, arma su pedido "
        "cuando quiera y lo recibe igual que siempre - sin tener que esperar "
        "a mi visita del %s.\n\n"
        "Y por su buen historial como cliente, ya le tenemos una linea de "
        "credito pre-aprobada \U0001F64C Para que pueda surtir su bodega y "
        "pagar con calma.\n\n"
        "Activarla le toma 2 minutos. Solo abra este enlace y envie el "
        "mensaje que le aparece:\n\U0001F449 %s\n\n"
        "Cualquier duda me avisa. Saludos!"
        % (don, nombre_vend, dia, LINK_ONBOARDING)
    )
