"""
Sube documentos de KYC al bucket privado `dni_fotos` y actualiza bodegas.dni_foto_url.

Uso:
    python3 subir_kyc.py <bodega_id> --dni ruta/dni.jpeg [--sufragio ruta/sufragio.jpeg]
    python3 subir_kyc.py <bodega_id> --dni ruta/dni.jpeg --ejecutar

Guarda en: dni_fotos/{bodega_id}/dni_{DNI}.jpeg  y  .../sufragio_{DNI}.jpeg
Solo escribe `dni_foto_url`. No hay columna para el sufragio: queda en el bucket
junto al DNI, bajo la misma carpeta de la bodega.
"""

import os
import argparse
import mimetypes

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

sb = create_client(os.environ["SUPABASE_URL"],
                   os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_KEY"])

BUCKET = "dni_fotos"

ap = argparse.ArgumentParser()
ap.add_argument("bodega_id")
ap.add_argument("--dni", required=True, help="ruta local a la foto del DNI")
ap.add_argument("--sufragio", help="ruta local a la constancia de sufragio")
ap.add_argument("--ejecutar", action="store_true")
args = ap.parse_args()

b = sb.table("bodegas").select(
    "id,razon_social,dni_representante,dni_foto_url,kyc_nivel"
).eq("id", args.bodega_id).execute().data
if not b:
    raise SystemExit("No existe la bodega %s" % args.bodega_id)
b = b[0]

print("bodega      : %s" % b["razon_social"])
print("dni         : %s" % b["dni_representante"])
print("dni_foto_url: %s" % b["dni_foto_url"])
print("kyc_nivel   : %s" % b["kyc_nivel"])

doc = b["dni_representante"] or "sindni"
subidas = []

for etiqueta, ruta in (("dni", args.dni), ("sufragio", args.sufragio)):
    if not ruta:
        continue
    if not os.path.exists(ruta):
        raise SystemExit("No existe el archivo: %s" % ruta)
    ext = os.path.splitext(ruta)[1].lower() or ".jpeg"
    destino = "%s/%s_%s%s" % (args.bodega_id, etiqueta, doc, ext)
    ctype = mimetypes.guess_type(ruta)[0] or "image/jpeg"
    subidas.append((etiqueta, ruta, destino, ctype, os.path.getsize(ruta)))

print("\nPLAN")
for e, r, d, c, n in subidas:
    print("  %-9s %s (%d bytes) -> %s" % (e, os.path.basename(r), n, d))

if not args.ejecutar:
    raise SystemExit("\n>>> DIAGNOSTICO. Corre con --ejecutar para subir.")

url_dni = None
for etiqueta, ruta, destino, ctype, _ in subidas:
    with open(ruta, "rb") as fh:
        sb.storage.from_(BUCKET).upload(
            destino, fh.read(), {"content-type": ctype, "upsert": "true"})
    print("subido: %s" % destino)
    if etiqueta == "dni":
        url_dni = destino

if url_dni and not b["dni_foto_url"]:
    sb.table("bodegas").update({"dni_foto_url": url_dni}).eq("id", args.bodega_id).execute()
    print("dni_foto_url actualizado -> %s" % url_dni)
elif url_dni:
    print("dni_foto_url ya tenia valor (%s); NO se pisa. Revisalo a mano." % b["dni_foto_url"])

v = sb.table("bodegas").select("dni_foto_url").eq("id", args.bodega_id).execute().data[0]
print("\nVERIFICACION dni_foto_url: %s" % v["dni_foto_url"])
print("Objetos en la carpeta: %s" %
      [o["name"] for o in sb.storage.from_(BUCKET).list(args.bodega_id)])
