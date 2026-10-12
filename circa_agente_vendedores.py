#!/usr/bin/env python3
"""
CIRCA — Agente diario de vendedores (7:30 AM) · v4

Genera TRES salidas:
  1. Mensaje de GRUPO: tip + despachos + cobranzas (con @tags) + conteos
     de línea por vendedor + TOP 3 comisiones del mes + promo.
  2. Mensajes PRIVADOS (--privados): un bloque por vendedor con sus bodegas
     con línea de HOY + su avance de comisiones del mes.
  3. Mensajes SUPERVISORES (--supervisores): un bloque por supervisor con
     el total de su equipo y el ranking de sus vendedores.

Uso:
    python3 circa_agente_vendedores.py                 # mensaje de grupo
    python3 circa_agente_vendedores.py --privados      # bloques por vendedor
    python3 circa_agente_vendedores.py --supervisores  # bloques por supervisor
    python3 circa_agente_vendedores.py --copiar        # copia al clipboard (Mac)

Requiere env vars: SUPABASE_URL, SUPABASE_KEY (o .env junto al script).
Las comisiones se calculan importando calcular_comisiones() de
circa_corte_comisiones.py (v2.1+, mismo directorio) — una sola fuente de
verdad. Ventana: día 1 del mes de AYER → AYER (el día 1 muestra el mes
cerrado completo). Si el cálculo falla, el agente avisa por stderr y emite
el mensaje SIN el bloque de comisiones (nunca muere por esto).

v4 (17-jul-2026): comisiones diarias integradas + modo supervisores.
v3 (15-jul-2026): grupo compacto + privados con listas de bodegas.
"""

import os
import sys
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from supabase import create_client

# Motor canónico de comisión + mora + escalones 15/30 días (misma fuente de
# verdad que el backoffice: app/services/fees.py). Si no se puede importar,
# se cae al cálculo crudo del crédito congelado para no romper la corrida.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from app.services.fees import total_pagar_desde_pedido
except Exception:  # pragma: no cover
    total_pagar_desde_pedido = None

LIMA = ZoneInfo("America/Lima")
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DIAS_DISPLAY = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# ── Copys motivadores (EDITABLE — rotación por día: tip Circa + arenga) ────
# Tips del mensaje de grupo, ANCLADOS al día de la semana (decisión de Paola,
# 01-09-2026): el tip tiene que sentirse hecho para el día que toca — el
# "¡Buen sábado equipo!" cae sábado y el "arranquemos la semana" cae lunes.
#
# Estructura: una lista por día (índice = hoy.weekday(), lunes = 0). Dentro de
# cada día hay 2-3 tips que ROTAN SEMANA A SEMANA, para que no sea siempre el
# mismo lunes. Ver la selección en `build_grupo`.
#
# ⚠️ Antes esto era una lista plana de 7 y se elegía con `hoy.weekday()`.
# Agregar un octavo tip al final NO hacía nada: `weekday()` nunca pasa de 6,
# así que el índice 7 en adelante era código muerto — sin error, simplemente
# no se mostraba nunca. Si agregas un tip, mételo DENTRO del día que le toca.
#
# ⚠️ Un tip que menciona un día ("¡Buen sábado!") solo puede vivir en ese día.
MOTIVADORES_POR_DIA = [
    # ── Lunes ─────────────────────────────────────────────────────────────
    [
        "💡 *Tip Circa:* una bodega con línea compra MÁS en cada pedido — no depende del efectivo "
        "que tenga en caja ese día. Más pedido = más comisión para ti. 💪 ¡Arranquemos la semana con todo!",

        "💡 *Tip Circa:* si el dueño no está, la visita no tiene por qué estar perdida. 👀 Puede enrolar "
        "el familiar encargado con su autorización; pide su WhatsApp y la mejor hora para encontrarlo. "
        "📲 👉 Tu próxima visita ya empieza con ventaja.",
    ],
    # ── Martes ────────────────────────────────────────────────────────────
    [
        "💡 *Tip Circa:* las bodegas que financian piden en promedio *más del doble* que antes. "
        "Ofrecer la línea no es un favor, es hacerles crecer el negocio. 🚀 ¡Hoy a ofrecerla en cada visita!",

        "💡 *Tip Circa:* no preguntes solamente \"¿quieres usar tu línea?\". Pregunta: \"¿Qué te falta "
        "comprar hoy?\" 🛒 Primero encuentra la necesidad. Después muéstrale cómo Circa puede ayudarlo "
        "a completar su pedido. 💙",
    ],
    # ── Miércoles ─────────────────────────────────────────────────────────
    [
        "💡 *Tip Circa:* la línea es *reutilizable* — cuando la bodega paga, se libera y puede volver "
        "a financiar. Cada bodega enrolada te compra todas las semanas. 🔥 ¡Vamos por esas recompras!",

        "💡 *Tip Circa:* una bodega que ya financió una vez es una de tus mejores oportunidades de "
        "recompra. 🔄 Siempre pregúntate: ¿quién de mis clientes podría volver a pedir hoy? 💰",

        "💡 *Tip Circa:* una buena venta no termina cuando el cliente hace su primer pedido. 🎯 👉 El "
        "verdadero objetivo es que vuelva a comprar. Revisa hoy tus bodegas enroladas y busca tu "
        "próxima recompra. 🔄💰",
    ],
    # ── Jueves ────────────────────────────────────────────────────────────
    [
        "💡 *Tip Circa:* financiar cuesta desde *1.4% a 7 días* (S/1.40 por cada S/100). Menos que "
        "quedarse sin stock un fin de semana. ⭐ ¡Cuéntaselo a la bodega y cierra el pedido!",

        "💡 *Tip Circa:* cuando una bodega te diga \"no necesito crédito\", no cierres la conversación. "
        "🙅‍♂️ Respóndele: \"Perfecto. Igual puedes usar Circa: enrólate y úsalo para las promos, y si "
        "algún día te falta caja, usas tu línea.\" 😉",
    ],
    # ── Viernes ───────────────────────────────────────────────────────────
    [
        "💡 *Tip Circa:* el fin de semana es cuando la bodega más vende. Hoy es EL día para que "
        "surtan fuerte con su línea y lleguen llenos al sábado. 🏆 ¡A darle con todo!",

        "💡 *Tip Circa:* si una bodega está cerca de completar una promo, díselo. 🎁 A veces unas "
        "unidades más pueden significar un mejor beneficio para el cliente y un pedido más grande "
        "para ti. 🚀",
    ],
    # ── Sábado ────────────────────────────────────────────────────────────
    [
        "💡 *Tip Circa:* enrolar toma *5 minutos* — contrato digital + PIN por WhatsApp, sin papeles "
        "ni trámites. Una bodega enrolada hoy financia desde su próximo pedido. 💥 ¡Buen sábado equipo!",

        "💡 *Tip Circa:* antes de irte de una bodega nueva, asegúrate de que el cliente abra Circa y "
        "mande su primer mensaje. 💬 👉 Enrolar abre la puerta. Lograr que lo use es lo que queremos. 🚀",
    ],
    # ── Domingo ───────────────────────────────────────────────────────────
    [
        "💡 *Tip Circa:* la bodega no paga nada por adelantado — Circa le paga al distribuidor y "
        "ella paga después por Yape/Plin. Fácil de explicar, fácil de vender. 🙌 ¡Éxitos hoy!",

        "💡 *Tip Circa:* la confianza vende. 🤝 No presentes Circa como algo separado: explícale que es "
        "una herramienta que trabaja junto con su vendedor para que pueda comprar más fácil y hacer "
        "crecer su bodega. 🏪💙 👉 Más confianza = más uso = más ventas.",
    ],
]


