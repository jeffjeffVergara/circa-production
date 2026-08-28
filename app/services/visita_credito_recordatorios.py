"""
Recordatorio visita crédito — plantilla Meta circa_recordatorio_visita_credito.

Variables Meta (orden fijo):
  {{1}} nombre · {{2}} aliado · {{3}} vendedor · {{4}} monto
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
        "Tu vendedor {{vendedor}} te visitará para activar tu línea de crédito.\n"
        "Línea aprobada: S/ {{monto}}"
    ),
}

_CSV_HEADER_ALIASES: dict[str, str] = {
    "telefono": "telefono",
    "tel": "telefono",
    "wa": "telefono",
    "whatsapp": "telefono",
    "telefono_whatsapp": "telefono",
    "bodega_id": "bodega_id",
    "id": "bodega_id",
    "nombre": "nombre",
    "representante": "nombre",
    "representante_nombre_corto": "nombre",
    "nombre_comercial": "nombre_comercial",
    "vendedor": "vendedor",
    "vendedor_nombre": "vendedor",
    "aliado": "aliado",
    "distribuidor": "aliado",
    "monto": "monto",
    "linea": "monto",
    "linea_aprobada": "monto",
}


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

    nombre = (
        overrides.get("nombre")
        or bodega.get("representante_nombre_corto")
        or bodega.get("nombre_comercial")
        or defaults.get("nombre")
        or "estimado cliente"
    )
    aliado = overrides.get("aliado") or defaults.get("aliado") or "Dimax (Zoom)"
    vendedor_nombre = (
        overrides.get("vendedor")
        or vendedor.get("nombre")
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

    var_lines = [f"{{{i}}} {k} = {variables.get(k, '')}" for i, k in enumerate(keys, 1)]
    preview_lines = [
        f"Plantilla Meta: {tpl_name} ({cfg.get('language', 'es_MX')})",
        f"Destino WA: {telefono or '(sin teléfono)'}",
        f"Bodega: {bodega_nombre or '—'}",
        "",
        "Cuerpo (vista previa):",
        body_rendered,
        "",
        "Variables de la plantilla:",
        *var_lines,
    ]
    return {
        "plantilla": tpl_name,
        "telefono_destino": telefono or None,
        "variables": [{"name": k, "value": variables.get(k, "")} for k in keys],
        "mensaje_preview": "\n".join(preview_lines),
        "mensaje_tipo": "whatsapp_template",
        "body_rendered": body_rendered,
    }


def build_preview_item(
    *,
    item_id: str,
    bodega: Optional[dict[str, Any]] = None,
    vendedor: Optional[dict[str, Any]] = None,
    overrides: Optional[dict[str, Any]] = None,
    template_config: Optional[dict[str, Any]] = None,
    source: str = "bodega",
) -> dict[str, Any]:
    bodega = bodega or {}
    telefono = _normalize_phone(
        (overrides or {}).get("telefono")
        or bodega.get("telefono_whatsapp")
        or ""
    )
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
    vend_nombre = variables.get("vendedor") or "—"
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
            for k in ("nombre", "aliado", "vendedor", "monto", "telefono", "nombre_comercial")
            if raw.get(k) not in (None, "")
        }
        items.append(
            build_preview_item(
                item_id=item_id,
                bodega=bodega,
                vendedor=vendedor,
                overrides=overrides,
                template_config=cfg,
                source=str(raw.get("source") or "csv"),
            )
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
    raw_rows: list[dict[str, Any]] = []

    for i, row in enumerate(reader, start=2):
        mapped: dict[str, Any] = {"source": "csv"}
        for norm_key, orig_key in field_map.items():
            val = (row.get(orig_key) or "").strip()
            if val:
                mapped[norm_key] = val
        telefono = _normalize_phone(mapped.get("telefono") or "")
        if telefono:
            mapped["telefono"] = telefono
        if not telefono and not mapped.get("bodega_id"):
            errors.append(f"Fila {i}: falta teléfono o bodega_id")
            continue
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
    telefono = _normalize_phone(item.get("telefono") or "")
    if not telefono:
        return {"ok": False, "error": "Sin teléfono"}

    # Prefer stored variable_values; rebuild if missing
    var_values = item.get("variable_values")
    if not var_values:
        var_values = resolve_item_variables(
            overrides={v["name"]: v["value"] for v in (item.get("variables") or []) if v.get("name")},
            template_config=cfg,
        )
    keys = cfg["variable_keys"]
    variables = [str(var_values.get(k, "")) for k in keys]
    tpl_name = cfg["template_name"]

    resultado = dist._send_wa_template(telefono, tpl_name, variables)
    if not resultado.get("ok"):
        return {"ok": False, "error": resultado.get("error") or "Meta rechazó el envío"}

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
            content=f"Recordatorio visita crédito — {item.get('bodega_nombre', '')}",
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

    for item in items:
        iid = str(item.get("item_id") or "")
        if allowed is not None and iid not in allowed:
            continue
        if not item.get("telefono"):
            skipped += 1
            continue
        result = await send_visita_credito_item(item, template_config=template_config)
        if result.get("ok"):
            sent += 1
            logger.info(
                "Visita crédito reminder sent: %s — %s",
                result.get("bodega"),
                result.get("plantilla"),
            )
        else:
            errors.append({"item_id": iid, "error": str(result.get("error") or "error")})

    return {"sent": sent, "skipped": skipped, "errors": errors}
