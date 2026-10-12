"""
Circa - Backfill de contratos PDF (v2).

Que hace:
  1. Lee `contratos` + `bodegas`.
  2. Agrupa filas por EVENTO de aceptacion (ventana de 15 min) -> los doble-insert del bot
     cuentan como un solo evento; las re-aceptaciones separadas por dias son eventos distintos.
  3. Genera un PDF por evento con la FECHA Y HORA REALES de `contratos.aceptado_at` (America/Lima).
  4. Lo sube al bucket `contratos` y escribe `url_contrato` en TODAS las filas del evento.
  5. Sella `contratos.metadata` con el rastro de lo que hizo (no pisa metadata existente).

Reglas duras:
  - Salta `bodegas.es_test = true`.
  - Salta filas que ya tienen `url_contrato`.
  - NO borra nada. El dedup de la tabla se decide aparte.
  - Si el texto que vas a renderizar no coincide con `contratos.version`, se niega a generar
    salvo que pases --acepto-discrepancia-version "<motivo>". El motivo queda en metadata.
  - Corre en simulacion salvo --ejecutar.

Uso:
    python3 circa_backfill_contratos.py --texto v3.0 \
        --acepto-discrepancia-version "db.py:102 estampaba string v2.1 hardcodeado; texto servido era v3.0"

    # revisar los PDF en ./contratos_generados/ y recien ahi:
    python3 circa_backfill_contratos.py --texto v3.0 \
        --acepto-discrepancia-version "..." --ejecutar
"""

import os
import re
import argparse
import unicodedata
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client
from circa_contrato_pdf import generar_contrato_pdf, VERSION_CONTRATO

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_KEY"]
BUCKET = "contratos"
LIMA = timezone(timedelta(hours=-5))
SALIDA = "contratos_generados"
VENTANA_EVENTO = timedelta(minutes=15)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)


_RE_TS = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(?:\.(\d+))?\s*(Z|[+-]\d{2}(?::?\d{2})?)?$")


def parse_ts(s):
    """timestamptz de Supabase -> datetime en America/Lima. Tolera +00, +0000, +00:00 y Z."""
    if not s:
        return None
    m = _RE_TS.match(s.strip())
    if not m:
        raise ValueError("timestamp no reconocido: %r" % s)
    base, frac, tz = m.group(1).replace(" ", "T"), m.group(2) or "0", m.group(3) or "+00:00"
    if tz == "Z":
        tz = "+00:00"
    elif len(tz) == 3:
        tz += ":00"
    elif ":" not in tz:
        tz = tz[:3] + ":" + tz[3:]
    dt = datetime.fromisoformat("%s.%s%s" % (base, frac[:6].ljust(6, "0"), tz))
    return dt.astimezone(LIMA)


def cargar():
    contratos = sb.table("contratos").select(
        "id,bodega_id,version,url_contrato,aceptado_at,canal,"
        "nombre_firmante,dni_firmante,metadata"
    ).order("aceptado_at", desc=False).execute().data

    ids = sorted({c["bodega_id"] for c in contratos})
    bodegas = {}
    for i in range(0, len(ids), 50):
        for b in sb.table("bodegas").select(
            "id,razon_social,nombre_comercial,ruc,representante_legal,dni_representante,"
            "direccion_fiscal,direccion_despacho,telefono_whatsapp,email_facturacion,"
            "contrato_hash,es_test"
        ).in_("id", ids[i:i + 50]).execute().data:
            bodegas[b["id"]] = b
    return contratos, bodegas


def agrupar_eventos(filas):
    """Agrupa filas de UNA bodega en eventos de aceptacion por ventana de tiempo."""
    eventos, actual = [], []
    for f in sorted(filas, key=lambda x: x["aceptado_at"]):
        ts = parse_ts(f["aceptado_at"])
        if actual and (ts - parse_ts(actual[-1]["aceptado_at"])) <= VENTANA_EVENTO:
            actual.append(f)
        else:
            if actual:
                eventos.append(actual)
            actual = [f]
    if actual:
        eventos.append(actual)
    return eventos


