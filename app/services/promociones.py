"""
Motor de evaluación de promociones por distribuidor.

Toma un carrito y un distribuidor_id, devuelve para cada item del carrito
qué descuento se aplica (si alguno) y cuál es el siguiente escalón al que
puede llegar el bodeguero para incentivar más compra.

Diseño:
- Las reglas viven en tabla `promociones_distribuidor` (ver promociones_dimax_fase1_v3_final.sql)
- Cada regla tiene un `grupo_anulacion` — solo aplica el escalón más alto
  alcanzado en cada grupo
- Soporta dos tipos de promoción:
    * 'descuento_unidades'        → cuenta unidades base de SKUs específicos
    * 'descuento_monto_categoria' → suma monto S/ de productos por categoría

Conversión de unidades:
- El brief habla en unidades base (UND, TIRA, DSP)
- El bodeguero compra en formatos (UND, TIRA, CJA)
- El motor convierte a unidades base usando contenido_caja/contenido_pack
- Ej: 1 CJA CREMOSITA (24 UND) cuenta como 24 UND para una regla "6 UND"
- Ej: 1 CJA NESCAFE (8 TIRAS) cuenta como 8 TIRAS para una regla "1 TIRA"

Autor: Paola Velarde + Claude
Fecha: 22 abril 2026 (Sprint promociones DIMAX)
"""

from typing import List, Dict, Optional, Tuple
from collections import defaultdict


# ============================================================
# UTILIDADES DE CONVERSIÓN DE FORMATOS
# ============================================================

def parse_formato(formato_str: str) -> Tuple[Optional[str], int]:
    """
    Parsea strings tipo "CJA x 24" o "UND x 1" o "TIRA x 10".
    Retorna (tipo, multiplicador).
    
    Ej: "CJA x 24" → ("CJA", 24)
    Ej: "UND x 1"  → ("UND", 1)
    Ej: "TIRA x 10" → ("TIRA", 10)
    """
    if not formato_str:
        return (None, 1)
    parts = formato_str.upper().replace(" ", "").split("X")
    if len(parts) != 2:
        return (None, 1)
    tipo = parts[0].strip()
    try:
        mult = int(parts[1].strip())
    except ValueError:
        mult = 1
    return (tipo, mult)


def cantidad_en_unidad_base(cantidad: int, formato: str, unidad_objetivo: str,
                             contenido_caja: Optional[int] = None,
                             contenido_pack: Optional[int] = None) -> int:
    """
    Convierte una cantidad en un formato dado a la unidad base objetivo.
    
    Ej: 1 "CJA x 24" UND → 24 UND
    Ej: 2 "CJA x 8" TIRA → 16 TIRA
    Ej: 5 "UND x 1" UND → 5 UND
    Ej: 1 "CJA x 8" UND con contenido_caja=80, contenido_pack=10 → 80 UND
        (porque 1 CJA = 8 TIRA = 80 UND)
    """
    tipo_formato, mult = parse_formato(formato)
    if tipo_formato is None:
        return cantidad
    
    # Misma unidad: solo multiplicar
    if tipo_formato == unidad_objetivo:
        return cantidad * mult
    
    # CJA → TIRA: multiplicador es directo (CJA x 8 TIRA = 8 TIRAS)
    if tipo_formato == "CJA" and unidad_objetivo == "TIRA":
        return cantidad * mult
    
    # CJA → UND: usar contenido_caja
    if tipo_formato == "CJA" and unidad_objetivo == "UND":
        return cantidad * (contenido_caja or mult)
    
    # TIRA → UND: usar contenido_pack
    if tipo_formato == "TIRA" and unidad_objetivo == "UND":
        return cantidad * (contenido_pack or mult)
    
    # UND → CJA o UND → TIRA: no tiene sentido, devolver 0 (no aplica)
    if tipo_formato == "UND" and unidad_objetivo in ("CJA", "TIRA"):
        return 0
    
    # Fallback conservador
    return cantidad * mult


# ============================================================
# EVALUADOR PRINCIPAL
# ============================================================

