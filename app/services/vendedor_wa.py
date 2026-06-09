"""
Flujo WhatsApp para vendedores de campo.

El vendedor opera desde su teléfono (vendedores.telefono_whatsapp):
  1. Busca bodega (DNI/RUC o cartera)
  2. Recibe link al catálogo web (modo preventa + vt)
  3. Tras armar el pedido en web, escribe AVISAR → Circa notifica al bodeguero

No reemplaza la app web /v/{token}; la complementa para quien prefiere WA.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from app.services import db

CIRCA_WA_NUMBER = os.getenv("CIRCA_WA_NUMBER", "51986311567").lstrip("+")

_VEND_MENU_CMDS = frozenset({
    "MENU", "INICIO", "HOLA", "HI", "VENDEDOR", "VEND",
})
_VEND_PREVENTA_CMDS = frozenset({"1", "PREVENTA", "NUEVA", "NUEVA PREVENTA", "PEDIDO"})
_VEND_LISTA_CMDS = frozenset({"2", "MIS PREVENTAS", "MIS PEDIDOS", "PREVENTAS", "PEDIDOS"})
_VEND_CARTERA_CMDS = frozenset({"3", "BODEGAS", "CARTERA", "CLIENTES"})
_VEND_AYUDA_CMDS = frozenset({"4", "AYUDA", "HELP"})
_VEND_BODEGA_CMDS = frozenset({"2", "BODEGA", "CLIENTE", "SOY BODEGA"})
_LINK_TOKEN_RE = re.compile(r"\b([a-f0-9]{12})\b", re.IGNORECASE)


def _app_base_url() -> str:
    return os.getenv("APP_BASE_URL", "https://circa-production-c517.up.railway.app").rstrip("/")


def _primer_nombre(nombre: str) -> str:
    tokens = (nombre or "").strip().split()
    if len(tokens) >= 3:
        return tokens[2].capitalize()
    return tokens[-1].capitalize() if tokens else "Vendedor"


def _parse_session_datos(session: dict | None) -> dict[str, Any]:
    if not session:
        return {}
    raw = session.get("datos")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _catalog_url_vendedor(access_token: str, bodega_id: str) -> str:
    return f"{_app_base_url()}/static/catalogo_v2.html?b={bodega_id}&t=preventa&vt={access_token}&fresh=1"


def _wa_pedido_link(link_token: str) -> str:
    return f"https://wa.me/{CIRCA_WA_NUMBER}?text=Pedido%20{link_token}"


def should_route_to_vendedor(
    vendedor: dict | None,
    bodega: dict | None,
    session: dict | None,
) -> bool:
    """True si el mensaje debe ir al flujo vendedor (sin chooser dual)."""
    if not vendedor or not vendedor.get("activo"):
        return False
    fase = (session or {}).get("fase") or ""
    if fase.startswith("vend_"):
        return True
    if session and fase and not fase.startswith("vend_") and bodega:
        return False
    if vendedor and bodega:
        return False
    return True


def should_show_actor_chooser(vendedor: dict | None, bodega: dict | None, session: dict | None) -> bool:
    if not vendedor or not bodega:
        return False
    if session:
        return False
    return True


def actor_chooser_responses() -> list:
    return [
        "👤 Este número está registrado como *vendedor* y como *bodega*.\n\n"
        "¿Cómo quieres entrar?\n"
        "• Escribe *1* o *VENDEDOR* — modo vendedor de campo\n"
        "• Escribe *2* o *BODEGA* — modo bodeguero (cliente)"
    ]


def _vend_menu_text(vendedor: dict) -> str:
    nombre = _primer_nombre(vendedor.get("nombre") or "")
    codigo = vendedor.get("codigo") or ""
    return (
        f"🧑‍💼 *Hola {nombre}* · código {codigo}\n\n"
        "¿Qué quieres hacer?\n"
        "• *1* — Nueva preventa (buscar bodega)\n"
        "• *2* — Mis preventas recientes\n"
        "• *3* — Ver mi cartera de bodegas\n"
        "• *4* — Ayuda\n\n"
        "También puedes enviar directo el *DNI* o *RUC* de una bodega."
    )


def _buscar_bodega(vendedor: dict, q: str) -> tuple[dict | None, str | None]:
    q_clean = "".join(c for c in q if c.isdigit())
    if len(q_clean) not in (8, 11):
        return None, "Envía un DNI (8 dígitos) o RUC (11 dígitos)."

    select_fields = (
        "id,razon_social,nombre_comercial,distrito,ruc,dni_representante,"
        "linea_aprobada,linea_disponible,distribuidor_id,estado,telefono_whatsapp"
    )
    if len(q_clean) == 8:
        rows = (
            db.sb.table("bodegas")
            .select(select_fields)
            .eq("dni_representante", q_clean)
            .limit(1)
            .execute()
            .data
        )
    else:
        rows = (
            db.sb.table("bodegas")
            .select(select_fields)
            .eq("ruc", q_clean)
            .limit(1)
            .execute()
            .data
        )
    if not rows:
        tipo = "DNI" if len(q_clean) == 8 else "RUC"
        return None, f"No encontramos una bodega con ese {tipo}."

    bodega = rows[0]
    if not vendedor.get("es_admin"):
        cartera = (
            db.sb.table("bodega_vendedores")
            .select("id")
            .eq("vendedor_id", vendedor["id"])
            .eq("bodega_id", bodega["id"])
            .eq("activo", True)
            .limit(1)
            .execute()
            .data
        )
        if not cartera:
            return None, "Esa bodega no está en tu cartera. Pide al admin que te la asigne."

    estado = (bodega.get("estado") or "").lower()
    if estado in ("rechazada", "suspendida", "bloqueada"):
        return None, f"La bodega está {estado} y no puede recibir preventas."

    if bodega.get("distribuidor_id") != vendedor.get("distribuidor_id") and not vendedor.get("es_admin"):
        return None, "La bodega pertenece a otro distribuidor."

    return bodega, None


def _list_cartera(vendedor: dict, limit: int = 8) -> list[dict]:
    if vendedor.get("es_admin"):
        rows = (
            db.sb.table("bodegas")
            .select("id,nombre_comercial,razon_social,distrito,linea_disponible,estado")
            .eq("distribuidor_id", vendedor["distribuidor_id"])
            .in_("estado", ["activo", "preaprobada"])
            .order("nombre_comercial")
            .limit(limit)
            .execute()
            .data
        )
        return rows or []

    rows = (
        db.sb.table("bodega_vendedores")
        .select("bodegas(id,nombre_comercial,razon_social,distrito,linea_disponible,estado)")
        .eq("vendedor_id", vendedor["id"])
        .eq("activo", True)
        .limit(limit)
        .execute()
        .data
    )
    out = []
    for row in rows or []:
        b = row.get("bodegas")
        if b:
            out.append(b)
    return out


def _list_preventas_vendedor(vendedor_id: str, limit: int = 5) -> list[dict]:
    rows = (
        db.sb.table("pedidos")
        .select("id,numero,estado,link_token,total_pedido,created_at,bodega_id,bodegas(nombre_comercial,razon_social)")
        .eq("vendedor_id", vendedor_id)
        .eq("tipo_operacion", "preventa")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )
    return rows or []


def _bodega_seleccionada_responses(telefono: str, vendedor: dict, bodega: dict) -> list:
    nombre = bodega.get("nombre_comercial") or bodega.get("razon_social") or "Bodega"
    linea = float(bodega.get("linea_disponible") or 0)
    token = vendedor.get("access_token") or ""
    cat_url = _catalog_url_vendedor(token, bodega["id"]) if token else ""

    db.upsert_session(
        telefono,
        "vend_preventa_bodega",
        {
            "vendedor_id": vendedor["id"],
            "bodega_id": bodega["id"],
            "bodega_nombre": nombre,
        },
        None,
    )

    warn = ""
    if linea <= 0:
        warn = "\n⚠️ Sin línea disponible: el cliente podría pagar todo en efectivo a ti."

    parts = [
        f"✅ *{nombre}*\n"
        f"📍 {bodega.get('distrito') or '—'}\n"
        f"💳 Línea disponible: *S/ {linea:.2f}*{warn}\n\n"
        f"👉 Arma el pedido aquí:\n{cat_url}\n\n"
        "Cuando termines en el catálogo, escribe *AVISAR* y le mandamos el link de aprobación al cliente por WhatsApp.\n"
        "También: *MENU* para volver."
    ]
    return parts


def _avisar_bodeguero(vendedor: dict, datos: dict, body_raw: str) -> list:
    bodega_id = datos.get("bodega_id")
    link_token = None
    m = _LINK_TOKEN_RE.search(body_raw or "")
    if m:
        link_token = m.group(1).lower()

    q = (
        db.sb.table("pedidos")
        .select("id,link_token,total_pedido,estado,bodega_id")
        .eq("vendedor_id", vendedor["id"])
        .eq("tipo_operacion", "preventa")
        .eq("estado", "preventa_confirmada")
    )
    if link_token:
        q = q.eq("link_token", link_token)
    elif bodega_id:
        q = q.eq("bodega_id", bodega_id)
    pedidos = q.order("created_at", desc=True).limit(1).execute().data

    if not pedidos:
        return [
            "No hay preventa pendiente de avisar.\n\n"
            "Primero arma el pedido en el catálogo y luego escribe *AVISAR*."
        ]

    pedido = pedidos[0]
    if pedido.get("estado") != "preventa_confirmada":
        return ["Esa preventa ya fue procesada (estado: %s)." % pedido.get("estado")]

    bodega_rows = (
        db.sb.table("bodegas")
        .select("id,nombre_comercial,razon_social,telefono_whatsapp")
        .eq("id", pedido["bodega_id"])
        .limit(1)
        .execute()
        .data
    )
    if not bodega_rows:
        return ["No encontramos la bodega del pedido."]
    bodega = bodega_rows[0]
    tel_bg = bodega.get("telefono_whatsapp")
    if not tel_bg:
        return ["La bodega no tiene WhatsApp registrado. Actualízalo en backoffice."]

    lt = pedido.get("link_token") or ""
    total = float(pedido.get("total_pedido") or 0)
    vnombre = _primer_nombre(vendedor.get("nombre") or "")
    bnombre = bodega.get("nombre_comercial") or bodega.get("razon_social") or "tu negocio"

    msg_bodeguero = (
        f"🛒 *Hola! {vnombre} armó una preventa para {bnombre}*\n\n"
        f"Total: *S/ {total:.2f}*\n\n"
        f"Para revisar y aprobar, escribe:\n*Pedido {lt}*\n\n"
        f"O abre: {_wa_pedido_link(lt)}"
    )

    return [
        {
            "signal": "VEND_NOTIFY_BODEGA",
            "to": tel_bg,
            "body": msg_bodeguero,
        },
        f"✅ Le avisamos a *{bnombre}* por WhatsApp.\n\n"
        f"Código del pedido: `{lt}`\n"
        "Cuando el cliente apruebe, lo verás en *2 — Mis preventas*.",
    ]


def handle_vendedor_message(
    telefono: str,
    body_raw: str,
    body_n: str,
    vendedor: dict,
    session: dict | None,
    *,
    force_entry: bool = False,
) -> list:
    datos = _parse_session_datos(session)
    fase = (session or {}).get("fase") or ""

    if body_n in _VEND_MENU_CMDS or force_entry:
        db.upsert_session(telefono, "vend_menu", {"vendedor_id": vendedor["id"]}, None)
        return [_vend_menu_text(vendedor)]

    if not fase.startswith("vend_"):
        db.upsert_session(telefono, "vend_menu", {"vendedor_id": vendedor["id"]}, None)
        fase = "vend_menu"

    # DNI/RUC directo desde menú
    digits = "".join(c for c in body_raw if c.isdigit())
    if fase == "vend_menu" and len(digits) in (8, 11):
        bodega, err = _buscar_bodega(vendedor, body_raw)
        if err:
            return [f"⚠️ {err}\n\nEscribe *MENU* para ver opciones."]
        return _bodega_seleccionada_responses(telefono, vendedor, bodega)

    if fase == "vend_menu":
        if body_n in _VEND_PREVENTA_CMDS:
            db.upsert_session(telefono, "vend_preventa_buscar", {"vendedor_id": vendedor["id"]}, None)
            return [
                "🔍 *Nueva preventa*\n\n"
                "Envía el *DNI* (8 dígitos) o *RUC* (11 dígitos) de la bodega.\n"
                "O escribe *3* para elegir de tu cartera."
            ]
        if body_n in _VEND_LISTA_CMDS:
            return _mis_preventas_text(vendedor)
        if body_n in _VEND_CARTERA_CMDS:
            return _cartera_text(vendedor)
        if body_n in _VEND_AYUDA_CMDS:
            return [_ayuda_text()]
        return [_vend_menu_text(vendedor)]

    if fase == "vend_preventa_buscar":
        if body_n in _VEND_CARTERA_CMDS:
            return _cartera_text(vendedor, selectable=True, telefono=telefono)
        bodega, err = _buscar_bodega(vendedor, body_raw)
        if err:
            return [f"⚠️ {err}\n\nIntenta otro documento o *MENU*."]
        return _bodega_seleccionada_responses(telefono, vendedor, bodega)

    if fase == "vend_preventa_bodega":
        if body_n in ("AVISAR", "NOTIFICAR", "AVISA", "5"):
            return _avisar_bodeguero(vendedor, datos, body_raw)
        if body_n in ("CATALOGO", "LINK", "CAT"):
            bid = datos.get("bodega_id")
            token = vendedor.get("access_token") or ""
            if bid and token:
                return [f"👉 Catálogo:\n{_catalog_url_vendedor(token, bid)}"]
            return ["No hay bodega seleccionada. Escribe *MENU*."]
        if body_n in _VEND_MENU_CMDS:
            db.upsert_session(telefono, "vend_menu", {"vendedor_id": vendedor["id"]}, None)
            return [_vend_menu_text(vendedor)]
        return [
            "Opciones:\n"
            "• *AVISAR* — notificar al cliente por WhatsApp\n"
            "• *CATALOGO* — reenviar link del catálogo\n"
            "• *MENU* — volver al inicio"
        ]

    if fase == "vend_cartera_pick":
        try:
            idx = int(digits) - 1
            ids = datos.get("cartera_ids") or []
            if 0 <= idx < len(ids):
                rows = (
                    db.sb.table("bodegas")
                    .select("id,razon_social,nombre_comercial,distrito,linea_disponible,estado,telefono_whatsapp")
                    .eq("id", ids[idx])
                    .limit(1)
                    .execute()
                    .data
                )
                if rows:
                    return _bodega_seleccionada_responses(telefono, vendedor, rows[0])
        except ValueError:
            pass
        return ["Escribe el número de la lista (1, 2, …) o *MENU*."]

    db.upsert_session(telefono, "vend_menu", {"vendedor_id": vendedor["id"]}, None)
    return [_vend_menu_text(vendedor)]


def _mis_preventas_text(vendedor: dict) -> list[str]:
    rows = _list_preventas_vendedor(vendedor["id"])
    if not rows:
        return ["📋 Aún no tienes preventas registradas.\n\nEscribe *1* para armar una nueva."]
    lines = ["📋 *Tus preventas recientes:*\n"]
    for i, p in enumerate(rows, 1):
        b = p.get("bodegas") or {}
        bnombre = b.get("nombre_comercial") or b.get("razon_social") or "—"
        total = float(p.get("total_pedido") or 0)
        estado = p.get("estado") or "—"
        lt = p.get("link_token") or ""
        lines.append(f"{i}. {bnombre} · S/ {total:.2f} · {estado}")
        if lt and estado == "preventa_confirmada":
            lines.append(f"   Código: `{lt}`")
    lines.append("\nPara avisar al cliente de la última: *AVISAR* (desde la bodega seleccionada).")
    return ["\n".join(lines)]


def _cartera_text(
    vendedor: dict,
    *,
    selectable: bool = False,
    telefono: str | None = None,
) -> list[str]:
    rows = _list_cartera(vendedor)
    if not rows:
        return ["No tienes bodegas en cartera.\n\nPide al admin que te asigne clientes en backoffice."]
    lines = ["🏪 *Tu cartera:*\n"]
    ids = []
    for i, b in enumerate(rows, 1):
        nombre = b.get("nombre_comercial") or b.get("razon_social") or "—"
        distrito = b.get("distrito") or ""
        linea = float(b.get("linea_disponible") or 0)
        lines.append(f"{i}. {nombre} ({distrito}) · línea S/ {linea:.2f}")
        ids.append(b["id"])
    if selectable and telefono:
        db.upsert_session(
            telefono,
            "vend_cartera_pick",
            {"vendedor_id": vendedor["id"], "cartera_ids": ids},
            None,
        )
        lines.append("\nResponde con el *número* de la bodega para armar su preventa.")
    else:
        lines.append("\nEnvía el DNI/RUC de una bodega o escribe *1* para nueva preventa.")
    return ["\n".join(lines)]


def _ayuda_text() -> str:
    return (
        "ℹ️ *Ayuda vendedor Circa*\n\n"
        "1. Busca la bodega (DNI/RUC o cartera)\n"
        "2. Abre el catálogo que te enviamos\n"
        "3. Confirma el carrito en la web\n"
        "4. Escribe *AVISAR* → el cliente recibe el link en su WhatsApp\n"
        "5. El cliente escribe *Pedido {código}* y aprueba con su PIN\n\n"
        "También puedes usar la app web: /v/{tu_token}\n"
        "Escribe *MENU* para volver."
    )