def tip_del_dia(hoy: date) -> str:
    """Tip anclado al día de la semana, rotando semana a semana.

    El día manda (para que el copy calce con el día), y dentro del día se
    alterna por número de semana ISO para no repetir el mismo lunes siempre.
    """
    pool = MOTIVADORES_POR_DIA[hoy.weekday()]
    return pool[hoy.isocalendar()[1] % len(pool)]

# ── Promo del mes (EDITABLE — dejar "" para no mostrar) ────────────────────
PROMO_MES = (
    "🏆 *PREMIO INDIVIDUAL*\n"
    "El *primer* vendedor que llegue a *30 bodegas enroladas* acumuladas a "
    "octubre se lleva *S/100 adicionales* 💵\n"
    "✅ No debe tener morosos.\n"
    "\n"
    "🎉 *PREMIO A LA MESA GANADORA*\n"
    "La mesa que *más bodegas enrole* durante octubre se lleva *S/250* para "
    "celebrar con Circa 🍕🍻🥳\n"
    "¡Ustedes deciden cómo gastarlo!\n"
    "👉 *Condiciones para ganar el premio de mesa:*\n"
    "✅ Todos los vendedores de la mesa deben haber enrolado al menos 1 cliente.\n"
    "✅ La mesa debe cerrar sin clientes morosos."
)

# Tag de Washington en el grupo (EDITABLE)
TAG_WASHINGTON = "@Washington Arroyo Dimax"

# ── Recorte del mensaje de GRUPO (EDITABLE) ────────────────────────────────
# Paola pidió el 02-set-2026 acortar el grupal a partir del 03-set. Se apagan
# dos bloques; poner en True los devuelve tal cual estaban.
#   · MOSTRAR_PODIO_GRUPO: el "🏁 COMISIONES DEL MES" con el top 3. Apagarlo
#     NO afecta el cálculo de comisiones: los privados lo siguen usando.
#   · MOSTRAR_RECORDATORIO_WASHINGTON: el "⏰ Si tienen nuevos para enrolar…".
MOSTRAR_PODIO_GRUPO = False
MOSTRAR_RECORDATORIO_WASHINGTON = False

# ── Copys de comisiones (EDITABLE — Paola define el copy final) ────────────
# Arenga según el estado del vendedor. {faltan} = afiliaciones financiadas
# que le faltan ESTA semana para el bono semanal de S/10.
COMISION_ARENGAS = {
    "top":      "🏆 ¡Vas TOP del mes (bono S/20)! Nadie te alcanza todavía — no aflojes.",
    "casi_meta": "🎯 Esta semana llevas *{sem}/5 activaciones financiadas* — mantén el ritmo todas las semanas y el bono de S/10 es tuyo.",
    "meta_ok":  "✅ ¡Ritmo semanal cumplido ({sem}/5)! Sostenlo todas las semanas del mes y aseguras tu bono de S/10.",
    "en_cero":  "Aún no registras comisiones este mes. Tu primera activación financiada son *S/5 directos* — dime cuál bodega de tu ruta activamos hoy y te preparo todo. 💪",
    "retenida": "⛔ Tienes S/{venc} en espera por bodegas atrasadas — ayúdalas a ponerse al día y ese dinero se libera solo.",
    # Cubre retención de cohorte junio Y pre-junio (regla desde 01-ago-2026),
    # por eso dice "de antes" y no "de junio".
    "ret_junio": "🔁 Tus bodegas de antes siguen financiando: +S/{nivel} de retención ganados.",
}
COMISION_CIERRE = "El pago sale a fin de mes por Yape. 💙"

ESTADOS_INVALIDOS = ("cancelad", "rechazad", "expirad", "borrador")
ESTADOS_CERRADOS = ("entregado", "pagado")

# ── Concurso OCTUBRE 2026 ──────────────────────────────────────────────────
# Arrancó en setiembre (anunciado por Paola el 01-09-2026) y Paola lo renovó
# SIN CAMBIOS para octubre el 03-10-2026. Reemplaza al bono de ritmo
# (S/10 semanal) y al top del mes (S/20), que ya NO existen.
#   · Bono individual: S/100 al PRIMERO que llegue a META_BONO_INDIVIDUAL
#     bodegas enroladas ACUMULADAS (histórico total, NO del mes en curso).
#     Definición confirmada por Paola el 01-09-2026.
#     ⚠️ Por ser acumulado, el contador NO se reinicia al cambiar de mes: la
#     carrera siguió viva de setiembre a octubre porque nadie llegó a 30 (el
#     líder al 03-10 era V0011 Estrada con 16). Si alguna vez se decide
#     reiniciarlo por mes, hay que cambiar `q_enrolados_acumulados()`, no solo
#     este texto.
#   · Premio de mesa: S/250 a la mesa (= equipo del supervisor) que más
#     enrole en octubre. No se calcula en el privado del vendedor.
#
# ⚠️ EL MES ESTÁ HARDCODEADO en PROMO_MES y en el bloque 1️⃣ del privado. El
# 01-nov-2026 los mensajes volverán a decir "octubre" si nadie los actualiza.
# Revisar estos dos puntos cada cambio de mes.
META_BONO_INDIVIDUAL = 30
PREMIO_BONO_INDIVIDUAL = 100

# Estados en los que un pedido financiado YA cuenta como enrolamiento.
# Criterio v2 (CLAUDE.md): tiene que estar entregado o pagado; la preventa
# aceptada pero no entregada no cuenta.
ESTADOS_ENROLA = ("pagado", "entregado")


# ── Helpers ────────────────────────────────────────────────────────────────

def sb():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        # Fallback: leer .env junto al script (para Cowork/cron)
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            url = os.environ.get("SUPABASE_URL")
            key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("❌ Faltan SUPABASE_URL / SUPABASE_KEY (entorno o .env junto al script).")
    return create_client(url, key)


PAGE = 1000  # tope duro del servidor PostgREST (db-max-rows). .limit() NO lo sube.


def fetch_all(query_fn):
    """Trae TODAS las filas paginando con .range().

    PostgREST corta cada respuesta en 1000 filas y `.limit(n)` no levanta ese
    tope — es configuración del servidor. Sin paginar, cualquier consulta a
    `bodega_vendedores` (4640 filas activas) devuelve solo el 21% de los datos,
    en silencio. Eso hacía que bodegas reales se vieran "sin día de visita" y
    que sus cobranzas se taggearan al Admin en vez de a su vendedor.

    `query_fn` recibe (desde, hasta) y devuelve el query ya construido.
    """
    filas, off = [], 0
    while True:
        r = query_fn(off, off + PAGE - 1).execute()
        d = r.data or []
        filas.extend(d)
        if len(d) < PAGE:
            return filas
        off += PAGE


def es_estado_valido(estado: str) -> bool:
    e = (estado or "").lower()
    return not any(x in e for x in ESTADOS_INVALIDOS)


def nombre_bodega(b: dict) -> str:
    return b.get("nombre_comercial") or b.get("razon_social") or "Bodega"


def fmt_monto(m) -> str:
    try:
        f = float(m)
        return f"S/{f:,.0f}" if f == int(f) else f"S/{f:,.2f}"
    except (TypeError, ValueError):
        return "S/—"


def apellido(v: dict) -> str:
    return ((v or {}).get("nombre") or "Sin vendedor").split()[0]


def nombre_corto(v: dict) -> str:
    """'ESTRADA TRAVEZAN CARLOS ALBERTO' -> 'Estrada Carlos'.
    Asume formato ApiInti: PATERNO MATERNO NOMBRES. Con apellidos
    compuestos puede fallar — editar a mano en ese caso."""
    palabras = (((v or {}).get("nombre")) or "Sin vendedor").split()
    if len(palabras) >= 3:
        return f"{palabras[0].title()} {palabras[2].title()}"
    return " ".join(p.title() for p in palabras)