def evaluar_promociones(cart: List[Dict], reglas: List[Dict]) -> Dict:
    """
    Evalúa qué promociones aplican al carrito.
    
    Args:
        cart: lista de items del carrito. Cada item:
            {
                "sku_distribuidor": "1248",
                "cantidad": 4,                 # cuántos del formato elegido
                "formato": "CJA x 24",         # o "UND x 1", "TIRA x 10"
                "precio_unitario_formato": 91.19,  # precio del formato (no del UND)
                "categoria": "EVAPORADAS",
                "marca": "IDEAL",
                "contenido_caja": 24,          # opcional, para conversiones
                "contenido_pack": None,        # opcional
            }
        reglas: lista de reglas activas del distribuidor (tabla promociones_distribuidor)
    
    Returns:
        {
            "items": [
                {
                    "sku_distribuidor": "1248",
                    "subtotal": 364.76,
                    "descuento_aplicado": {
                        "porcentaje": 0.075,
                        "ahorro": 27.36,
                        "mensaje": "¡Descuento 7.5%! Ahorras S/27.36"
                    },
                    "siguiente_escalon": {
                        "faltan": 60,
                        "unidad": "UND",
                        "porcentaje": 0.085,
                        "mensaje": "+60 UND más para subir a 8.5%"
                    }
                }
            ],
            "ahorro_total": 27.36,
            "subtotal_total": 364.76,
            "total_final": 337.40
        }
    """
    # Indexar reglas por grupo_anulacion para procesar de a uno
    grupos = defaultdict(list)
    for r in reglas:
        if r.get("activa", True):
            grupos[r["grupo_anulacion"]].append(r)
    
    # Para cada grupo, ordenar escalones de mayor a menor cantidad/monto
    for grupo in grupos:
        grupos[grupo].sort(
            key=lambda r: r.get("umbral_cantidad") or r.get("umbral_monto") or 0,
            reverse=True
        )
    
    # Evaluar cada grupo y armar mapping: grupo → (regla_aplicada, regla_siguiente, total_grupo)
    eval_grupos = {}  # grupo_anulacion → dict
    
    for grupo_nombre, reglas_grupo in grupos.items():
        regla_ejemplo = reglas_grupo[0]
        tipo = regla_ejemplo["tipo"]
        
        if tipo == "descuento_unidades":
            skus_aplica = set(regla_ejemplo.get("skus_aplica") or [])
            unidad = regla_ejemplo["umbral_unidad"]
            
            # Items del carrito que aplican a este grupo
            items_grupo = [i for i in cart if i["sku_distribuidor"] in skus_aplica]
            if not items_grupo:
                continue
            
            # Sumar cantidad total en unidad base
            cantidad_total = 0
            subtotal_grupo = 0.0
            for item in items_grupo:
                cantidad_unidad_base = cantidad_en_unidad_base(
                    item["cantidad"],
                    item["formato"],
                    unidad,
                    item.get("contenido_caja"),
                    item.get("contenido_pack"),
                )
                cantidad_total += cantidad_unidad_base
                subtotal_grupo += item["cantidad"] * item["precio_unitario_formato"]
            
            # Encontrar escalón aplicado y siguiente
            regla_aplicada = None
            regla_siguiente = None
            for r in reglas_grupo:  # ya ordenado de mayor a menor
                if cantidad_total >= r["umbral_cantidad"]:
                    regla_aplicada = r
                    break
            # Siguiente escalón: el más bajo de los que el cart no alcanza
            no_alcanzados = [r for r in reglas_grupo if cantidad_total < r["umbral_cantidad"]]
            if no_alcanzados:
                regla_siguiente = min(no_alcanzados, key=lambda r: r["umbral_cantidad"])
            
            eval_grupos[grupo_nombre] = {
                "tipo": tipo,
                "items_aplicables_skus": skus_aplica,
                "cantidad_total": cantidad_total,
                "subtotal_grupo": subtotal_grupo,
                "unidad": unidad,
                "regla_aplicada": regla_aplicada,
                "regla_siguiente": regla_siguiente,
            }
        
        elif tipo == "descuento_monto_categoria":
            categoria = regla_ejemplo.get("categoria")
            marca = regla_ejemplo.get("marca_aplica")
            
            # Items del carrito que matchean por categoría (y opcionalmente marca)
            items_grupo = []
            for i in cart:
                if categoria and i.get("categoria") != categoria:
                    continue
                if marca and i.get("marca") != marca:
                    continue
                items_grupo.append(i)
            if not items_grupo:
                continue
            
            # Sumar monto total
            subtotal_grupo = sum(
                i["cantidad"] * i["precio_unitario_formato"] for i in items_grupo
            )
            
            # Encontrar escalón aplicado y siguiente (por monto)
            regla_aplicada = None
            regla_siguiente = None
            for r in reglas_grupo:
                if subtotal_grupo >= float(r["umbral_monto"]):
                    regla_aplicada = r
                    break
            no_alcanzados = [r for r in reglas_grupo if subtotal_grupo < float(r["umbral_monto"])]
            if no_alcanzados:
                regla_siguiente = min(no_alcanzados, key=lambda r: float(r["umbral_monto"]))
            
            skus_grupo = {i["sku_distribuidor"] for i in items_grupo}
            eval_grupos[grupo_nombre] = {
                "tipo": tipo,
                "items_aplicables_skus": skus_grupo,
                "monto_total": subtotal_grupo,
                "subtotal_grupo": subtotal_grupo,
                "categoria": categoria,
                "marca": marca,
                "regla_aplicada": regla_aplicada,
                "regla_siguiente": regla_siguiente,
            }
    
    # Ahora construir el output: mensaje por item del carrito
    items_resultado = []
    ahorro_total = 0.0
    subtotal_total = 0.0
    
    for item in cart:
        item_subtotal = item["cantidad"] * item["precio_unitario_formato"]
        subtotal_total += item_subtotal
        
        # Buscar el grupo al que pertenece este SKU
        grupo_del_item = None
        eval_del_item = None
        for grupo, eval_data in eval_grupos.items():
            if item["sku_distribuidor"] in eval_data["items_aplicables_skus"]:
                grupo_del_item = grupo
                eval_del_item = eval_data
                break
        
        item_resultado = {
            "sku_distribuidor": item["sku_distribuidor"],
            "subtotal": round(item_subtotal, 2),
            "descuento_aplicado": None,
            "siguiente_escalon": None,
        }
        
        if eval_del_item:
            # Descuento aplicado (si hay)
            if eval_del_item["regla_aplicada"]:
                regla = eval_del_item["regla_aplicada"]
                pct = float(regla["porcentaje_descuento"])
                # El ahorro se prorratea: este item ahorra según su % del subtotal del grupo
                ahorro_item = item_subtotal * pct
                pct_visual = round(pct * 100, 2)
                # Quitar .0 final si es entero (6.5 sí, 7.0 → 7)
                pct_str = f"{pct_visual:.2f}".rstrip("0").rstrip(".")
                item_resultado["descuento_aplicado"] = {
                    "porcentaje": pct,
                    "ahorro": round(ahorro_item, 2),
                    "mensaje": f"¡Descuento {pct_str}%! Ahorras S/{ahorro_item:.2f}",
                }
                ahorro_total += ahorro_item
            
            # Siguiente escalón (si hay)
            if eval_del_item["regla_siguiente"]:
                sig = eval_del_item["regla_siguiente"]
                pct_sig = float(sig["porcentaje_descuento"])
                pct_sig_visual = round(pct_sig * 100, 2)
                pct_sig_str = f"{pct_sig_visual:.2f}".rstrip("0").rstrip(".")
                
                if eval_del_item["tipo"] == "descuento_unidades":
                    faltan = sig["umbral_cantidad"] - eval_del_item["cantidad_total"]
                    unidad = eval_del_item["unidad"]
                    if eval_del_item["regla_aplicada"]:
                        msg = f"+{faltan} {unidad} más para subir a {pct_sig_str}%"
                    else:
                        msg = f"+{faltan} {unidad} más para {pct_sig_str}% descuento"
                    item_resultado["siguiente_escalon"] = {
                        "faltan": faltan,
                        "unidad": unidad,
                        "porcentaje": pct_sig,
                        "mensaje": msg,
                    }
                else:  # descuento_monto_categoria
                    faltan_monto = float(sig["umbral_monto"]) - eval_del_item["monto_total"]
                    if eval_del_item["regla_aplicada"]:
                        msg = f"+S/{faltan_monto:.2f} más para subir a {pct_sig_str}%"
                    else:
                        msg = f"+S/{faltan_monto:.2f} más para {pct_sig_str}% descuento"
                    item_resultado["siguiente_escalon"] = {
                        "faltan_monto": round(faltan_monto, 2),
                        "porcentaje": pct_sig,
                        "mensaje": msg,
                    }
        
        items_resultado.append(item_resultado)
    
    return {
        "items": items_resultado,
        "ahorro_total": round(ahorro_total, 2),
        "subtotal_total": round(subtotal_total, 2),
        "total_final": round(subtotal_total - ahorro_total, 2),
    }


