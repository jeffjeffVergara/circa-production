"""
Handlers de comercio/pago del webhook Meta — extraídos de main.py.

Usa MetaWaContext para resolver bodega una sola vez por mensaje.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.services import db
from app.services.fees import calculate_fee, format_rate_pct, fee_regimen_para_pedido_nuevo

logger = logging.getLogger("circa.meta.handlers")


def normalize_wa_phone(telefono: str) -> str:
    t = (telefono or "").strip()
    if t and not t.startswith("+"):
        t = f"+{t}"
    return t


@dataclass
class MetaWaContext:
    telefono: str
    bodega: dict | None = None

    @property
    def bodega_id(self) -> str | None:
        return self.bodega.get("id") if self.bodega else None

    @classmethod
    def from_phone(cls, telefono: str) -> MetaWaContext:
        tel = normalize_wa_phone(telefono)
        bodega = db.get_bodega_by_phone(tel)
        return cls(telefono=tel, bodega=bodega)


def _pedido_total(pedido: dict) -> float:
    return float(pedido.get("total_pedido") or pedido.get("monto_productos") or 0)


def _is_draft_status(estado: str) -> bool:
    return estado in ("borrador", "preventa_borrador")


def _confirmed_status_for(tipo_operacion: str) -> str:
    return "preventa_confirmada" if tipo_operacion == "preventa" else "confirmado"


async def _gen_order_number(bodega_id: str, tipo_operacion: str = "venta") -> str:
    prefix = "PRV" if tipo_operacion == "preventa" else "CRC"
    afil = "TEST"
    try:
        b = (
            db.sb.table("bodegas")
            .select("codigo_afiliado")
            .eq("id", bodega_id)
            .limit(1)
            .execute()
        )
        codigo = b.data[0].get("codigo_afiliado") if b.data else None
        if codigo and codigo.startswith("CIRCA-"):
            afil = codigo.split("-")[1]
    except Exception as e:
        logger.error("_gen_order_number afiliado %s: %s", bodega_id, e)

    n = 1
    try:
        r = (
            db.sb.table("pedidos")
            .select("numero")
            .eq("bodega_id", bodega_id)
            .eq("tipo_operacion", tipo_operacion)
            .not_.is_("numero", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if r.data and r.data[0].get("numero"):
            partes = r.data[0]["numero"].split("-")
            if len(partes) == 3 and partes[2].isdigit():
                n = int(partes[2]) + 1
    except Exception as e:
        logger.error("_gen_order_number correlativo %s: %s", bodega_id, e)

    return f"{prefix}-{afil}-{n:03d}"


async def _mark_read(msg: dict, meta_client) -> None:
    if msg.get("message_id"):
        await meta_client.mark_as_read(msg["message_id"])


async def handle_editar(btn: str, ctx: MetaWaContext, msg: dict, meta_client) -> bool:
    if not btn.startswith("EDITAR_"):
        return False
    try:
        bod_id = ctx.bodega_id
        if bod_id:
            po = (
                db.sb.table("pedidos")
                .select("tipo_operacion")
                .eq("bodega_id", bod_id)
                .in_("estado", ["borrador", "preventa_borrador"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            tipo_op = "preventa" if po.data and po.data[0].get("tipo_operacion") == "preventa" else "venta"
            await meta_client.send_catalogo_flow(
                ctx.telefono,
                bod_id,
                tipo_operacion=tipo_op,
                edit_cart=True,
                catalog_prompt=(
                    "¡Aquí seguimos!\n"
                    "Tu pre-venta te está esperando en el catálogo: revísala con calma y confírmala cuando quieras."
                    if tipo_op == "preventa"
                    else (
                        "¡Seguimos donde lo dejaste!\n"
                        "Tu pedido sigue en el carrito: ábrelo, retoca lo que necesites y confirma cuando estés listo."
                    )
                ),
            )
    except Exception as e:
        logger.error("EDITAR error: %s", e, exc_info=True)
    await _mark_read(msg, meta_client)
    return True


async def handle_preconf(btn: str, ctx: MetaWaContext, msg: dict, meta_client) -> bool:
    if not btn.startswith("PRECONF_"):
        return False
    try:
        bod_id = ctx.bodega_id
        r = (
            db.sb.table("pedidos")
            .select("id, monto_productos")
            .eq("bodega_id", bod_id)
            .eq("estado", "preventa_borrador")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ) if bod_id else type("X", (), {"data": []})()
        if r.data:
            pedido = r.data[0]
            monto = pedido["monto_productos"]
            db.sb.table("sesiones").delete().eq("telefono", ctx.telefono).execute()
            db.sb.table("sesiones").insert({
                "telefono": ctx.telefono,
                "fase": "pin_pago",
                "datos": json.dumps({"pedido_id": pedido["id"], "dias": 0, "rate": 0, "monto": monto}),
                "bodega_id": bod_id,
            }).execute()
            await meta_client.send_text(
                ctx.telefono,
                f"🔐 *Confirmar pre-venta*\n\n"
                f"Ingresa tu clave Circa para confirmar la pre-venta por S/{monto:.2f}.",
            )
            await meta_client.send_pin_request(ctx.telefono, mode="verify", bodega_id=bod_id)
        else:
            await meta_client.send_text(ctx.telefono, "No encontré una pre-venta pendiente.")
    except Exception as e:
        logger.error("PRECONF handler error: %s", e, exc_info=True)
        await meta_client.send_text(ctx.telefono, "Error al confirmar pre-venta. Intenta de nuevo.")
    await _mark_read(msg, meta_client)
    return True


async def handle_contado(btn: str, ctx: MetaWaContext, msg: dict, meta_client) -> bool:
    if not btn.startswith("CONTADO_"):
        return False
    try:
        bod_id = ctx.bodega_id
        pedido_short = btn.split("_", 1)[1] if "_" in btn else ""
        pedido = (
            db.get_pedido_borrador_por_prefijo(bod_id, pedido_short)
            if bod_id and pedido_short
            else None
        )
        if pedido:
            monto = _pedido_total(pedido)
            db.sb.table("sesiones").delete().eq("telefono", ctx.telefono).execute()
            db.sb.table("sesiones").insert({
                "telefono": ctx.telefono,
                "fase": "pin_pago",
                "datos": json.dumps({"pedido_id": pedido["id"], "dias": 0, "rate": 0, "monto": monto}),
                "bodega_id": bod_id,
            }).execute()
            await meta_client.send_text(
                ctx.telefono,
                f"💵 *Pago al contado — S/{monto:.2f}*\n\n"
                f"Ingresa tu clave Circa de 4 dígitos para confirmar:",
            )
            await meta_client.send_pin_request(ctx.telefono, mode="verify", bodega_id=bod_id)
        else:
            await meta_client.send_text(ctx.telefono, "No encontré el pedido.")
    except Exception as e:
        logger.error("Contado handler error: %s", e, exc_info=True)
        await meta_client.send_text(ctx.telefono, "Error al confirmar.")
    await _mark_read(msg, meta_client)
    return True


async def handle_finfijo(btn: str, ctx: MetaWaContext, msg: dict, meta_client) -> bool:
    if not btn.startswith("FINFIJO"):
        return False
    import re as _re

    try:
        monto_match = _re.search(r"FINFIJO(\d+)_", btn)
        fin_amt = int(monto_match.group(1)) if monto_match else 0
        bod_id = ctx.bodega_id
        linea = float((ctx.bodega or {}).get("linea_disponible") or 0)
        pedido_short = btn.rsplit("_", 1)[-1] if "_" in btn else ""
        pedido = (
            db.get_pedido_borrador_por_prefijo(
                bod_id,
                pedido_short,
                ("borrador", "preventa_borrador", "preventa_confirmada"),
            )
            if bod_id and pedido_short
            else None
        )
        if pedido and fin_amt > 0:
            total = _pedido_total(pedido)
            contado = round(total - fin_amt, 2)
            dias = 7
            _qf = calculate_fee(fin_amt, dias)
            rate = _qf["rate"]
            fee = _qf["fee"]
            fecha_venc = (datetime.now() + timedelta(days=dias)).strftime("%d/%m/%Y")
            db.sb.table("sesiones").delete().eq("telefono", ctx.telefono).execute()
            db.sb.table("sesiones").insert({
                "telefono": ctx.telefono,
                "fase": "pin_pago",
                "datos": json.dumps({"pedido_id": pedido["id"], "dias": dias, "rate": rate, "monto": fin_amt}),
                "bodega_id": bod_id,
            }).execute()
            total_pagar = contado + fin_amt + fee
            await meta_client.send_text(
                ctx.telefono,
                f"\U0001f4b3 *Resumen de pago*\n\n"
                f"\U0001f69a Hoy pagas al repartidor: *S/{contado:.2f}*\n"
                f"\U0001f4b3 Cuota Circa S/{fin_amt + fee:.2f} — pagar antes del {fecha_venc}\n\n"
                f"*Total a pagar: S/{total_pagar:.2f}*\n\n"
                f"Confirma con tu clave de 4 digitos.",
            )
            await meta_client.send_pin_request(ctx.telefono, mode="verify", bodega_id=bod_id)
    except Exception as e:
        logger.error("FINFIJO error: %s", e)
    await _mark_read(msg, meta_client)
    return True


async def handle_fin_pct(btn: str, ctx: MetaWaContext, msg: dict, meta_client) -> bool:
    if not (btn.startswith("FIN100_") or btn.startswith("FIN50_") or btn.startswith("FIN25_")):
        return False
    try:
        bod_id = ctx.bodega_id
        linea = float((ctx.bodega or {}).get("linea_disponible") or 0)
        pedido_short = btn.rsplit("_", 1)[-1] if "_" in btn else ""
        pedido = (
            db.get_pedido_borrador_por_prefijo(
                bod_id, pedido_short,
                ("borrador", "preventa_borrador", "preventa_confirmada"),
            )
            if bod_id and pedido_short
            else None
        )
        if pedido:
            total = _pedido_total(pedido)
            if btn.startswith("FIN100_"):
                fin_amt = min(linea, total)
            elif btn.startswith("FIN50_"):
                fin_amt = min(round(linea * 0.5, 2), total)
            else:
                fin_amt = min(round(linea * 0.25, 2), total)
            contado = round(total - fin_amt, 2)
            fee7 = calculate_fee(fin_amt, 7)["fee"]
            fee15 = calculate_fee(fin_amt, 15)["fee"]
            fee30 = calculate_fee(fin_amt, 30)["fee"]
            pid = str(pedido["id"])[:8]
            db.sb.table("sesiones").delete().eq("telefono", ctx.telefono).execute()
            db.sb.table("sesiones").insert({
                "telefono": ctx.telefono,
                "fase": "fin_plazo",
                "datos": json.dumps({
                    "pedido_id": pedido["id"],
                    "fin_amt": fin_amt,
                    "contado": contado,
                    "total": total,
                }),
                "bodega_id": bod_id,
            }).execute()
            await meta_client.send_list(
                to=ctx.telefono,
                body=f"Financiar: *S/{fin_amt:.2f}*\nAl contado: S/{contado:.2f}\n\nElige plazo:",
                button_text="Ver plazos",
                sections=[{"title": "Plazo de pago", "rows": [
                    {"id": f"PAY7_{pid}", "title": f"7 días ({format_rate_pct(calculate_fee(fin_amt, 7)['rate'])})", "description": f"Cargo Circa S/{fee7:.2f} · Total S/{fin_amt+fee7:.2f}"},
                    {"id": f"PAY15_{pid}", "title": f"15 días ({format_rate_pct(calculate_fee(fin_amt, 15)['rate'])})", "description": f"Cargo Circa S/{fee15:.2f} · Total S/{fin_amt+fee15:.2f}"},
                    {"id": f"PAY30_{pid}", "title": f"30 días ({format_rate_pct(calculate_fee(fin_amt, 30)['rate'])})", "description": f"Cargo Circa S/{fee30:.2f} · Total S/{fin_amt+fee30:.2f}"},
                ]}],
            )
        else:
            await meta_client.send_text(ctx.telefono, "No encontré el pedido.")
    except Exception as e:
        logger.error("FIN handler error: %s", e, exc_info=True)
        await meta_client.send_text(ctx.telefono, "Error. Intenta de nuevo.")
    await _mark_read(msg, meta_client)
    return True


async def handle_pay_plazo(btn: str, ctx: MetaWaContext, msg: dict, meta_client) -> bool:
    if not (btn.startswith("PAY7_") or btn.startswith("PAY15_") or btn.startswith("PAY30_")):
        return False
    pedido_short = btn.split("_", 1)[1] if "_" in btn else ""
    if btn.startswith("PAY7"):
        dias = 7
    elif btn.startswith("PAY15"):
        dias = 15
    else:
        dias = 30
    try:
        bod_id = ctx.bodega_id
        pedido = (
            db.get_pedido_borrador_por_prefijo(bod_id, pedido_short)
            if bod_id and pedido_short
            else None
        )
        if pedido:
            ses_fin = db.sb.table("sesiones").select("datos").eq("telefono", ctx.telefono).limit(1).execute()
            fin_amt = _pedido_total(pedido)
            contado = 0.0
            if ses_fin.data and ses_fin.data[0].get("datos"):
                sd = json.loads(ses_fin.data[0]["datos"]) if isinstance(ses_fin.data[0]["datos"], str) else ses_fin.data[0]["datos"]
                if sd.get("fin_amt"):
                    fin_amt = float(sd["fin_amt"])
                    contado = float(sd.get("contado") or 0)
            monto = fin_amt
            _qfee = calculate_fee(float(monto), int(dias))
            fee = _qfee["fee"]
            rate = _qfee["rate"]
            venc = (datetime.now() + timedelta(days=dias)).strftime("%d/%m/%Y")
            db.sb.table("sesiones").delete().eq("telefono", ctx.telefono).execute()
            db.sb.table("sesiones").insert({
                "telefono": ctx.telefono,
                "fase": "pin_pago",
                "datos": json.dumps({
                    "pedido_id": pedido["id"],
                    "dias": dias,
                    "rate": rate,
                    "monto": monto,
                    "fee": round(fee, 2),
                    "venc": venc,
                    "contado": contado,
                }),
                "bodega_id": bod_id,
            }).execute()
            await meta_client.send_text(
                ctx.telefono,
                f"💳 *Circa {dias} dias*\n"
                f"Financiar: S/{monto:.2f}\n"
                f"Comisión Circa ({format_rate_pct(rate)}): S/{fee:.2f}\n"
                f"*TOTAL: S/{monto+fee:.2f}*\n"
                f"Vence: {venc}",
            )
            await meta_client.send_pin_request(ctx.telefono, mode="verify", bodega_id=bod_id)
            logger.info("Order %s plazo %sd fee=%s", pedido["id"], dias, fee)
        else:
            await meta_client.send_text(ctx.telefono, "No encontre el pedido. Intenta de nuevo.")
    except Exception as e:
        logger.error("Payment handler error: %s", e, exc_info=True)
        await meta_client.send_text(ctx.telefono, "Error al confirmar. Intenta de nuevo.")
    await _mark_read(msg, meta_client)
    return True


async def handle_menu_buttons(btn: str, ctx: MetaWaContext, msg: dict, meta_client) -> bool:
    if btn == "YA_PAGUE":
        try:
            await meta_client.send_text(
                ctx.telefono,
                "🎉 *¡Pago registrado!*\n\n"
                "Verificación en las próximas horas.\n"
                "Tu tope se renueva cuando Circa confirme el pago.\n\n"
                "Escribe *MENU* para volver al menú principal.",
            )
        except Exception as e:
            logger.error("YA_PAGUE error: %s", e)
        await _mark_read(msg, meta_client)
        return True

    if btn == "PEDIDO":
        try:
            if ctx.bodega:
                await meta_client.send_catalogo_flow(
                    ctx.telefono, ctx.bodega["id"], tipo_operacion="venta", fresh=True
                )
            else:
                await meta_client.send_text(ctx.telefono, "Escribe MENU para empezar.")
        except Exception as e:
            logger.error("PEDIDO handler error: %s", e, exc_info=True)
        await _mark_read(msg, meta_client)
        return True

    if btn == "PREVENTA":
        try:
            if ctx.bodega:
                await meta_client.send_catalogo_flow(
                    ctx.telefono, ctx.bodega["id"], tipo_operacion="preventa", fresh=True
                )
            else:
                await meta_client.send_text(ctx.telefono, "Escribe MENU para empezar.")
        except Exception as e:
            logger.error("PREVENTA handler error: %s", e, exc_info=True)
        await _mark_read(msg, meta_client)
        return True

    if btn == "REPETIR":
        try:
            if not ctx.bodega:
                await meta_client.send_text(ctx.telefono, "Escribe MENU para empezar.")
            else:
                items = db.get_items_para_repetir(ctx.bodega)
                if items:
                    db.save_carrito(ctx.bodega["id"], items)
                    await meta_client.send_catalogo_flow(
                        ctx.telefono,
                        ctx.bodega["id"],
                        tipo_operacion="venta",
                        load_saved_cart=True,
                        catalog_prompt=meta_client.CATALOGO_CTA_BODY_REPETIR,
                    )
                else:
                    await meta_client.send_text(
                        ctx.telefono,
                        "No tienes un pedido anterior. Escribe PEDIDO o MENU.",
                    )
        except Exception as e:
            logger.error("REPETIR handler error: %s", e, exc_info=True)
        await _mark_read(msg, meta_client)
        return True

    if btn == "ACEPTO":
        try:
            from app.config import now_peru
            from app.services.contract_generator import generate_contract

            bodega_ac = ctx.bodega
            if bodega_ac:
                bod_id = bodega_ac["id"]
                dist_nombre = "Red de distribuidores Circa"
                if bodega_ac.get("distribuidor_id"):
                    dist_r = db.sb.table("distribuidores").select("nombre_comercial").eq(
                        "id", bodega_ac["distribuidor_id"]
                    ).limit(1).execute()
                    if dist_r.data:
                        dist_nombre = dist_r.data[0]["nombre_comercial"]
                now = now_peru()
                contract_path, contract_hash = generate_contract({
                    "razon_social": bodega_ac.get("razon_social", ""),
                    "ruc": bodega_ac.get("ruc", ""),
                    "representante_legal": bodega_ac.get("representante_legal", ""),
                    "dni_representante": bodega_ac.get("dni_representante", ""),
                    "direccion_fiscal": bodega_ac.get("direccion_fiscal", ""),
                    "direccion_despacho": bodega_ac.get("direccion_despacho", ""),
                    "email": bodega_ac.get("email", ""),
                    "linea_aprobada": bodega_ac.get("linea_aprobada", 500),
                    "nombre_comercial": bodega_ac.get("nombre_comercial", ""),
                    "distribuidor_nombre": dist_nombre,
                    "telefono": ctx.telefono.replace("+51", "").replace("+", ""),
                    "fecha_firma": now.strftime("%d/%m/%Y"),
                    "hora_firma": now.strftime("%H:%M:%S"),
                })
                nombre = bodega_ac.get("nombre_comercial") or bodega_ac.get("razon_social", "Bodega")
                await meta_client.send_contract_document(ctx.telefono, contract_path, nombre)
                db.sign_contract(bod_id, contract_hash)
                import os
                try:
                    os.remove(contract_path)
                except OSError:
                    pass
                await meta_client.send_pin_request(ctx.telefono, mode="create", bodega_id=bod_id)
                db.upsert_session(ctx.telefono, "reg_pin", {"bodega_id": bod_id}, bod_id)
                logger.info("Contract signed for bodega %s, hash=%s", bod_id, contract_hash)
            else:
                await meta_client.send_text(ctx.telefono, "Error. Escribe MENU para empezar.")
        except Exception as e:
            logger.error("ACEPTO handler error: %s", e, exc_info=True)
            await meta_client.send_text(ctx.telefono, "Error al procesar. Intenta de nuevo.")
        await _mark_read(msg, meta_client)
        return True

    return False


async def handle_pin_payment_digits(
    body_text: str,
    ctx: MetaWaContext,
    msg: dict,
    meta_client,
) -> bool:
    if not body_text or len(body_text) != 4 or not body_text.isdigit():
        return False
    try:
        ses = db.sb.table("sesiones").select("fase, datos, bodega_id").eq(
            "telefono", ctx.telefono
        ).limit(1).execute()
        if not ses.data or ses.data[0].get("fase") != "pin_pago":
            return False

        datos = json.loads(ses.data[0]["datos"]) if isinstance(ses.data[0]["datos"], str) else ses.data[0]["datos"]
        bod_id = ses.data[0]["bodega_id"]
        bodega = db.sb.table("bodegas").select("pin_hash, pin_intentos").eq("id", bod_id).limit(1).execute()
        if not bodega.data:
            return True

        import bcrypt

        pin_hash = bodega.data[0].get("pin_hash", "")
        if pin_hash and bcrypt.checkpw(body_text.encode(), pin_hash.encode()):
            pedido_id = datos["pedido_id"]
            dias = int(datos.get("dias", 0) or 0)
            monto = float(datos["monto"])
            contado = float(datos.get("contado", 0) or 0)
            venc = datos.get("venc", "")

            pe = db.sb.table("pedidos").select("id, estado").eq("id", pedido_id).limit(1).execute()
            if not pe.data:
                await meta_client.send_text(ctx.telefono, "No encontramos ese pedido. Escribe MENU.")
                db.sb.table("sesiones").update({"fase": "menu", "datos": "{}"}).eq("telefono", ctx.telefono).execute()
            elif not _is_draft_status(pe.data[0].get("estado")):
                await meta_client.send_text(
                    ctx.telefono,
                    "Este pedido ya estaba confirmado. Escribe MENU si necesitas otra cosa.",
                )
                db.sb.table("sesiones").update({"fase": "menu", "datos": "{}"}).eq("telefono", ctx.telefono).execute()
            elif dias > 0:
                bod_line = db.sb.table("bodegas").select(
                    "linea_disponible, linea_aprobada"
                ).eq("id", bod_id).limit(1).execute()
                ld = float(bod_line.data[0].get("linea_disponible") or 0) if bod_line.data else 0.0
                if monto > ld + 1e-6:
                    await meta_client.send_text(
                        ctx.telefono,
                        f"⚠️ Tu tope disponible ya no alcanza (tienes S/{ld:.2f}). "
                        "Escribe MENU, arma el pedido de nuevo o elige menos financiamiento.",
                    )
                    db.sb.table("sesiones").update({"fase": "menu", "datos": "{}"}).eq("telefono", ctx.telefono).execute()
                else:
                    qfee = calculate_fee(monto, dias)
                    fee = qfee["fee"]
                    rate = qfee["rate"]
                    ped_t = db.sb.table("pedidos").select("tipo_operacion").eq("id", pedido_id).limit(1).execute()
                    tipo_op = ped_t.data[0].get("tipo_operacion", "venta") if ped_t.data else "venta"
                    num = await _gen_order_number(bod_id, tipo_op)
                    _dist_ped = db.get_distribuidor_pedido_de_bodega(bod_id)
                    db.sb.table("pedidos").update({
                        "numero": num,
                        "distribuidor_id": _dist_ped,
                        "fee_tasa": rate,
                        "fee_monto": fee,
                        "fee_regimen": fee_regimen_para_pedido_nuevo(),
                        "monto_financiado": round(monto, 2),
                        "plazo_dias": dias,
                        "monto_contado": round(contado, 2),
                        "monto_total_credito": round(monto + fee, 2),
                        "total": round(monto + fee, 2),
                        "estado": _confirmed_status_for(tipo_op),
                    }).eq("id", pedido_id).execute()
                    lap = float(bod_line.data[0].get("linea_aprobada") or ld)
                    new_ld = max(0.0, ld - monto)
                    new_ld = min(new_ld, lap)
                    db.sb.table("bodegas").update({"linea_disponible": new_ld}).eq("id", bod_id).execute()
                    db.snapshot_ultimo_pedido_venta(bod_id, pedido_id)
                    from app.services.analytics import track_event

                    track_event(
                        "order_confirmed" if tipo_op == "venta" else "preventa_confirmada",
                        bodega_id=bod_id,
                        pedido_id=pedido_id,
                        telefono=ctx.telefono,
                        source="pin_verify",
                        metadata={
                            "numero": num,
                            "tipo_operacion": tipo_op,
                            "monto_financiado": round(monto, 2),
                            "fee_monto": round(fee, 2),
                            "dias": dias,
                        },
                    )
                    track_event(
                        "credit_used",
                        bodega_id=bod_id,
                        pedido_id=pedido_id,
                        telefono=ctx.telefono,
                        source="pin_verify",
                        metadata={"monto": round(monto, 2), "dias": dias},
                    )
                    await meta_client.send_text(
                        ctx.telefono,
                        f"✅ *Pedido {num} confirmado*\n"
                        f"Financiado con Circa\n\n"
                        f"Nro: *#{num}*\n"
                        f"Financiado: *S/{monto:.2f}*\n"
                        f"Comisión Circa ({format_rate_pct(rate)}): S/{fee:.2f}\n"
                        f"Total a pagar a Circa: *S/{monto + fee:.2f}*\n"
                        f"Al distribuidor (contado): S/{contado:.2f}\n"
                        f"Plazo: {dias} días\n"
                        f"Vence: {venc}\n\n"
                        "Recibirás novedades por WhatsApp.",
                    )
                    db.clear_carrito(bod_id)
                    db.sb.table("sesiones").update({"fase": "menu", "datos": "{}"}).eq("telefono", ctx.telefono).execute()
                    logger.info("Order %s confirmed via PIN (financiado)", pedido_id)
            else:
                ped_t = db.sb.table("pedidos").select("tipo_operacion").eq("id", pedido_id).limit(1).execute()
                tipo_op = ped_t.data[0].get("tipo_operacion", "venta") if ped_t.data else "venta"
                num = await _gen_order_number(bod_id, tipo_op)
                _dist_ped = db.get_distribuidor_pedido_de_bodega(bod_id)
                db.sb.table("pedidos").update({
                    "numero": num,
                    "distribuidor_id": _dist_ped,
                    "fee_tasa": 0,
                    "fee_monto": 0,
                    "monto_financiado": 0,
                    "monto_contado": round(monto, 2),
                    "total": round(monto, 2),
                    "estado": _confirmed_status_for(tipo_op),
                }).eq("id", pedido_id).execute()
                db.snapshot_ultimo_pedido_venta(bod_id, pedido_id)
                from app.services.analytics import track_event

                track_event(
                    "order_confirmed" if tipo_op == "venta" else "preventa_confirmada",
                    bodega_id=bod_id,
                    pedido_id=pedido_id,
                    telefono=ctx.telefono,
                    source="pin_verify",
                    metadata={"numero": num, "tipo_operacion": tipo_op, "monto_contado": round(monto, 2)},
                )
                await meta_client.send_text(
                    ctx.telefono,
                    f"✅ *Pedido {num} confirmado — Contado*\n\n"
                    f"Total: S/{monto:.2f}\n"
                    "Pagas al recibir tu pedido, sin cargo extra de plazo.\n\n"
                    "Tu distribuidor preparará tu pedido.",
                )
                db.clear_carrito(bod_id)
                db.sb.table("sesiones").update({"fase": "menu", "datos": "{}"}).eq("telefono", ctx.telefono).execute()
                logger.info("Order %s confirmed via PIN (contado)", pedido_id)
        else:
            intentos = bodega.data[0].get("pin_intentos", 0) + 1
            db.sb.table("bodegas").update({"pin_intentos": intentos}).eq("id", bod_id).execute()
            if intentos >= 3:
                await meta_client.send_text(
                    ctx.telefono,
                    "❌ Demasiados intentos incorrectos.\n\n"
                    "Escribe *Me olvidé mi clave* para crear una nueva "
                    "sin perder tu pedido.\n\n"
                    "O escribe *MENU* para volver al menú.",
                )
            else:
                await meta_client.send_text(
                    ctx.telefono,
                    f"❌ Clave incorrecta. Intento {intentos}/3.\n\n"
                    "¿La olvidaste? Escribe *Me olvidé mi clave*.",
                )
        await _mark_read(msg, meta_client)
        return True
    except Exception as e:
        logger.error("PIN verify error: %s", e, exc_info=True)
        return False


async def try_handle_commerce_interactive(
    btn: str,
    body_text: str,
    ctx: MetaWaContext,
    msg: dict,
    meta_client,
) -> bool:
    """Intenta manejar botones/listas de comercio. True si consumió el mensaje."""
    handlers = (
        handle_editar,
        handle_preconf,
        handle_contado,
        handle_finfijo,
        handle_fin_pct,
        handle_menu_buttons,
        handle_pay_plazo,
    )
    for fn in handlers:
        if await fn(btn, ctx, msg, meta_client):
            return True
    if await handle_pin_payment_digits(body_text, ctx, msg, meta_client):
        return True
    return False