def primer_nombre(v: dict) -> str:
    """Nombre de pila para el saludo.

    Prioriza `vendedores.nombre_corto` (curado a mano) porque el heurístico
    posicional falla con apellidos compuestos:
      JAIME GARCIA CALDERON LUIS MIGUEL -> palabras[2] = 'Calderon' (mal)
      BUITRON JIMENEZ AMALIA BEATRIZ    -> palabras[2] = 'Amalia'   (mal)
    Si `nombre_corto` está en NULL, cae al heurístico de siempre.
    """
    corto = ((v or {}).get("nombre_corto") or "").strip()
    if corto:
        return corto.split()[0].title()
    palabras = (((v or {}).get("nombre")) or "").split()
    return palabras[2].title() if len(palabras) >= 3 else (
        palabras[0].title() if palabras else "")


def tag(v: dict) -> str:
    cod = (v or {}).get("codigo") or ""
    return f"@{cod} {nombre_corto(v)}".strip()


def hoy_lima() -> date:
    return datetime.now(LIMA).date()


def _fecha_cli():
    """Fecha forzada por CLI: --fecha YYYY-MM-DD o --fecha=YYYY-MM-DD.
    Blinda contra desfases del reloj del entorno (sandbox/scheduler).
    Devuelve un date, o None si no se pasó / es inválida."""
    for i, a in enumerate(sys.argv):
        val = None
        if a.startswith("--fecha="):
            val = a.split("=", 1)[1]
        elif a == "--fecha" and i + 1 < len(sys.argv):
            val = sys.argv[i + 1]
        if val:
            try:
                return date.fromisoformat(val.strip())
            except ValueError:
                print(f"⚠️  --fecha inválida: {val!r} (usa YYYY-MM-DD). "
                      f"Se ignora y se usa el reloj del sistema.", file=sys.stderr)
                return None
    return None


def agrupar(items, get_v):
    """{ (codigo, nombre) : [items] } ordenado por código."""
    grupos = {}
    for it in items:
        v = get_v(it) or {}
        grupos.setdefault((v.get("codigo") or "ZZZ", v.get("nombre") or "Sin vendedor"),
                          []).append(it)
    return dict(sorted(grupos.items()))


# ── Comisiones del mes (motor compartido con el corte) ────────────────────

def stats_comisiones(hoy: date):
    """Corre calcular_comisiones() con ventana: día 1 del mes de AYER → AYER.
    Devuelve dict o None si el cálculo no fue posible (avisa por stderr).

    Estructura devuelta:
      por_codigo: {codigo: {"v", "mat", "vuelo", "venc", "afil", "rec",
                            "metas", "afil_sem_actual", "es_top"}}
      supervisores: {nombre_sup: [codigos ordenados por mat+vuelo desc]}
      top3: [(codigo, mat+vuelo)] los 3 primeros con actividad
      desde, hasta
    """
    ayer = hoy - timedelta(days=1)
    desde = ayer.replace(day=1)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from circa_corte_comisiones import calcular_comisiones
        url = (os.environ.get("SUPABASE_URL") or os.environ.get("CIRCA_SUPABASE_URL") or "").rstrip("/")
        key = os.environ.get("SUPABASE_KEY") or os.environ.get("CIRCA_SUPABASE_KEY") or ""
        if not url or not key:
            raise RuntimeError("sin credenciales Supabase para comisiones")
        r = calcular_comisiones(url, key, desde, ayer, hoy=hoy, verbose=False)
    except (Exception, SystemExit) as exc:
        print(f"\n⚠️  Comisiones NO disponibles hoy ({exc}). El mensaje sale sin "
              f"ese bloque — revisar circa_corte_comisiones.py.", file=sys.stderr)
        return None

    sem_actual = hoy.isocalendar()[:2]
    # v5: detalle línea por línea agrupado por vendedor, para el privado.
    # Cada fila de r["detalle"] es:
    #   (supervisor, codigo, bodega, nro_pedido, fecha, concepto, monto, estado)
    detalle_cod = {}
    for fila in r.get("detalle") or []:
        try:
            _sup, _cod, _bod, _num, _fec, _con, _mon, _est = fila
        except (ValueError, TypeError):
            continue
        detalle_cod.setdefault(_cod, []).append(
            {"bodega": _bod, "pedido": _num, "fecha": _fec,
             "concepto": _con, "monto": float(_mon or 0), "estado": _est})

    por_codigo, supervisores = {}, {}
    for v in r["vendedores"]:
        vid = v["id"]
        st = {
            "v": v,
            "mat": round(r["paga"][vid]["MAT"], 2),
            "vuelo": round(r["paga"][vid]["VUELO"], 2),
            "venc": round(r["paga"][vid]["VENC"], 2),
            "afil": r["cnt"][vid]["afiliacion_financiada"] + r["cnt"][vid]["afiliacion_cash"],
            "afil_fin": r["cnt"][vid]["afiliacion_financiada"],
            "afil_cash": r["cnt"][vid]["afiliacion_cash"],
            "rec": r["cnt"][vid]["recompra_financiada"],
            "metas": r["cnt"][vid]["metas_semanales"],
            "afil_sem_actual": r["afil_sem"][vid].get(sem_actual, 0),
            "es_top": vid == r["top_vid"],
            "ret_junio": r["cnt"][vid]["retencion_junio"],
            # v5: retención de cohorte pre-junio (regla nueva desde 01-ago-2026).
            "ret_prejunio": r["cnt"][vid]["retencion_prejunio"],
            "sem_cumplidas": r["cnt"][vid]["semanas_cumplidas"],
            "sem_evaluadas": r["cnt"][vid]["semanas_evaluadas"],
            "detalle": detalle_cod.get(v["codigo"], []),
        }
        por_codigo[v["codigo"]] = st
        supervisores.setdefault((v.get("supervisor") or "SIN SUPERVISOR").strip() or "SIN SUPERVISOR",
                                []).append(v["codigo"])
    for sup in supervisores:
        supervisores[sup].sort(key=lambda c: -(por_codigo[c]["mat"] + por_codigo[c]["vuelo"]))

    con_actividad = [(c, s["mat"] + s["vuelo"]) for c, s in por_codigo.items()
                     if s["mat"] + s["vuelo"] > 0]
    top3 = sorted(con_actividad, key=lambda x: -x[1])[:3]

    # v5: cuántas bodegas le faltan a cada uno para alcanzar al líder de
    # enrolamientos — el criterio real del bono top es CANTIDAD de bodegas
    # enroladas (financiadas + cash), no soles.
    max_afil = max((s["afil"] for s in por_codigo.values()), default=0)
    for s in por_codigo.values():
        s["falta_top"] = max(max_afil - s["afil"], 0)

    if r["alertas"]:
        print(f"\n⚠️  Comisiones: {len(r['alertas'])} pedido(s) sin atribuir "
              f"(no suman a nadie hasta resolverse) — ver corte semanal.", file=sys.stderr)
    return {"por_codigo": por_codigo, "supervisores": supervisores,
            "top3": top3, "desde": desde, "hasta": ayer}


def _fdia(f) -> str:
    """Fecha corta dd/mm para las líneas de detalle."""
    try:
        return f"{f.day:02d}/{f.month:02d}"
    except AttributeError:
        s = str(f or "")
        return f"{s[8:10]}/{s[5:7]}" if len(s) >= 10 else s


