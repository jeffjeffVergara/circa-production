"""
Nombre para mensajes dirigidos al representante legal (persona), no a la marca.

Usar solo en copy conversacional (ej. pedido, selfie). No sustituye
representante_legal en contratos, SUNAT ni verificación biométrica.
"""


def nombre_para_comunicar_representante(
    bodega: dict | None,
    nombre_desde_dni: str | None = None,
) -> str:
    """
    Devuelve texto corto para saludar al bodeguero/representante, o cadena vacía.

    Prioridad: representante_nombre_corto (BD) → primera palabra del nombre RENIEC
    en sesión → primera palabra de representante_legal.
    """
    nick = ((bodega or {}).get("representante_nombre_corto") or "").replace("*", "").strip()
    if nick:
        return nick[:80]

    cand = (nombre_desde_dni or "").strip()
    if cand:
        first = cand.split()[0].replace("*", "").strip(".,;")
        if first:
            return first[:80]

    rep = ((bodega or {}).get("representante_legal") or "").strip()
    if rep:
        first = rep.split()[0].replace("*", "").strip(".,;")
        if first:
            return first[:80]

    return ""