# ============================================================
# TESTS INTERNOS (correr con: python -m app.services.promociones)

# ============================================================
# EVALUADOR DE BONIFICACIONES (productos regalo, no descuentos %)
# Agregado: 5 mayo 2026 — Sprint v2 motor de promociones
# ============================================================

def _grupo_bonif(b: Dict) -> Optional[str]:
    """Asigna grupo lógico para evaluación de escalones."""
    cat = (b.get('categoria') or '').strip()
    marca = (b.get('marca_aplica') or '').strip()
    if b.get('umbral_monto') is not None:
        return f"{cat}__MONTO"
    if b.get('umbral_cantidad') is not None and b.get('umbral_unidad'):
        return f"{marca}__{b['umbral_unidad']}"
    return None


def _mensaje_bonif_aplicada(regla):
    cant = regla.get("cantidad_regalo") or 1
    unid = regla.get("unidad_regalo") or "UND"
    nombre = regla.get("producto_regalo_nombre") or "regalo"
    return f"🎁 ¡Te llevás {cant} {unid} de {nombre} GRATIS!"


def evaluar_bonificaciones(cart: List[Dict], reglas_bonif: List[Dict]) -> Dict:
    """
    Evalúa qué bonificaciones (productos regalo) aplican al carrito.
    
    A diferencia de `evaluar_promociones` (que devuelve % off),
    ésta devuelve qué producto regalo se ganó y cuánto falta para el siguiente escalón.
    
    Args:
        cart: lista de items con sku_distribuidor, cantidad, formato,
              precio_unitario_formato, categoria, marca, contenido_caja, contenido_pack
        reglas_bonif: filas activas de bonificaciones_distribuidor
    
    Returns:
        {
            "aplicables": [{regla_id, regalo_nombre, regalo_cantidad, ...}],
            "proximas":   [{regla_id, falta, mensaje_corto, ...}],
            "valor_total_estimado": float
        }
    """
    reglas = [r for r in reglas_bonif if r.get("activa", True)]
    
    grupos = defaultdict(list)
    for r in reglas:
        g = _grupo_bonif(r)
        if g:
            grupos[g].append(r)
    
    for g in grupos:
        grupos[g].sort(
            key=lambda r: float(r.get("umbral_cantidad") or r.get("umbral_monto") or 0),
            reverse=True
        )
    
    aplicables = []
    proximas = []
    valor_total = 0.0
    
    for grupo_nombre, reglas_grupo in grupos.items():
        regla_ejemplo = reglas_grupo[0]
        es_por_monto = regla_ejemplo.get("umbral_monto") is not None
        
        if es_por_monto:
            categoria = regla_ejemplo.get("categoria")
            items_grupo = [
                i for i in cart
                if (i.get("categoria") or "").strip() == (categoria or "").strip()
            ]
            if not items_grupo:
                continue
            total_alcanzado = sum(i["cantidad"] * i["precio_unitario_formato"] for i in items_grupo)
            tipo_umbral = "monto"
        else:
            marca = regla_ejemplo.get("marca_aplica")
            unidad = regla_ejemplo["umbral_unidad"]
            items_grupo = [
                i for i in cart
                if (i.get("marca") or "").strip() == (marca or "").strip()
            ]
            if not items_grupo:
                continue
            total_alcanzado = 0
            for it in items_grupo:
                total_alcanzado += cantidad_en_unidad_base(
                    it["cantidad"], it["formato"], unidad,
                    it.get("contenido_caja"), it.get("contenido_pack")
                )
            tipo_umbral = "cantidad"
        
        regla_aplicada = None
        for r in reglas_grupo:
            umbral_r = float(r.get("umbral_monto") or r.get("umbral_cantidad") or 0)
            if total_alcanzado >= umbral_r:
                regla_aplicada = r
                break
        
        no_alcanzados = [
            r for r in reglas_grupo
            if total_alcanzado < float(r.get("umbral_monto") or r.get("umbral_cantidad") or 0)
        ]
        regla_siguiente = None
        if no_alcanzados:
            regla_siguiente = min(
                no_alcanzados,
                key=lambda r: float(r.get("umbral_monto") or r.get("umbral_cantidad") or 0)
            )
        
        if regla_aplicada:
            umbral_a = float(regla_aplicada.get("umbral_monto") or regla_aplicada.get("umbral_cantidad") or 0)
            tasa = float(regla_aplicada.get("porcentaje_descuento_equivalente") or 0)
            subtotal_grupo = sum(i["cantidad"] * i["precio_unitario_formato"] for i in items_grupo)
            valor_estim = round(subtotal_grupo * tasa, 2)
            valor_total += valor_estim
            
            aplicables.append({
                "regla_id": regla_aplicada["id"],
                "categoria": regla_aplicada.get("categoria"),
                "marca_aplica": regla_aplicada.get("marca_aplica"),
                "regalo_nombre": regla_aplicada.get("producto_regalo_nombre"),
                "regalo_cantidad": regla_aplicada.get("cantidad_regalo"),
                "regalo_unidad": regla_aplicada.get("unidad_regalo") or "UND",
                "descripcion": regla_aplicada.get("descripcion_completa") or regla_aplicada.get("nombre"),
                "alcanzado": round(total_alcanzado, 2) if es_por_monto else int(total_alcanzado),
                "umbral": round(umbral_a, 2) if es_por_monto else int(umbral_a),
                "tipo_umbral": tipo_umbral,
                "valor_estimado": valor_estim,
                "mensaje_corto": _mensaje_bonif_aplicada(regla_aplicada),
            })
        
        if regla_siguiente:
            umbral_s = float(regla_siguiente.get("umbral_monto") or regla_siguiente.get("umbral_cantidad") or 0)
            falta = umbral_s - total_alcanzado
            cant_regalo = regla_siguiente.get("cantidad_regalo") or 1
            unid_regalo = regla_siguiente.get("unidad_regalo") or "UND"
            regalo_nombre = regla_siguiente.get("producto_regalo_nombre") or "regalo"
            
            if es_por_monto:
                falta_str = f"S/{falta:.2f}"
            else:
                falta_str = f"{int(falta)} {regla_siguiente.get('umbral_unidad')}"
            
            mensaje = (
                f"+{falta_str} para llevarte "
                f"{cant_regalo} {unid_regalo} de {regalo_nombre} GRATIS 🎁"
            )
            
            proximas.append({
                "regla_id": regla_siguiente["id"],
                "categoria": regla_siguiente.get("categoria"),
                "marca_aplica": regla_siguiente.get("marca_aplica"),
                "regalo_nombre": regalo_nombre,
                "regalo_cantidad": cant_regalo,
                "regalo_unidad": unid_regalo,
                "descripcion": regla_siguiente.get("descripcion_completa") or regla_siguiente.get("nombre"),
                "alcanzado": round(total_alcanzado, 2) if es_por_monto else int(total_alcanzado),
                "umbral": round(umbral_s, 2) if es_por_monto else int(umbral_s),
                "falta": round(falta, 2) if es_por_monto else int(falta),
                "tipo_umbral": tipo_umbral,
                "mensaje_corto": mensaje,
            })
    
    return {
        "aplicables": aplicables,
        "proximas": proximas,
        "valor_total_estimado": round(valor_total, 2),
    }