def bloque_comision_vendedor(st, hasta: date) -> list:
    """Líneas del bloque de comisiones para el privado de un vendedor.

    v5 (24-ago-2026): agrega el detalle del mes bodega por bodega —
    activaciones con su S/, comisión retenida con nombre y motivo, y avance
    real hacia el bono de ritmo y el top. La idea es poder reenviar el
    privado tal cual, sin abrir el Excel del corte.
    """
    L = [f"💰 *TU AVANCE DEL MES* (al {hasta.day:02d}/{hasta.month:02d})"]
    if st["mat"] + st["vuelo"] + st["venc"] == 0:
        L.append(f"  {COMISION_ARENGAS['en_cero']}")
        return L

    det = st.get("detalle") or []

    L.append(f"  ✅ *{fmt_monto(st['mat'])}* confirmados a pagar")
    if st["vuelo"]:
        L.append(f"  🕐 {fmt_monto(st['vuelo'])} en camino (se confirman cuando la bodega paga)")

    # ── Detalle 1: bodegas que activó este mes, una por una ───────────────
    # OJO: las filas con "(arrastre)" son activaciones de un mes ANTERIOR
    # cuya comisión recién se liberó ahora porque la bodega pagó. No van en
    # esta lista (la fecha delataría el mes viejo); van en su propia línea.
    def _es_activacion(d):
        c = (d.get("concepto") or "").lower()
        return "afiliacion" in c or "activacion" in c

    act = [d for d in det
           if _es_activacion(d) and "arrastre" not in (d.get("concepto") or "").lower()]
    act.sort(key=lambda d: str(d.get("fecha") or ""))
    if act:
        L.append("")
        L.append(f"  🆕 *BODEGAS QUE ACTIVASTE ESTE MES* ({len(act)})")
        for d in act:
            pago = fmt_monto(d["monto"]) if d["monto"] else "S/0 (no paga)"
            L.append(f"     · {d['bodega']} · {_fdia(d['fecha'])} · {pago}")

    arr = [d for d in det if "arrastre" in (d.get("concepto") or "").lower()]
    if arr:
        tot_arr = sum(float(d.get("monto") or 0) for d in arr)
        L.append("")
        L.append(f"  🔓 *LIBERADO DE MESES ANTERIORES: {fmt_monto(tot_arr)}* — "
                 f"bodegas que por fin pagaron:")
        for d in sorted(arr, key=lambda x: str(x.get("fecha") or "")):
            L.append(f"     · {d['bodega']} · activada {_fdia(d['fecha'])} · {fmt_monto(d['monto'])}")
        L.append("     Cobrar funciona: esa plata estaba detenida y ya es tuya. 🙌")

    # ── Resumen de recompras / retención ──────────────────────────────────
    partes = []
    if st["rec"]:
        partes.append(f"{st['rec']} recompra(s) financiada(s)")
    if st["metas"]:
        partes.append("bono mensual de ritmo")
    if partes:
        L.append(f"  📈 {' · '.join(partes)}")
    ret_ant = st.get("ret_junio", 0) + st.get("ret_prejunio", 0)
    if ret_ant:
        L.append(f"  {COMISION_ARENGAS['ret_junio'].format(nivel=ret_ant)}")

    # ── Detalle 2: comisión retenida, con nombre y motivo ─────────────────
    if st["venc"]:
        # Una bodega puede tener varias comisiones retenidas (p. ej. tres
        # recompras de S/1). Se agrupan por bodega para no repetir el nombre.
        por_bodega = {}
        for d in det:
            if (d.get("estado") or "").upper() != "VENC":
                continue
            b = d["bodega"]
            acc = por_bodega.setdefault(b, {"monto": 0.0, "n": 0})
            acc["monto"] += float(d.get("monto") or 0)
            acc["n"] += 1
        L.append("")
        L.append(f"  ⛔ *EN ESPERA: {fmt_monto(st['venc'])}* — retenidos por bodegas atrasadas:")
        for b, acc in sorted(por_bodega.items(), key=lambda x: -x[1]["monto"]):
            detalle_n = f" ({acc['n']} comisiones)" if acc["n"] > 1 else ""
            L.append(f"     · {b} · {fmt_monto(acc['monto'])}{detalle_n}")
        L.append("     Ese dinero ya es tuyo: se libera solo apenas se pongan al día. 💪")

    # ── Detalle 3: avance a meta de ritmo y al top del mes ────────────────
    L.append("")
    sem_ok, sem_ev = st.get("sem_cumplidas"), st.get("sem_evaluadas")
    if sem_ok is not None and sem_ev:
        L.append(f"  🎯 *Bono de ritmo (S/10):* {sem_ok}/{sem_ev} semanas del mes con 5+ activaciones.")
        if sem_ok == sem_ev:
            L.append(f"     Vas cumpliendo todas. Esta semana llevas {st['afil_sem_actual']}/5 — sostenlo.")
        else:
            L.append(f"     El bono pide TODAS las semanas completas. Esta semana llevas "
                     f"{st['afil_sem_actual']}/5.")
    elif st["afil_sem_actual"] >= 5:
        L.append(f"  {COMISION_ARENGAS['meta_ok'].format(sem=st['afil_sem_actual'])}")
    else:
        L.append(f"  {COMISION_ARENGAS['casi_meta'].format(sem=st['afil_sem_actual'])}")

    if st["es_top"]:
        L.append(f"  {COMISION_ARENGAS['top']}")
    else:
        falta = st.get("falta_top")
        if falta:
            L.append(f"  🏆 *Top del mes (S/20):* llevas {st['afil']} bodega(s) enrolada(s); "
                     f"te faltan *{falta}* para alcanzar al primero.")
        else:
            L.append(f"  🏆 *Top del mes (S/20):* llevas {st['afil']} bodega(s) enrolada(s).")

    L.append(f"  {COMISION_CIERRE}")
    return L


# ── Consultas ──────────────────────────────────────────────────────────────

def q_despachos_pendientes(client, hoy: date):
    """Pedidos confirmados de los últimos 10 días aún NO entregados."""
    desde = (hoy - timedelta(days=10)).isoformat()
    r = (
        client.table("pedidos")
        .select("numero,bodega_id,total_pedido,monto_financiado,estado,created_at,"
                "entregado_at,fecha_entregado,"
                "bodegas!inner(nombre_comercial,razon_social,es_test),"
                "vendedores(nombre,nombre_corto,codigo,es_admin)")
        .gte("created_at", desde)
        .execute()
    )
    out = []
    for p in r.data or []:
        if (p.get("bodegas") or {}).get("es_test") is True:
            continue  # solo excluir test explícito; NULL = bodega real
        if not p.get("numero"):
            continue
        if p.get("entregado_at") or p.get("fecha_entregado"):
            continue
        e = str(p.get("estado") or "").lower()
        if not es_estado_valido(e) or any(x in e for x in ESTADOS_CERRADOS):
            continue
        out.append(p)
    return sorted(out, key=lambda x: x.get("created_at") or "")


def q_cobranza(client, hoy: date):
    """Pedidos financiados vencidos, que vencen hoy o mañana, sin pago."""
    manana = (hoy + timedelta(days=1)).isoformat()
    r = (
        client.table("pedidos")
        .select("id,numero,bodega_id,fecha_vencimiento,monto_total_credito,monto_financiado,fee_monto,"
                "plazo_dias,fecha_entregado,confirmado_at,created_at,"
                "pagado_at,fecha_pagado,estado,"
                "bodegas!inner(nombre_comercial,razon_social,es_test),"
                "vendedores(nombre,nombre_corto,codigo,es_admin)")
        .lte("fecha_vencimiento", manana)
        .gt("monto_financiado", 0)
        .execute()
    )
    out = []
    for p in r.data or []:
        if (p.get("bodegas") or {}).get("es_test") is True:
            continue
        if p.get("pagado_at") or p.get("fecha_pagado"):
            continue
        e = str(p.get("estado") or "").lower()
        if "pagado" in e or not es_estado_valido(e):
            continue
        out.append(p)
    _adjuntar_abonos(client, out)
    return sorted(out, key=lambda x: x.get("fecha_vencimiento") or "")