def construir_datos(cabecera, b):
    ts = parse_ts(cabecera["aceptado_at"])
    tel = b.get("telefono_whatsapp")
    return {
        "razon_social": b.get("razon_social") or b.get("nombre_comercial"),
        "ruc": b.get("ruc"),
        "representante_legal": b.get("representante_legal"),
        "dni": b.get("dni_representante"),
        "domicilio_fiscal": b.get("direccion_fiscal"),
        "direccion_entrega": b.get("direccion_despacho"),
        "email": b.get("email_facturacion"),
        "nombre_firmante": cabecera.get("nombre_firmante") or b.get("representante_legal"),
        "dni_firmante": cabecera.get("dni_firmante") or b.get("dni_representante"),
        "telefono": ("+51%s" % tel) if tel else None,
        "fecha_aceptacion": ts.strftime("%d/%m/%Y") if ts else None,
        "hora_aceptacion": ts.strftime("%H:%M:%S") if ts else None,
        "hash_verificacion": b.get("contrato_hash"),
    }


def slug(txt, maxlen=45):
    """Nombre legible y seguro para storage: sin tildes, sin enie, sin espacios."""
    if not txt or not str(txt).strip():
        return "SIN_NOMBRE"
    t = unicodedata.normalize("NFKD", str(txt))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("\u00d1", "N").replace("\u00f1", "n").upper()
    t = re.sub(r"[^A-Z0-9]+", "_", t).strip("_")
    return t[:maxlen].rstrip("_") or "SIN_NOMBRE"


def nombre_archivo(b, ts):
    etiqueta = b.get("razon_social") or b.get("nombre_comercial")
    return "Contrato_%s_v%s_%s.pdf" % (slug(etiqueta), VERSION_CONTRATO,
                                       ts.strftime("%Y%m%d_%H%M%S"))


