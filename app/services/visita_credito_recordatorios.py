"""
Recordatorio de ventas — plantilla Meta circa_recordatorio_visita_credito.

Variables Meta (orden fijo):
  {{1}} nombre · {{2}} aliado · {{3}} vendedor (mismo valor si viene del CSV) · {{4}} monto
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from typing import Any, Optional

from app.services import db

logger = logging.getLogger("circa.visita_credito_recordatorios")

DEFAULT_TEMPLATE_CONFIG: dict[str, Any] = {
    "template_name": "circa_recordatorio_visita_credito",
    "language": "es_MX",
    "variable_keys": ["nombre", "aliado", "vendedor", "monto"],
    "defaults": {"aliado": "Dimax (Zoom)"},
    "body_text": (
        "Hola {{nombre}} 👋\n"
        "Somos Circa, aliado de {{aliado}}.\n"
        "Tu vendedor te visitará para activar tu línea de crédito.\n"
        "Línea aprobada: S/ {{monto}}"
    ),
}

_CSV_HEADER_ALIASES: dict[str, str] = {
    "nombre": "nombre",
    "bodega": "nombre",
    "nombre_bodega": "nombre",
    "nombrecomercial": "nombre",
    "nombre_comercial": "nombre",
    "representante": "nombre",
    "representante_nombre_corto": "nombre",
    # CSV histórico: columna «aliado» se lee como vendedor.
    "aliado": "vendedor",
    "vendedor": "vendedor",
    "vendedor_nombre": "vendedor",
    "monto": "monto",
    "linea": "monto",
    "linea_aprobada": "monto",
    "soles": "monto",
    "telefono": "telefono",
    "tel": "telefono",
    "celular": "telefono",
    "whatsapp": "telefono",
    "telefono_whatsapp": "telefono",
}

CSV_EJEMPLO = """nombre,vendedor,monto,telefono
Bodega San Juan,Carlos Mendoza,1500,999888777
Minimarket El Sol,Ana García,800,987654321
"""

CSV_COLUMNAS_AYUDA = "nombre (bodega), vendedor, monto (soles), telefono"


def normalize_template_config(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    base = dict(DEFAULT_TEMPLATE_CONFIG)
    if not cfg:
        return base
    if cfg.get("template_name"):
        base["template_name"] = str(cfg["template_name"]).strip()
    if cfg.get("language"):
        base["language"] = str(cfg["language"]).strip()
    if cfg.get("variable_keys"):
        keys = [str(k).strip() for k in cfg["variable_keys"] if str(k).strip()]
        if keys:
            base["variable_keys"] = keys
    if cfg.get("defaults") and isinstance(cfg["defaults"], dict):
        base["defaults"] = {**base.get("defaults", {}), **cfg["defaults"]}
    if cfg.get("body_text"):
        base["body_text"] = str(cfg["body_text"])
    return base


def _fmt_monto(x: Any) -> str:
    try:
        val = float(x or 0)
    except (TypeError, ValueError):
        val = 0.0
    return str(int(val)) if val == int(val) else f"{val:.2f}"


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return ""
    if digits.startswith("51") and len(digits) >= 11:
        return digits
    if len(digits) == 9:
        return "51" + digits
    return digits


def _fetch_bodegas_by_ids(bodega_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not bodega_ids:
        return {}
    out: dict[str, dict[str, Any]] = {}
    chunk = 80
    for i in range(0, len(bodega_ids), chunk):
        part = bodega_ids[i : i + chunk]
        rows = (
            db.sb.table("bodegas")
            .select(
                "id, nombre_comercial, telefono_whatsapp, es_test, "
                "representante_nombre_corto, linea_aprobada"
            )
            .in_("id", part)
            .execute()
            .data
            or []
        )
        for row in rows:
            if row.get("id"):
                out[str(row["id"])] = row
    return out


_BODEGA_LOOKUP_COLS = (
    "id, nombre_comercial, telefono_whatsapp, es_test, "
    "representante_nombre_corto, linea_aprobada, razon_social"
)


def _resolve_bodega_by_nombre(nombre: str) -> tuple[Optional[dict[str, Any]], str]:
    """Busca bodega por nombre comercial (coincidencia exacta o única parcial)."""
    n = (nombre or "").strip()
    if len(n) < 2:
        return None, "nombre de bodega muy corto"

    found: dict[str, dict[str, Any]] = {}
    pattern = f"%{n}%"
    for col in ("nombre_comercial", "razon_social", "representante_nombre_corto"):
        rows = (
            db.sb.table("bodegas")
            .select(_BODEGA_LOOKUP_COLS)
            .ilike(col, pattern)
            .limit(10)
            .execute()
            .data
            or []
        )
        for row in rows:
            if row.get("id"):
                found[str(row["id"])] = row

    if not found:
        return None, "bodega no encontrada"

    exact = [
        b
        for b in found.values()
        if (b.get("nombre_comercial") or "").strip().lower() == n.lower()
        or (b.get("razon_social") or "").strip().lower() == n.lower()
        or (b.get("representante_nombre_corto") or "").strip().lower() == n.lower()
    ]
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return None, f"nombre ambiguo ({len(exact)} coincidencias exactas)"

    rows = list(found.values())
    if len(rows) == 1:
        return rows[0], ""
    return None, f"nombre ambiguo ({len(rows)} coincidencias; usa el nombre exacto)"


def _fetch_vendedores_por_bodega(bodega_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not bodega_ids:
        return {}
    out: dict[str, dict[str, Any]] = {}
    chunk = 80
    for i in range(0, len(bodega_ids), chunk):
        part = bodega_ids[i : i + chunk]
        try:
            rows = (
                db.sb.table("bodega_vendedores")
                .select("bodega_id, vendedores(nombre, codigo)")
                .in_("bodega_id", part)
                .eq("activo", True)
                .execute()
                .data
                or []
            )
        except Exception:
            rows = []
        for row in rows:
            bid = row.get("bodega_id")
            if not bid or bid in out:
                continue
            v = row.get("vendedores") or {}
            if isinstance(v, list):
                v = v[0] if v else {}
            out[bid] = v
    return out


def resolve_item_variables(
    *,
    bodega: Optional[dict[str, Any]] = None,
    vendedor: Optional[dict[str, Any]] = None,
    overrides: Optional[dict[str, Any]] = None,
    template_config: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    cfg = normalize_template_config(template_config)
    defaults = cfg.get("defaults") or {}
    bodega = bodega or {}
    vendedor = vendedor or {}
    overrides = overrides or {}

    csv_vendedor = str(overrides.get("vendedor") or "").strip()

    nombre = (
        overrides.get("nombre")
        or bodega.get("representante_nombre_corto")
        or bodega.get("nombre_comercial")
        or defaults.get("nombre")
        or "estimado cliente"
    )
    # CSV columna «vendedor» → {{2}} aliado y {{3}} vendedor (mismo valor).
    aliado = (
        overrides.get("aliado")
        or csv_vendedor
        or defaults.get("aliado")
        or "Dimax (Zoom)"
    )
    aliado_from_csv = bool(overrides.get("aliado") or csv_vendedor)
    if aliado_from_csv:
        vendedor_nombre = str(aliado).strip()
    else:
        vendedor_nombre = (
            vendedor.get("nombre")
            or vendedor.get("codigo")
            or defaults.get("vendedor")
            or "tu vendedor"
        )
    monto_raw = overrides.get("monto")
    if monto_raw is None:
        monto_raw = bodega.get("linea_aprobada") or defaults.get("monto") or 0

    return {
        "nombre": str(nombre).strip(),
        "aliado": str(aliado).strip(),
        "vendedor": str(vendedor_nombre).strip(),
        "monto": _fmt_monto(monto_raw),
    }


def _payload_overrides_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Arma overrides de envío sin contaminar el vendedor CSV con placeholders de vista previa."""
    overrides: dict[str, Any] = {}
    for key in ("nombre", "monto", "nombre_comercial", "aliado"):
        val = raw.get(key)
        if val not in (None, ""):
            overrides[key] = val
    # Columna CSV «vendedor» → Meta aliado (si aún no hay aliado explícito).
    vend = str(raw.get("vendedor") or "").strip()
    if vend and vend not in ("tu vendedor", "—") and not overrides.get("aliado"):
        overrides["vendedor"] = vend
    return overrides