def _adjuntar_abonos(client, pedidos):
    """Cuelga en cada pedido sus abonos vigentes como `_abonos`.

    ⚠️ total_pagar_desde_pedido() ya sabe descontar pagos parciales, pero los
    busca con _abonos_de_pedido(), que usa app.services.db.sb — un cliente que
    SOLO existe dentro de la app Flask. Desde este script revienta con
    "supabase_key is required" y su `except Exception: return []` se traga el
    error y responde "sin abonos": la cobranza sale por el total completo sin
    ningún aviso. Por eso los traemos con NUESTRO cliente y los pasamos
    explícitos con abonos=...
    [Confirmado 22-sep-2026: RABANAL CRC-205 decía S/106 debiendo S/56 tras
     abonar S/50; AVILA CRC-240 decía S/51.50 debiendo S/1.]
    """
    ids = [p["id"] for p in pedidos if p.get("id")]
    if not ids:
        return pedidos
    por_pedido = {}
    for i in range(0, len(ids), 200):  # en lotes: el tope de 1000 es del servidor
        r = (client.table("abonos").select("pedido_id,monto,fecha_pago")
             .in_("pedido_id", ids[i:i + 200]).eq("anulado", False).execute())
        for a in r.data or []:
            por_pedido.setdefault(a["pedido_id"], []).append(
                {"monto": a["monto"], "fecha_pago": a["fecha_pago"]})
    for p in pedidos:
        p["_abonos"] = por_pedido.get(p.get("id")) or []
    return pedidos


def abonado_de(p) -> float:
    """Cuánto abonó ya la bodega a cuenta de este pedido."""
    return sum(float(a.get("monto") or 0) for a in (p.get("_abonos") or []))


def q_visitas_hoy(client, dia: str):
    """Mapeos activos con dia_visita = hoy, con datos de línea de la bodega.
    Devuelve (con_linea, pre_aprobadas) ya clasificadas y sin duplicados."""
    filas = fetch_all(lambda a, b: (
        client.table("bodega_vendedores")
        .select("dia_visita,vendedores(nombre,nombre_corto,codigo,celular),"
                "bodegas!inner(id,nombre_comercial,razon_social,"
                "linea_aprobada,linea_disponible,pin_hash,contrato_firmado_at,"
                "es_test,en_piloto)")
        .eq("activo", True)
        .eq("dia_visita", dia)
        .range(a, b)
    ))
    con_linea, pre_aprobadas, vistos = [], [], set()
    for m in filas:
        b = m.get("bodegas") or {}
        if b.get("es_test") is True:
            continue
        if b.get("id") in vistos:
            continue
        vistos.add(b.get("id"))
        enrolada = bool(b.get("pin_hash")) and bool(b.get("contrato_firmado_at"))
        if enrolada and float(b.get("linea_disponible") or 0) > 0:
            con_linea.append(m)
        elif not enrolada and float(b.get("linea_aprobada") or 0) > 0:
            pre_aprobadas.append(m)
    return con_linea, pre_aprobadas


def q_lineas_aprobadas_por_vendedor(client):
    """Bodegas con línea aprobada por vendedor (para el detalle del supervisor).

    Devuelve {codigo: {"nueva": [(nombre, monto)], "recompra": [(nombre, monto)]}}
      · nueva     = bodega NO enrolada con linea_aprobada>0 (línea por colocar)
      · recompra  = bodega enrolada con linea_disponible>0 (línea reutilizable)
    Excluye bodegas es_test=True. Dedup por (vendedor, bodega)."""
    filas = fetch_all(lambda a, b: (
        client.table("bodega_vendedores")
        .select("vendedores(codigo),bodegas!inner(nombre_comercial,razon_social,"
                "linea_aprobada,linea_disponible,pin_hash,contrato_firmado_at,es_test)")
        .eq("activo", True)
        .range(a, b)
    ))
    out, seen = {}, set()
    for m in filas:
        b = m.get("bodegas") or {}
        if b.get("es_test") is True:
            continue
        cod = (m.get("vendedores") or {}).get("codigo")
        nom = b.get("nombre_comercial") or b.get("razon_social")
        if not cod or not nom or (cod, nom) in seen:
            continue
        seen.add((cod, nom))
        la = float(b.get("linea_aprobada") or 0)
        ld = float(b.get("linea_disponible") or 0)
        enrol = bool(b.get("pin_hash")) and bool(b.get("contrato_firmado_at"))
        d = out.setdefault(cod, {"nueva": [], "recompra": []})
        if not enrol and la > 0:
            d["nueva"].append((nom, la))
        elif enrol and ld > 0:
            d["recompra"].append((nom, ld))
    for cod in out:
        out[cod]["nueva"].sort(key=lambda x: -x[1])
        out[cod]["recompra"].sort(key=lambda x: -x[1])
    return out


def q_mapa_vendedores(client):
    """bodega_id -> vendedor de cartera (prefiere rol ABN sobre legacy)."""
    filas = fetch_all(lambda a, b: (
        client.table("bodega_vendedores")
        .select("bodega_id,rol,vendedores(nombre,codigo)")
        .eq("activo", True)
        .range(a, b)
    ))
    mapa = {}
    for m in filas:
        bid, v = m.get("bodega_id"), m.get("vendedores")
        if not bid or not v:
            continue
        if bid not in mapa or (m.get("rol") == "ABN"):
            mapa[bid] = v
    return mapa


def asignar_vendedor_cartera(pedidos, mapa):
    """La bodega SIEMPRE pertenece a su vendedor de cartera (bodega_vendedores).
    El vendedor grabado en el pedido no es fuente de verdad: las preventas las
    sube el admin, así que ese campo puede quedar como ADMIN o como quien la
    cargó. Para despachos y cobranzas taggear siempre al vendedor de cartera
    de la bodega — es quien la visita y cobra. Solo se respeta el vendedor del
    pedido cuando la bodega no tiene cartera mapeada (fallback)."""
    for p in pedidos:
        cartera = mapa.get(p.get("bodega_id"))
        if cartera:
            p["vendedores"] = cartera
    return pedidos