def ruta_storage(bodega_id, b, ts):
    return "%s/%s" % (bodega_id, nombre_archivo(b, ts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--texto", required=True,
                    help="version del TEXTO que se va a renderizar (hoy solo v3.0)")
    ap.add_argument("--acepto-discrepancia-version", metavar="MOTIVO",
                    help="permite renderizar aunque contratos.version no coincida; queda en metadata")
    ap.add_argument("--ejecutar", action="store_true", help="escribe de verdad")
    ap.add_argument("--bodega", help="procesar solo esta bodega_id")
    ap.add_argument("--incluir-test", action="store_true", help="incluye bodegas es_test=true")
    ap.add_argument("--modo-url", choices=["path", "firmada", "publica"],
                    help="que se guarda en url_contrato. OBLIGATORIO con --ejecutar. "
                         "path = ruta del objeto (no caduca, recomendado para bucket privado); "
                         "firmada = signed URL (caduca); publica = URL publica (solo bucket publico)")
    ap.add_argument("--firmada-dias", type=int, default=3650,
                    help="vigencia de la signed URL cuando --modo-url firmada")
    args = ap.parse_args()

    if args.ejecutar and not args.modo_url:
        raise SystemExit(
            "Falta --modo-url. Bucket `contratos` es privado: usa 'path' (recomendado) o 'firmada'.")
    if args.texto.lstrip("v") != VERSION_CONTRATO:
        raise SystemExit("El generador solo produce texto v%s. Pediste %s." % (VERSION_CONTRATO, args.texto))

    os.makedirs(SALIDA, exist_ok=True)
    contratos, bodegas = cargar()

    por_bodega = {}
    for c in contratos:
        por_bodega.setdefault(c["bodega_id"], []).append(c)

    hechos, saltados, errores = [], [], []

    for bid, filas in por_bodega.items():
        if args.bodega and bid != args.bodega:
            continue
        b = bodegas.get(bid)
        etiqueta = (b or {}).get("nombre_comercial") or (b or {}).get("razon_social") or bid[:8]

        if b is None:
            errores.append((etiqueta, "bodega no encontrada"))
            continue
        if b.get("es_test") and not args.incluir_test:
            saltados.append((etiqueta, "es_test = true"))
            continue

        for evento in agrupar_eventos(filas):
            cab = evento[0]
            ts = parse_ts(cab["aceptado_at"])
            marca = ts.strftime("%d/%m %H:%M")

            if any(f.get("url_contrato") for f in evento):
                saltados.append(("%s (%s)" % (etiqueta, marca), "ya tiene url_contrato"))
                continue
            if not cab.get("nombre_firmante") or not cab.get("dni_firmante"):
                saltados.append(("%s (%s)" % (etiqueta, marca), "sin nombre/dni de firmante"))
                continue

            ver_reg = cab.get("version") or ""
            discrepa = not ver_reg.lstrip("v").startswith(VERSION_CONTRATO)
            if discrepa and not args.acepto_discrepancia_version:
                saltados.append(("%s (%s)" % (etiqueta, marca),
                                 "version registrada '%s' != texto v%s -> requiere --acepto-discrepancia-version"
                                 % (ver_reg, VERSION_CONTRATO)))
                continue

            datos = construir_datos(cab, b)
            destino = ruta_storage(bid, b, ts)
            local = os.path.join(SALIDA, destino.replace("/", "__"))
            generar_contrato_pdf(datos, local)

            estado = "SIMULADO"
            if args.ejecutar:
                try:
                    with open(local, "rb") as fh:
                        sb.storage.from_(BUCKET).upload(
                            destino, fh.read(),
                            {"content-type": "application/pdf", "upsert": "true"})

                    if args.modo_url == "path":
                        url = destino
                    elif args.modo_url == "firmada":
                        r = sb.storage.from_(BUCKET).create_signed_url(
                            destino, args.firmada_dias * 86400)
                        url = r.get("signedURL") or r.get("signedUrl")
                    else:
                        url = sb.storage.from_(BUCKET).get_public_url(destino)

                    sello = {
                        "pdf_backfill": {
                            "generado_at": datetime.now(LIMA).isoformat(),
                            "texto_version": "v%s" % VERSION_CONTRATO,
                            "version_registrada_en_fila": ver_reg,
                            "filas_del_evento": [f["id"] for f in evento],
                            "origen": "circa_backfill_contratos.py",
                            "modo_url": args.modo_url,
                            "bucket": BUCKET,
                            "objeto": destino,
                        }
                    }
                    if discrepa:
                        sello["pdf_backfill"]["discrepancia_version_motivo"] = \
                            args.acepto_discrepancia_version

                    for f in evento:
                        meta = dict(f.get("metadata") or {})
                        meta.update(sello)
                        sb.table("contratos").update(
                            {"url_contrato": url, "metadata": meta}
                        ).eq("id", f["id"]).execute()

                    estado = "OK (%d fila%s)" % (len(evento), "s" if len(evento) > 1 else "")
                except Exception as e:
                    errores.append((etiqueta, str(e)[:160]))
                    continue

            hechos.append(("%s (%s)" % (etiqueta, marca), destino, estado))

    print("\n=== EVENTOS PROCESADOS (%d) ===" % len(hechos))
    for e in hechos:
        print("  %-42s %-58s [%s]" % e)
    print("\n=== SALTADOS (%d) ===" % len(saltados))
    for e in saltados:
        print("  %-42s %s" % e)
    print("\n=== ERRORES (%d) ===" % len(errores))
    for e in errores:
        print("  %-42s %s" % e)
    if not args.ejecutar:
        print("\n>>> SIMULACION. Revisa los PDF en ./%s/ y corre con --ejecutar." % SALIDA)


if __name__ == "__main__":
    main()