# ============================================================

if __name__ == "__main__":
    # Reglas de prueba (mock de las 18 reglas piloto DIMAX)
    REGLAS_DEMO = [
        # CREMOSITA (3 escalones)
        {"tipo": "descuento_unidades", "skus_aplica": ["1248"], "umbral_cantidad": 6,  "umbral_unidad": "UND", "porcentaje_descuento": 0.0650, "grupo_anulacion": "CREMOSITA", "activa": True},
        {"tipo": "descuento_unidades", "skus_aplica": ["1248"], "umbral_cantidad": 12, "umbral_unidad": "UND", "porcentaje_descuento": 0.0750, "grupo_anulacion": "CREMOSITA", "activa": True},
        {"tipo": "descuento_unidades", "skus_aplica": ["1248"], "umbral_cantidad": 72, "umbral_unidad": "UND", "porcentaje_descuento": 0.0850, "grupo_anulacion": "CREMOSITA", "activa": True},
        # NESCAFE 14g (4 escalones)
        {"tipo": "descuento_unidades", "skus_aplica": ["1748", "1770"], "umbral_cantidad": 1, "umbral_unidad": "TIRA", "porcentaje_descuento": 0.0500, "grupo_anulacion": "NESCAFE_14", "activa": True},
        {"tipo": "descuento_unidades", "skus_aplica": ["1748", "1770"], "umbral_cantidad": 3, "umbral_unidad": "TIRA", "porcentaje_descuento": 0.0600, "grupo_anulacion": "NESCAFE_14", "activa": True},
        {"tipo": "descuento_unidades", "skus_aplica": ["1748", "1770"], "umbral_cantidad": 5, "umbral_unidad": "TIRA", "porcentaje_descuento": 0.0800, "grupo_anulacion": "NESCAFE_14", "activa": True},
        {"tipo": "descuento_unidades", "skus_aplica": ["1748", "1770"], "umbral_cantidad": 8, "umbral_unidad": "TIRA", "porcentaje_descuento": 0.1000, "grupo_anulacion": "NESCAFE_14", "activa": True},
        # ECCO por monto (3 escalones)
        {"tipo": "descuento_monto_categoria", "categoria": "ECCO", "umbral_monto": 30,  "porcentaje_descuento": 0.0269, "grupo_anulacion": "ECCO_MONTO", "activa": True},
        {"tipo": "descuento_monto_categoria", "categoria": "ECCO", "umbral_monto": 60,  "porcentaje_descuento": 0.0403, "grupo_anulacion": "ECCO_MONTO", "activa": True},
        {"tipo": "descuento_monto_categoria", "categoria": "ECCO", "umbral_monto": 100, "porcentaje_descuento": 0.0565, "grupo_anulacion": "ECCO_MONTO", "activa": True},
    ]
    
    # Test 1: 4 UND CREMOSITA → no llega al primer escalón (necesita 6)
    print("\n=== TEST 1: 4 UND CREMOSITA (no llega) ===")
    cart = [{"sku_distribuidor": "1248", "cantidad": 4, "formato": "UND x 1", "precio_unitario_formato": 3.80, "contenido_caja": 24, "categoria": "EVAPORADAS", "marca": "IDEAL"}]
    r = evaluar_promociones(cart, REGLAS_DEMO)
    print(f"Subtotal: S/{r['subtotal_total']}, ahorro: S/{r['ahorro_total']}, total: S/{r['total_final']}")
    item = r['items'][0]
    print(f"  Aplicado: {item['descuento_aplicado']}")
    print(f"  Siguiente: {item['siguiente_escalon']}")
    assert item['descuento_aplicado'] is None, "No debería aplicar nada con 4 UND"
    assert item['siguiente_escalon']['faltan'] == 2, "Faltan 2 UND para 6.5%"
    
    # Test 2: 6 UND CREMOSITA → primer escalón (6.5%)
    print("\n=== TEST 2: 6 UND CREMOSITA (primer escalón 6.5%) ===")
    cart = [{"sku_distribuidor": "1248", "cantidad": 6, "formato": "UND x 1", "precio_unitario_formato": 3.80, "contenido_caja": 24, "categoria": "EVAPORADAS", "marca": "IDEAL"}]
    r = evaluar_promociones(cart, REGLAS_DEMO)
    item = r['items'][0]
    print(f"Subtotal: S/{r['subtotal_total']}, ahorro: S/{r['ahorro_total']}, total: S/{r['total_final']}")
    print(f"  Aplicado: {item['descuento_aplicado']}")
    print(f"  Siguiente: {item['siguiente_escalon']}")
    assert abs(item['descuento_aplicado']['porcentaje'] - 0.065) < 0.001
    assert item['siguiente_escalon']['faltan'] == 6, "Faltan 6 UND para 7.5%"
    
    # Test 3: 1 CJA CREMOSITA = 24 UND → segundo escalón (7.5%)
    print("\n=== TEST 3: 1 CJA CREMOSITA = 24 UND (segundo escalón 7.5%) ===")
    cart = [{"sku_distribuidor": "1248", "cantidad": 1, "formato": "CJA x 24", "precio_unitario_formato": 91.19, "contenido_caja": 24, "categoria": "EVAPORADAS", "marca": "IDEAL"}]
    r = evaluar_promociones(cart, REGLAS_DEMO)
    item = r['items'][0]
    print(f"Subtotal: S/{r['subtotal_total']}, ahorro: S/{r['ahorro_total']}, total: S/{r['total_final']}")
    print(f"  Aplicado: {item['descuento_aplicado']}")
    print(f"  Siguiente: {item['siguiente_escalon']}")
    assert abs(item['descuento_aplicado']['porcentaje'] - 0.075) < 0.001
    assert item['siguiente_escalon']['faltan'] == 48, "Faltan 48 UND para 8.5%"
    
    # Test 4: 1 CJA NESCAFE = 8 TIRAS → escalón máximo (10%)
    print("\n=== TEST 4: 1 CJA NESCAFE = 8 TIRAS (máximo 10%) ===")
    cart = [{"sku_distribuidor": "1748", "cantidad": 1, "formato": "CJA x 8", "precio_unitario_formato": 168.00, "contenido_caja": 80, "contenido_pack": 10, "categoria": "CAFES SIN ECCO", "marca": "NESCAFE"}]
    r = evaluar_promociones(cart, REGLAS_DEMO)
    item = r['items'][0]
    print(f"Subtotal: S/{r['subtotal_total']}, ahorro: S/{r['ahorro_total']}, total: S/{r['total_final']}")
    print(f"  Aplicado: {item['descuento_aplicado']}")
    print(f"  Siguiente: {item['siguiente_escalon']}")
    assert abs(item['descuento_aplicado']['porcentaje'] - 0.10) < 0.001
    assert item['siguiente_escalon'] is None, "No hay siguiente, ya está en máximo"
    
    # Test 5: ECCO con S/45 (entre escalones 30 y 60) → 2.69%
    print("\n=== TEST 5: 1 CJA ECCO S/137.77 (escalón S/100, 5.65%) ===")
    cart = [{"sku_distribuidor": "1281", "cantidad": 1, "formato": "CJA x 24", "precio_unitario_formato": 137.77, "contenido_caja": 24, "categoria": "ECCO", "marca": "ECCO"}]
    r = evaluar_promociones(cart, REGLAS_DEMO)
    item = r['items'][0]
    print(f"Subtotal: S/{r['subtotal_total']}, ahorro: S/{r['ahorro_total']}, total: S/{r['total_final']}")
    print(f"  Aplicado: {item['descuento_aplicado']}")
    print(f"  Siguiente: {item['siguiente_escalon']}")
    assert abs(item['descuento_aplicado']['porcentaje'] - 0.0565) < 0.001
    assert item['siguiente_escalon'] is None, "No hay siguiente para S/100"
    
    # Test 6: Carrito mixto (CREMOSITA + NESCAFE + ECCO) → descuentos múltiples
    print("\n=== TEST 6: CARRITO MIXTO (CREMOSITA + NESCAFE + ECCO) ===")
    cart = [
        {"sku_distribuidor": "1248", "cantidad": 12, "formato": "UND x 1", "precio_unitario_formato": 3.80, "contenido_caja": 24, "categoria": "EVAPORADAS", "marca": "IDEAL"},
        {"sku_distribuidor": "1748", "cantidad": 3, "formato": "TIRA x 10", "precio_unitario_formato": 21.00, "contenido_caja": 80, "contenido_pack": 10, "categoria": "CAFES SIN ECCO", "marca": "NESCAFE"},
        {"sku_distribuidor": "1281", "cantidad": 1, "formato": "UND x 1", "precio_unitario_formato": 5.74, "contenido_caja": 24, "categoria": "ECCO", "marca": "ECCO"},
    ]
    r = evaluar_promociones(cart, REGLAS_DEMO)
    print(f"Subtotal: S/{r['subtotal_total']}, ahorro: S/{r['ahorro_total']}, total: S/{r['total_final']}")
    for item in r['items']:
        print(f"  SKU {item['sku_distribuidor']} (S/{item['subtotal']}):")
        print(f"    Aplicado: {item['descuento_aplicado']}")
        print(f"    Siguiente: {item['siguiente_escalon']}")
    
    print("\n✅ TODOS LOS TESTS PASARON")