def q_enrolados_acumulados(client, mapa):
    """Bodegas enroladas ACUMULADAS (histórico completo) por vendedor.

    Alimenta el bono individual de S/100 del concurso (setiembre→octubre 2026).
    Una bodega cuenta UNA sola vez, sin importar cuántos pedidos financiados
    tenga. El conteo es histórico completo y NO se reinicia por mes.

    Criterio: la bodega tiene que estar ENROLADA **Y** haber FINANCIADO — las
    dos cosas (definición confirmada por Paola el 01-09-2026, misma vara que
    la comisión de S/5).
      · contrato_firmado_at IS NOT NULL  ← enrolada. Sin esto no cuenta aunque
        haya financiado: pasa con SANTA CRUZ CARRASCO (CRC-069, S/89 pagados
        por Yape en julio, sin contrato registrado). Era la única diferencia
        contra el Excel de control de Paola del 01-09-2026.
      · monto_financiado > 0
      · estado ∈ ESTADOS_ENROLA (entregado o pagado). `pagado_cash` NO entra:
        la comparación es exacta, no por substring.
      · metodo_pago != 'efectivo' — el financiamiento se anuló aunque el
        pedido conserve el monto (caso CRC-184).
      · bodega no es de test.

    La atribución va por `mapa` (bodega_vendedores, vendedor de cartera), NO
    por el vendedor grabado en el pedido: las preventas las sube el admin y ese
    campo puede quedar como ADMIN.

    Devuelve {codigo: {"n": int, "bodegas": set(nombres)}}.
    """
    filas = fetch_all(lambda a, b: (
        client.table("pedidos")
        .select("bodega_id,estado,metodo_pago,monto_financiado,"
                "bodegas!inner(nombre_comercial,razon_social,es_test,"
                "contrato_firmado_at)")
        .gt("monto_financiado", 0)
        .range(a, b)
    ))
    por_bodega = {}
    for p in filas:
        b = p.get("bodegas") or {}
        if b.get("es_test") is True:
            continue
        if not b.get("contrato_firmado_at"):
            continue  # financió pero NUNCA firmó contrato → no está enrolada
        if str(p.get("estado") or "").lower() not in ESTADOS_ENROLA:
            continue
        if str(p.get("metodo_pago") or "").lower() == "efectivo":
            continue
        bid = p.get("bodega_id")
        if bid:
            por_bodega[bid] = nombre_bodega(b)

    # ⚠️ El crédito de enrolamiento NO se hereda [regla de Paola, 01-09-2026].
    # Cuando una zona cambia de vendedor, la cartera se reasigna pero la meta
    # del bono NO viaja con las bodegas: el que entra arranca en cero y solo
    # cobra S/1 por las recompras de lo que heredó.
    #
    # Por eso NO se puede atribuir por `mapa` (la cartera viva): después del
    # cambio de zonas de setiembre eso le daría a Horna las 6 de Amaro.
    # `enrolamiento_credito` congela quién enroló cada bodega. Manda esa tabla;
    # el mapa actual es solo el fallback para bodegas enroladas DESPUÉS del
    # congelamiento, que sí le tocan a su vendedor de hoy.
    credito = {}
    try:
        for f in fetch_all(lambda a, b: (
            client.table("enrolamiento_credito")
            .select("bodega_id,codigo_vendedor").range(a, b)
        )):
            credito[f["bodega_id"]] = f["codigo_vendedor"]
    except Exception as exc:                       # tabla aún no creada
        print(f"\n⚠️  Sin `enrolamiento_credito` ({exc}). El acumulado sale por "
              f"cartera actual y las bodegas heredadas se le van a contar al "
              f"vendedor equivocado.", file=sys.stderr)

    out = {}
    for bid, nom in por_bodega.items():
        cod = credito.get(bid) or (mapa.get(bid) or {}).get("codigo")
        if not cod:
            continue
        d = out.setdefault(cod, {"n": 0, "bodegas": set()})
        d["bodegas"].add(nom)
    for cod in out:
        out[cod]["n"] = len(out[cod]["bodegas"])
    return out


def q_panorama_linea(client, dia: str):
    """Todas las bodegas con linea_disponible > 0 y su situación de visita.
    Devuelve (otros_dias, huerfanas): cuántas se visitan otro día y cuáles
    no tienen día/mapeo/piloto — esas jamás saldrían en el reporte."""
    rb = (
        client.table("bodegas")
        .select("id,nombre_comercial,razon_social,linea_disponible,en_piloto,es_test")
        .gt("linea_disponible", 0)
        .execute()
    )
    bodegas = [b for b in (rb.data or []) if b.get("es_test") is not True]
    if not bodegas:
        return 0, []
    rm = fetch_all(lambda a, b: (
        client.table("bodega_vendedores")
        .select("bodega_id,dia_visita")
        .eq("activo", True)
        .range(a, b)
    ))
    dias_por_bodega = {}
    for m in rm:
        if m.get("dia_visita"):
            dias_por_bodega.setdefault(m["bodega_id"], set()).add(m["dia_visita"])
    otros_dias, huerfanas = 0, []
    for b in bodegas:
        dias_b = dias_por_bodega.get(b["id"], set())
        if not dias_b:
            huerfanas.append(f"{nombre_bodega(b)} (sin día de visita)")
        elif dia not in dias_b:
            otros_dias += 1
    return otros_dias, huerfanas


# ── 1. Mensaje de GRUPO ────────────────────────────────────────────────────

def build_grupo(hoy: date, despachos, cobranza, con_linea, pre_aprobadas,
                otros_dias=0, comisiones=None) -> str:
    dia_idx = hoy.weekday()
    L = [f"¡Buenos días a todos! ☀️ *CIRCA — {DIAS_DISPLAY[dia_idx]} "
         f"{hoy.day:02d}/{hoy.month:02d}*", ""]
    L.append(tip_del_dia(hoy))
    L.append("")

    # 🚚 Despachos — agrupado por vendedor (tag corto), monto financiado explícito
    L.append("🚚 *DESPACHOS PENDIENTES DE ENTREGA*")
    if despachos:
        for (cod, nom), items in agrupar(despachos, lambda p: p.get("vendedores")).items():
            L.append(tag(items[0].get("vendedores")))
            for p in items:
                b = p.get("bodegas") or {}
                fin_txt = ""
                mf = float(p.get("monto_financiado") or 0)
                if mf > 0:
                    fin_txt = f" 💳 Circa financia {fmt_monto(mf)}"
                L.append(f"  📦 {nombre_bodega(b)} · {p.get('numero')} · "
                         f"{fmt_monto(p.get('total_pedido'))}{fin_txt}")
    else:
        L.append("  ✅ Sin despachos pendientes")
    L.append("")

    # 💰 Cobranzas — lista plana, tag del vendedor al final de cada línea
    L.append("💰 *COBRANZAS* (vencidos y por vencer)")
    if cobranza:
        for p in cobranza:
            b = p.get("bodegas") or {}
            # Saldo vigente: fee con true-up 15/30 + mora híbrida 0.03%/día,
            # YA neto de abonos (pagos parciales), igual que el backoffice.
            monto = _cobranza_monto(p, hoy)
            try:
                dias = (hoy - date.fromisoformat(p.get("fecha_vencimiento") or "")).days
            except ValueError:
                dias = 0
            if dias > 1:
                icon, est = "🔴", f"({dias} días vencido 🚨)"
            elif dias == 1:
                icon, est = "🔴", "(1 día vencido 🚨)"
            elif dias == 0:
                icon, est = "🟡", "(vence *HOY*)"
            else:
                icon, est = "🟢", "(vence mañana)"
            ab = abonado_de(p)
            parcial = f" · ya abonó {fmt_monto(ab)} 🧾" if ab else ""
            L.append(f"  {icon} {nombre_bodega(b)} → {fmt_monto(monto)}{parcial} {est} "
                     f"{tag(p.get('vendedores'))}")
    else:
        L.append("  ✅ Nadie debe pagar 🎉")
    L.append("")

    # 💳 Línea — sin listas: el detalle va por privado
    L.append("💳 *VISITAS DE HOY CON LÍNEA LISTA Y CON LÍNEA APROBADA* (¡que financien!)")
    total_linea = len(con_linea) + len(pre_aprobadas)
    if total_linea:
        L.append("  📲 En privado les mandamos el detalle de cada una")
    else:
        L.append("  — Ninguna programada hoy")
    L.append("")

    # 🏁 Comisiones — top 3 del mes (competencia sana; el detalle va privado)
    if MOSTRAR_PODIO_GRUPO and comisiones and comisiones["top3"]:
        medallas = ["🥇", "🥈", "🥉"]
        podio = " · ".join(
            f"{medallas[i]} {apellido(comisiones['por_codigo'][cod]['v'])} {fmt_monto(m)}"
            for i, (cod, m) in enumerate(comisiones["top3"]))
        L.append(f"🏁 *COMISIONES DEL MES* (ganado + en camino)")
        L.append(f"  {podio}")
        L.append("  📲 Tu avance personal va en tu privado 💰")
        L.append("")

    if MOSTRAR_RECORDATORIO_WASHINGTON:
        L.append(f"  ⏰ Si tienen *nuevos para enrolar*, envíenlos LO MÁS TEMPRANO que "
                 f"puedan para que {TAG_WASHINGTON} nos ayude 🙏")
        L.append("")

    if PROMO_MES:
        L.append(PROMO_MES)
        L.append("")
    L.append("¡Vamos equipo! 💙")
    return "\n".join(L)


