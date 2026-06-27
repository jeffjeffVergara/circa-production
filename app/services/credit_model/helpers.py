"""Helpers del modelo de líneas de crédito."""

from app.services.credit_model.constants import CV_IRREGULAR, PREPOSICIONES, TIERS


def tier_para(linea_7d: float) -> int:
    """Tier conservador: el mínimo (100..500) que cubre la línea de 7 días."""
    for t in TIERS:
        if linea_7d <= t:
            return t
    return 500


def titulo(texto) -> str:
    if not texto:
        return ""
    out = []
    for i, p in enumerate(str(texto).strip().split()):
        bajo = p.lower()
        out.append(bajo if (i > 0 and bajo in PREPOSICIONES) else p.capitalize())
    return " ".join(out)


def doc_info(docnum):
    d = str(docnum).strip().replace(".0", "")
    if len(d) == 11 and d.startswith("10"):
        return {"ruc": d, "dni": d[2:10], "solo_dni": False}
    if len(d) == 11:
        return {"ruc": d, "dni": None, "solo_dni": False}
    dni = d.lstrip("0") if len(d) > 8 else d
    dni = dni.zfill(8)
    if len(dni) != 8:
        raise ValueError(
            "DNI invalido, no se puede normalizar a 8 caracteres: "
            "'%s' -> '%s'. Revisa el dato en el Excel." % (docnum, dni)
        )
    return {"ruc": None, "dni": dni, "solo_dni": True}


def telefono_e164(tel) -> str:
    t = str(tel).strip().replace(" ", "").replace("-", "").replace(".0", "")
    if t.startswith("+51"):
        return t
    if t.startswith("51") and len(t) == 11:
        return "+" + t
    return "+51" + t


def primer_nombre(razon_social) -> str:
    p = str(razon_social).strip().split()
    if len(p) >= 3:
        return p[2].capitalize()
    return p[-1].capitalize() if p else ""


def normaliza_grupo(g):
    if not g:
        return None
    g = str(g).strip().upper()
    if g.startswith("CONF") and not g.startswith("CONFITERIA"):
        g = g.replace("CONF", "CONFITERIA", 1)
    return "GV - " + g


def rol_de(grupo) -> str:
    return "CONFITERIA" if "CONF" in str(grupo or "").upper() else "ABN"


def dia_min(d) -> str:
    return str(d or "").strip().lower()


def etiqueta_regularidad(a) -> str:
    cv = a.get("cv")
    if cv is None:
        return "sin datos suficientes"
    estado = "irregular" if cv > CV_IRREGULAR else "regular"
    return "%s (CV %.2f)" % (estado, cv)


def sql_str(valor) -> str:
    if valor is None:
        return "NULL"
    return "'" + str(valor).replace("'", "''") + "'"