def _resolve_variables_for_send_item(
    item: dict[str, Any],
    *,
    template_config: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    """Reconstruye variables Meta al enviar (no confiar en variable_values obsoletos)."""
    bid = item.get("bodega_id")
    bodega: dict[str, Any] = {}
    vendedor: dict[str, Any] = {}
    if bid:
        bodegas = _fetch_bodegas_by_ids([str(bid)])
        bodega = bodegas.get(str(bid)) or {}
        vendedores = _fetch_vendedores_por_bodega([str(bid)])
        vendedor = vendedores.get(str(bid)) or {}

    vv = item.get("variable_values") or {}
    raw = {
        "nombre": vv.get("nombre"),
        "monto": vv.get("monto"),
        "aliado": vv.get("aliado"),
    }
    for var in item.get("variables") or []:
        if not isinstance(var, dict) or not var.get("name"):
            continue
        name = str(var["name"])
        if name in ("nombre", "monto", "aliado") and var.get("value") not in (None, ""):
            raw[name] = var.get("value")
    return resolve_item_variables(
        bodega=bodega,
        vendedor=vendedor,
        overrides=_payload_overrides_from_raw(raw),
        template_config=template_config,
    )


def compose_visita_credito_mensaje(
    *,
    telefono: str,
    bodega_nombre: str,
    variables: dict[str, str],
    template_config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = normalize_template_config(template_config)
    tpl_name = cfg["template_name"]
    keys = cfg["variable_keys"]
    body_tpl = cfg.get("body_text") or ""

    body_rendered = body_tpl
    for key in keys:
        body_rendered = body_rendered.replace("{{" + key + "}}", variables.get(key, ""))

    return {
        "plantilla": tpl_name,
        "telefono_destino": telefono or None,
        "variables": [{"name": k, "value": variables.get(k, "")} for k in keys],
        "mensaje_preview": body_rendered.strip(),
        "mensaje_tipo": "whatsapp_template",
        "body_rendered": body_rendered.strip(),
        "template_language": str(cfg.get("language", "es_MX")),
    }


def build_preview_item(
    *,
    item_id: str,
    bodega: Optional[dict[str, Any]] = None,
    vendedor: Optional[dict[str, Any]] = None,
    overrides: Optional[dict[str, Any]] = None,
    template_config: Optional[dict[str, Any]] = None,
    source: str = "bodega",
    telefono_ingresado: Optional[str] = None,
) -> dict[str, Any]:
    bodega = bodega or {}
    overrides = overrides or {}
    explicit_tel = _normalize_phone(
        telefono_ingresado or overrides.get("telefono") or overrides.get("telefono_envio") or ""
    )
    # CSV / payload manual: solo el número ingresado. Buscador de bodegas: teléfono de BD.
    if explicit_tel or source in ("csv", "manual"):
        telefono = explicit_tel
    else:
        telefono = _normalize_phone(bodega.get("telefono_whatsapp") or "")
    variables = resolve_item_variables(
        bodega=bodega,
        vendedor=vendedor,
        overrides=overrides,
        template_config=template_config,
    )
    bodega_nombre = (
        bodega.get("nombre_comercial")
        or (overrides or {}).get("nombre_comercial")
        or variables.get("nombre")
        or "—"
    )
    vend_nombre = (
        (overrides or {}).get("vendedor")
        or variables.get("aliado")
        or variables.get("vendedor")
        or "—"
    )
    msg = compose_visita_credito_mensaje(
        telefono=telefono,
        bodega_nombre=bodega_nombre,
        variables=variables,
        template_config=template_config,
    )
    cfg = normalize_template_config(template_config)
    detalle = (
        f"{bodega_nombre} · S/{variables.get('monto', '0')} · "
        f"{cfg['template_name']} · origen {source}"
    )
    return {
        "item_id": item_id,
        "bodega_id": bodega.get("id"),
        "bodega_nombre": bodega_nombre,
        "telefono": telefono or None,
        "telefono_envio": explicit_tel or telefono or None,
        "vendedor_nombre": vend_nombre,
        "es_test": bool(bodega.get("es_test")),
        "detalle": detalle,
        "accion": (
            f"Enviar plantilla {cfg['template_name']}"
            if telefono
            else "Omitido (sin teléfono)"
        ),
        "plantilla": msg["plantilla"],
        "mensaje_preview": msg["mensaje_preview"],
        "body_rendered": msg.get("body_rendered"),
        "template_language": msg.get("template_language"),
        "mensaje_tipo": msg["mensaje_tipo"],
        "variables": msg["variables"],
        "variable_values": variables,
        "source": source,
    }


def list_visita_credito_preview_items(
    *,
    bodega_ids: Optional[list[str]] = None,
    custom_items: Optional[list[dict[str, Any]]] = None,
    template_config: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    cfg = normalize_template_config(template_config)
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if bodega_ids:
        bodegas = _fetch_bodegas_by_ids([str(x) for x in bodega_ids])
        vendedores = _fetch_vendedores_por_bodega(list(bodegas.keys()))
        for bid in bodega_ids:
            bid_s = str(bid)
            if bid_s in seen_ids:
                continue
            bodega = bodegas.get(bid_s)
            if not bodega:
                continue
            seen_ids.add(bid_s)
            items.append(
                build_preview_item(
                    item_id=bid_s,
                    bodega=bodega,
                    vendedor=vendedores.get(bid_s),
                    template_config=cfg,
                    source="bodega",
                )
            )

    for raw in custom_items or []:
        if not isinstance(raw, dict):
            continue
        bid = raw.get("bodega_id")
        item_id = str(raw.get("item_id") or bid or "")
        telefono = _normalize_phone(raw.get("telefono") or "")
        if not item_id:
            seed = telefono or str(raw.get("nombre") or "")
            item_id = "csv-" + hashlib.md5(seed.encode()).hexdigest()[:12]
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        bodega: dict[str, Any] = {}
        vendedor: dict[str, Any] = {}
        if bid:
            bodegas = _fetch_bodegas_by_ids([str(bid)])
            bodega = bodegas.get(str(bid)) or {"id": bid}
            vendedores = _fetch_vendedores_por_bodega([str(bid)])
            vendedor = vendedores.get(str(bid)) or {}

        overrides = {
            k: raw.get(k)
            for k in (
                "nombre",
                "vendedor",
                "monto",
                "telefono",
                "telefono_envio",
                "nombre_comercial",
            )
            if raw.get(k) not in (None, "")
        }
        explicit_tel = _normalize_phone(
            raw.get("telefono_envio") or raw.get("telefono") or ""
        )
        items.append(
            build_preview_item(
                item_id=item_id,
                bodega=bodega,
                vendedor=vendedor,
                overrides=overrides,
                template_config=cfg,
                source=str(raw.get("source") or "csv"),
                telefono_ingresado=explicit_tel or None,
            )
        )

    return items


def _item_destino_telefono(item: dict[str, Any]) -> str:
    return _normalize_phone(item.get("telefono_envio") or item.get("telefono") or "")


def filter_items_by_test_mode(
    items: list[dict[str, Any]],
    test: Optional[str],
) -> list[dict[str, Any]]:
    """Filas CSV/manual las eligió el usuario; solo bodegas de BD siguen es_test."""
    if not test:
        return items
    if test == "real":
        return [
            i
            for i in items
            if i.get("source") in ("csv", "manual") or not i.get("es_test")
        ]
    if test == "test":
        return [
            i
            for i in items
            if i.get("source") in ("csv", "manual") or i.get("es_test")
        ]
    return items


def build_items_for_send(
    custom_items: list[dict[str, Any]],
    *,
    template_config: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    Arma items para envío usando únicamente el teléfono del payload (CSV/UI),
    sin reemplazarlo por el de la bodega en BD.
    """
    cfg = normalize_template_config(template_config)
    items: list[dict[str, Any]] = []
    for raw in custom_items or []:
        if not isinstance(raw, dict):
            logger.warning("visita_credito build_items_for_send: fila ignorada (no es dict)")
            continue
        telefono = _normalize_phone(raw.get("telefono_envio") or raw.get("telefono") or "")
        if not telefono:
            logger.warning(
                "visita_credito build_items_for_send: sin teléfono item_id=%s nombre=%s",
                raw.get("item_id"),
                raw.get("nombre"),
            )
            continue
        bid = raw.get("bodega_id")
        bodega: dict[str, Any] = {}
        vendedor: dict[str, Any] = {}
        if bid:
            bodegas = _fetch_bodegas_by_ids([str(bid)])
            bodega = bodegas.get(str(bid)) or {"id": bid}
            vendedores = _fetch_vendedores_por_bodega([str(bid)])
            vendedor = vendedores.get(str(bid)) or {}

        overrides = _payload_overrides_from_raw(raw)
        item_id = str(raw.get("item_id") or bid or f"send-{telefono}")
        item = build_preview_item(
            item_id=item_id,
            bodega=bodega,
            vendedor=vendedor,
            overrides=overrides,
            template_config=cfg,
            source=str(raw.get("source") or "csv"),
            telefono_ingresado=telefono,
        )
        item["telefono"] = telefono
        item["telefono_envio"] = telefono
        if raw.get("es_test") is not None:
            item["es_test"] = bool(raw.get("es_test"))
        items.append(item)
    logger.info(
        "visita_credito build_items_for_send: %s item(s) listos desde %s payload(s)",
        len(items),
        len(custom_items or []),
    )
    return items


def _normalize_csv_header(name: str) -> str:
    key = re.sub(r"[^a-z0-9_]", "", str(name or "").strip().lower())
    return _CSV_HEADER_ALIASES.get(key, key)


def parse_csv_recipients(
    csv_text: str,
    *,
    template_config: Optional[dict[str, Any]] = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    cfg = normalize_template_config(template_config)
    errors: list[str] = []
    if not (csv_text or "").strip():
        return [], ["CSV vacío"]

    try:
        sample = csv_text[:2048]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(csv_text), dialect=dialect)
    if not reader.fieldnames:
        return [], ["CSV sin encabezados"]

    field_map = {_normalize_csv_header(h): h for h in reader.fieldnames if h}
    required = {"nombre", "vendedor", "monto", "telefono"}
    if not required.issubset(set(field_map.keys())):
        return [], [
            f"El CSV debe incluir las columnas: {CSV_COLUMNAS_AYUDA}. "
            f"Encabezados detectados: {', '.join(reader.fieldnames)}"
        ]

    raw_rows: list[dict[str, Any]] = []

    for i, row in enumerate(reader, start=2):
        mapped: dict[str, Any] = {"source": "csv"}
        for norm_key, orig_key in field_map.items():
            val = (row.get(orig_key) or "").strip()
            if val:
                mapped[norm_key] = val

        nombre = mapped.get("nombre")
        vendedor = mapped.get("vendedor")
        monto = mapped.get("monto")
        telefono = _normalize_phone(mapped.get("telefono") or "")
        if not nombre or not vendedor or monto in (None, "") or not telefono:
            errors.append(f"Fila {i}: requiere nombre, vendedor, monto y teléfono")
            continue

        try:
            float(str(monto).replace(",", "."))
        except ValueError:
            errors.append(f"Fila {i}: monto inválido ({monto})")
            continue

        mapped["telefono"] = telefono
        mapped["telefono_envio"] = telefono
        bodega, _lookup_err = _resolve_bodega_by_nombre(nombre)
        if bodega:
            mapped["bodega_id"] = bodega["id"]
            mapped["nombre_comercial"] = bodega.get("nombre_comercial")
            mapped["es_test"] = bool(bodega.get("es_test"))
        raw_rows.append(mapped)

    items = list_visita_credito_preview_items(custom_items=raw_rows, template_config=cfg)
    return items, errors


async def send_visita_credito_item(
    item: dict[str, Any],
    *,
    template_config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from app.routes import distribuidor as dist

    cfg = normalize_template_config(template_config)
    telefono = _normalize_phone(
        item.get("telefono_envio") or item.get("telefono") or ""
    )
    if not telefono:
        return {"ok": False, "error": "Sin teléfono"}

    # Siempre reconstruir variables al enviar (el payload UI puede traer vendedor="tu vendedor").
    var_values = _resolve_variables_for_send_item(item, template_config=cfg)
    keys = cfg["variable_keys"]
    variables = [str(var_values.get(k, "")) for k in keys]
    tpl_name = cfg["template_name"]

    logger.info(
        "visita_credito enviando WA item_id=%s tel=%s plantilla=%s vars=%s bodega=%s",
        item.get("item_id"),
        telefono,
        tpl_name,
        variables,
        item.get("bodega_nombre"),
    )

    resultado = dist._send_wa_template(telefono, tpl_name, variables)
    if not resultado.get("ok"):
        err = resultado.get("error") or "Meta rechazó el envío"
        logger.error(
            "visita_credito Meta falló item_id=%s tel=%s plantilla=%s error=%s",
            item.get("item_id"),
            telefono,
            tpl_name,
            err,
        )
        return {"ok": False, "error": err, "telefono": telefono, "plantilla": tpl_name}

    logger.info(
        "visita_credito Meta OK item_id=%s tel=%s plantilla=%s lang=%s wamid=%s",
        item.get("item_id"),
        telefono,
        tpl_name,
        resultado.get("lang"),
        ((resultado.get("response") or {}).get("messages") or [{}])[0].get("id", ""),
    )

    wamid = ""
    try:
        wamid = ((resultado.get("response") or {}).get("messages") or [{}])[0].get("id", "")
    except (IndexError, KeyError, TypeError):
        wamid = ""

    try:
        from app.services.analytics import track_message

        track_message(
            telefono=telefono,
            direction="outbound",
            bodega_id=item.get("bodega_id"),
            message_id=wamid,
            message_type="visita_credito_recordatorio",
            template_name=tpl_name,
            content=f"Recordatorio de ventas — {item.get('bodega_nombre', '')}",
            metadata={
                "item_id": item.get("item_id"),
                "variables": var_values,
            },
            measure_response_latency=False,
        )
    except Exception as e:
        logger.error("[visita_credito track_message] %s", e)

    return {
        "ok": True,
        "enviado_a": telefono,
        "bodega": item.get("bodega_nombre"),
        "plantilla": tpl_name,
    }


async def send_visita_credito_batch(
    *,
    items: list[dict[str, Any]],
    selected_ids: Optional[list[str]] = None,
    template_config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    allowed = {str(x) for x in selected_ids} if selected_ids else None
    sent = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    send_log: list[str] = []

    logger.info(
        "visita_credito batch inicio: %s item(s)%s",
        len(items),
        f", selected_ids={len(allowed)}" if allowed else "",
    )

    for item in items:
        iid = str(item.get("item_id") or "")
        if allowed is not None and iid not in allowed:
            msg = f"omitido item_id={iid}: no está en selected_ids"
            send_log.append(msg)
            logger.warning("visita_credito %s", msg)
            continue
        telefono = _item_destino_telefono(item)
        if not telefono:
            skipped += 1
            err = "Sin teléfono en el item"
            errors.append({"item_id": iid, "error": err})
            send_log.append(f"skip item_id={iid}: {err}")
            logger.warning("visita_credito skip item_id=%s: %s", iid, err)
            continue
        result = await send_visita_credito_item(item, template_config=template_config)
        if result.get("ok"):
            sent += 1
            send_log.append(
                f"ok item_id={iid} tel={telefono} plantilla={result.get('plantilla')}"
            )
            logger.info(
                "Visita crédito reminder sent: %s — %s — %s",
                result.get("bodega"),
                result.get("plantilla"),
                telefono,
            )
        else:
            err = str(result.get("error") or "error")
            errors.append({"item_id": iid, "error": err, "telefono": telefono})
            send_log.append(f"error item_id={iid} tel={telefono}: {err[:200]}")
            logger.error("visita_credito error item_id=%s tel=%s: %s", iid, telefono, err)

    summary = f"fin batch: sent={sent} skipped={skipped} errors={len(errors)}"
    send_log.append(summary)
    logger.info("visita_credito %s", summary)

    return {"sent": sent, "skipped": skipped, "errors": errors, "send_log": send_log}