# ── 2. Mensajes PRIVADOS (bodegas de hoy + avance de comisiones) ──────────

def _cobranza_monto(p, hoy: date):
    """Total a pagar de un pedido, idéntico al mensaje de grupo."""
    if total_pagar_desde_pedido is not None:
        return total_pagar_desde_pedido(
            p, hoy=hoy, abonos=(p.get("_abonos") or None))["total_pagar"]
    return (p.get("monto_total_credito") or (
        (p.get("monto_financiado") or 0) + (p.get("fee_monto") or 0))) - abonado_de(p)


def _cobranza_estado(p, hoy: date):
    """(icono, texto de estado) de un pedido, idéntico al mensaje de grupo."""
    try:
        dias = (hoy - date.fromisoformat(p.get("fecha_vencimiento") or "")).days
    except ValueError:
        dias = 0
    if dias > 1:
        return "🔴", f"({dias} días vencido 🚨)"
    if dias == 1:
        return "🔴", "(1 día vencido 🚨)"
    if dias == 0:
        return "🟡", "(vence *HOY*)"
    return "🟢", "(vence mañana)"


def build_privados(hoy: date, con_linea, pre_aprobadas, cobranza=None,
                   comisiones=None, acumulados=None) -> str:
    """Un bloque por vendedor, en las 3 partes que pidió Paola (01-09-2026):

      1️⃣  cuántas bodegas enroladas lleva y cuánto le falta para el bono
          individual de S/100 (META_BONO_INDIVIDUAL acumuladas)
      2️⃣  las bodegas que tiene por cobrar
      3️⃣  las bodegas que tiene por enrolar o financiar

    La línea '>>> PARA:' es guía con link directo al chat — NO se pega.

    v6 (01-09-2026): se REEMPLAZA el bloque largo de comisiones por la parte
    1️⃣. El bono de ritmo (S/10) y el top del mes (S/20) ya no existen: los
    sustituyó el concurso (setiembre→octubre). `bloque_comision_vendedor()` queda
    intacta porque la sigue usando el modo --supervisores.
    """
    g_cl = agrupar(con_linea, lambda m: m.get("vendedores"))
    g_pa = agrupar(pre_aprobadas, lambda m: m.get("vendedores"))
    g_co = agrupar(cobranza or [], lambda p: p.get("vendedores"))

    claves = set(g_cl) | set(g_pa) | set(g_co)
    por_codigo = (comisiones or {}).get("por_codigo", {})
    cods_con_visita = {cod for cod, _ in claves}
    for cod, st in por_codigo.items():
        if cod in cods_con_visita:
            continue
        if st["mat"] + st["vuelo"] + st["venc"] > 0:
            claves.add((cod, st["v"].get("nombre") or ""))

    bloques = []
    for key in sorted(claves):
        cod, _ = key
        # Vendedor: preferir la fuente con celular (visitas) para el link.
        if g_cl.get(key):
            v = g_cl[key][0].get("vendedores") or {}
        elif g_pa.get(key):
            v = g_pa[key][0].get("vendedores") or {}
        elif cod in por_codigo:
            v = por_codigo[cod]["v"]  # vendedor sin visitas hoy, con comisiones
        else:
            v = g_co[key][0].get("vendedores") or {}  # solo cobranza hoy
        cel = (v.get("celular") or "").replace("+", "").replace(" ", "")
        link = f" · wa.me/{cel}" if cel else ""
        cabecera = f">>> PARA: {cod} · {nombre_corto(v)}{link}"

        L = [f"Hola {primer_nombre(v)}!"]

        # ── 1️⃣ Enroladas acumuladas + avance al bono individual ───────────
        acum = (acumulados or {}).get(cod) or {}
        n_acum = int(acum.get("n") or 0)
        falta = max(META_BONO_INDIVIDUAL - n_acum, 0)
        L.append("")
        L.append("1️⃣ *TUS BODEGAS ENROLADAS*")
        L.append(f"  🏪 Llevas *{n_acum}* bodega(s) enrolada(s) en total")
        if falta == 0:
            L.append(f"  🏆 *¡Ya llegaste a {META_BONO_INDIVIDUAL}!* Si eres el "
                     f"primero y sin morosos, los "
                     f"*{fmt_monto(PREMIO_BONO_INDIVIDUAL)}* son tuyos 🎉")
        else:
            L.append(f"  🎯 Vas *{n_acum}/{META_BONO_INDIVIDUAL}* en la carrera "
                     f"por los *{fmt_monto(PREMIO_BONO_INDIVIDUAL)}* — se lo "
                     f"lleva el primero, y sin morosos.")
        L.append(f"  📅 Es *acumulado a octubre*: cuentan las que enrolaste "
                 f"en meses anteriores.")
        st = por_codigo.get(cod)
        if st and (st["mat"] + st["vuelo"]) > 0:
            linea = f"  💰 Este mes: *{fmt_monto(st['mat'])}* confirmados"
            if st["vuelo"]:
                linea += f" · {fmt_monto(st['vuelo'])} en camino"
            L.append(linea)

        # ── 2️⃣ Por cobrar ─────────────────────────────────────────────────
        co = g_co.get(key, [])
        L.append("")
        if co:
            L.append(f"2️⃣ *TUS BODEGAS POR COBRAR* ({len(co)})")
            for p in co:
                b = p.get("bodegas") or {}
                icon, est = _cobranza_estado(p, hoy)
                ab = abonado_de(p)
                parcial = (f" · ya abonó {fmt_monto(ab)}, le falta esto 🧾"
                           if ab else "")
                L.append(f"  {icon} {nombre_bodega(b)} → "
                         f"{fmt_monto(_cobranza_monto(p, hoy))}{parcial} {est}")
        else:
            L.append("2️⃣ *TUS BODEGAS POR COBRAR*")
            L.append("  ✅ Ninguna por cobrar hoy — ¡así se mantiene! 👏")

        # ── 3️⃣ Por enrolar o financiar ────────────────────────────────────
        cl = g_cl.get(key, [])
        pa = g_pa.get(key, [])
        L.append("")
        L.append("3️⃣ *TUS BODEGAS POR ENROLAR O FINANCIAR*")
        if not cl and not pa:
            L.append("  — Hoy no tienes bodegas con línea en tu ruta")
        if cl:
            cl = sorted(cl, key=lambda m: -float((m.get("bodegas") or {}).get("linea_disponible") or 0))
            L.append(f"  ⚡ *YA TIENEN LÍNEA — ¡que financien hoy!* ({len(cl)})")
            for m in cl:
                b = m.get("bodegas") or {}
                L.append(f"     · {nombre_bodega(b)} · línea "
                         f"{fmt_monto(b.get('linea_disponible'))}")
        if pa:
            pa = sorted(pa, key=lambda m: -float((m.get("bodegas") or {}).get("linea_aprobada") or 0))
            L.append(f"  🔓 *POR ENROLAR* ({len(pa)}) — línea lista, se activa al enrolar")
            for m in pa:
                b = m.get("bodegas") or {}
                L.append(f"     · {nombre_bodega(b)} · hasta "
                         f"{fmt_monto(b.get('linea_aprobada'))}")

        L.append("")
        L.append("Envíanos los de tu ruta de hoy que quieras que evaluemos "
                 "para darles una línea cuanto antes.")
        L.append("")
        L.append("¡Que tengas un muy buen día!")

        bloques.append(cabecera + "\n" + "-" * 30 + "\n" + "\n".join(L))

    return ("\n\n" + "=" * 30 + "\n\n").join(bloques)


# ── 3. Mensajes SUPERVISORES ───────────────────────────────────────────────

def build_supervisores(hoy: date, comisiones, lineas=None) -> str:
    """Un bloque por supervisor: enrolamientos del equipo + foco en quienes no
    venden + detalle de bodegas con línea aprobada por vendedor.
    El supervisor es texto libre en la BD — sin celular, envío manual.
    `lineas` = {codigo: {"nueva":[(nom,monto)], "recompra":[(nom,monto)]}}."""
    if not comisiones:
        return "⚠️ Sin datos de comisiones hoy — no hay mensajes de supervisores."
    hasta = comisiones["hasta"]
    bloques = []
    for sup in sorted(comisiones["supervisores"]):
        cods = comisiones["supervisores"][sup]
        stats = [comisiones["por_codigo"][c] for c in cods]
        tot_mat = sum(s["mat"] for s in stats)
        tot_vuelo = sum(s["vuelo"] for s in stats)
        tot_venc = sum(s["venc"] for s in stats)

        sup_display = sup.title()
        cabecera = f">>> PARA SUPERVISOR: {sup}"
        L = [f"Hola {sup_display.split()[0] if sup_display else ''}! 👋 "
             f"Avance Circa de tu equipo (al {hasta.day:02d}/{hasta.month:02d}):", ""]
        L.append(f"💰 *TOTAL EQUIPO:* {fmt_monto(tot_mat)} confirmados"
                 + (f" + {fmt_monto(tot_vuelo)} en camino" if tot_vuelo else ""))
        if tot_venc:
            L.append(f"⛔ {fmt_monto(tot_venc)} retenidos por bodegas atrasadas "
                     f"— apoyar la cobranza los libera.")
        L.append("")

        # Enrolamientos del mes: quiénes enrolaron bodegas y quiénes no.
        enrolaron = sorted([s for s in stats if s["afil"] > 0],
                           key=lambda s: -s["afil"])
        sin_enrolar = [s for s in stats if s["afil"] == 0]
        # Foco: vendedores que no han vendido nada (sin comisión alguna).
        sin_vender = [s for s in stats if s["mat"] + s["vuelo"] + s["venc"] == 0]

        def _enrol(s):
            n = nombre_corto(s["v"])
            if s["afil_cash"]:
                return f"{n} ({s['afil_fin']}+{s['afil_cash']} cash)"
            return f"{n} ({s['afil_fin']})"

        L.append("🏪 *ENROLAMIENTOS DEL MES:*")
        L.append("  ✅ Enrolaron: "
                 + (", ".join(_enrol(s) for s in enrolaron) if enrolaron else "—"))
        if sin_enrolar:
            L.append("  ⬜ Sin enrolar aún: "
                     + ", ".join(nombre_corto(s["v"]) for s in sin_enrolar))

        if sin_vender:
            L.append("")
            L.append("🚨 *FOCO — aún sin vender nada:* "
                     + ", ".join(nombre_corto(s["v"]) for s in sin_vender))
            L.append("   una activación financiada son S/5 directos — "
                     "actívalos esta semana. 💪")

        if lineas:
            det = [(comisiones["por_codigo"][c]["v"], lineas.get(c, {}))
                   for c in cods if lineas.get(c, {}).get("nueva")
                   or lineas.get(c, {}).get("recompra")]
            if det:
                tot_b = sum(len(d.get("nueva", [])) for _, d in det)
                tot_s = sum(monto for _, d in det for _, monto in d.get("nueva", []))
                L.append("")
                L.append(f"📋 *DETALLE — bodegas con línea aprobada por colocar "
                         f"({tot_b} bodegas · S/{tot_s:.0f}):*")
                for v, d in sorted(det, key=lambda x: -len(x[1].get("nueva", []))):
                    nuevas = d.get("nueva", [])
                    sub = sum(m for _, m in nuevas)
                    L.append(f"  *{nombre_corto(v)}* — {len(nuevas)} bodega(s) · S/{sub:.0f}")
                    for nom, m in nuevas:
                        L.append(f"    • {nom} · S/{m:.0f}")
                    recompra = d.get("recompra", [])
                    if recompra:
                        L.append("    🔁 Recompra (línea reutilizable): "
                                 + ", ".join(f"{nom} S/{m:.0f}" for nom, m in recompra))
        L.append("")
        L.append("¡Gracias por el empuje de tu equipo! 💙")
        bloques.append(cabecera + "\n" + "-" * 30 + "\n" + "\n".join(L))
    return ("\n\n" + "=" * 30 + "\n\n").join(bloques)


def main():
    hoy = _fecha_cli() or hoy_lima()
    client = sb()

    comisiones = stats_comisiones(hoy)

    if "--supervisores" in sys.argv:
        lineas = q_lineas_aprobadas_por_vendedor(client)
        texto = build_supervisores(hoy, comisiones, lineas=lineas)
        print(texto)
        if "--copiar" in sys.argv:
            _copiar(texto)
        return

    con_linea, pre_aprobadas = q_visitas_hoy(client, DIAS[hoy.weekday()])

    # Bodegas con deuda VENCIDA: no van en "¡que financien!" aunque tengan línea
    cobranza_all = q_cobranza(client, hoy)
    vencidas_ids = set()
    for p in cobranza_all:
        try:
            if (hoy - date.fromisoformat(p.get("fecha_vencimiento") or "")).days > 0:
                vencidas_ids.add(p.get("bodega_id"))
        except ValueError:
            pass
    morosas = [m for m in con_linea
               if (m.get("bodegas") or {}).get("id") in vencidas_ids]
    con_linea = [m for m in con_linea
                 if (m.get("bodegas") or {}).get("id") not in vencidas_ids]
    if morosas:
        print("\n⛔ ALERTA (no va en el mensaje): visitas de hoy con línea PERO "
              "deuda vencida — excluidas de '¡que financien!', primero cobrar:",
              file=sys.stderr)
        for m in morosas:
            print(f"   · {nombre_bodega(m.get('bodegas') or {})}", file=sys.stderr)

    if "--privados" in sys.argv or "--por-vendedor" in sys.argv:
        mapa = q_mapa_vendedores(client)
        cobranza = asignar_vendedor_cartera(cobranza_all, mapa)
        acumulados = q_enrolados_acumulados(client, mapa)
        texto = build_privados(hoy, con_linea, pre_aprobadas,
                               cobranza=cobranza, comisiones=comisiones,
                               acumulados=acumulados)
    else:
        mapa = q_mapa_vendedores(client)
        despachos = asignar_vendedor_cartera(q_despachos_pendientes(client, hoy), mapa)
        cobranza = asignar_vendedor_cartera(cobranza_all, mapa)
        otros_dias, huerfanas = q_panorama_linea(client, DIAS[hoy.weekday()])
        texto = build_grupo(hoy, despachos, cobranza, con_linea, pre_aprobadas,
                            otros_dias=otros_dias, comisiones=comisiones)
        if huerfanas:
            print("\n⚠️  ALERTA (solo para ti, no va en el mensaje): bodegas con línea "
                  "que NUNCA aparecerán en el reporte:", file=sys.stderr)
            for h in huerfanas:
                print(f"   · {h}", file=sys.stderr)

    print(texto)

    if "--copiar" in sys.argv:
        _copiar(texto)


def _copiar(texto):
    try:
        import subprocess
        subprocess.run("pbcopy", input=texto.encode("utf-8"), check=True)
        print("\n📋 Copiado al clipboard.", file=sys.stderr)
    except Exception:
        print("\n⚠️ No se pudo copiar al clipboard.", file=sys.stderr)


if __name__ == "__main__":
    main()
