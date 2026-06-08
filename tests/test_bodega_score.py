from app.services.bodega_score import compute_bodega_score


def test_score_excellent_bodega():
    result = compute_bodega_score(
        bodega={"linea_aprobada": 500, "linea_disponible": 200},
        features={
            "frecuencia_compra": 8,
            "dias_desde_ultima_compra": 5,
            "ticket_promedio": 120,
            "usa_credito": True,
            "mensajes_inbound": 40,
            "mensajes_outbound": 30,
        },
        stats={"total_pedidos": 8, "pedidos_pagados": 6},
        pedidos=[
            {"estado": "pagado", "monto_financiado": 100, "fecha_vencimiento": "2026-01-01"},
            {"estado": "pagado", "monto_financiado": 80, "fecha_vencimiento": "2026-02-01"},
            {"estado": "entregado", "monto_financiado": 50, "fecha_vencimiento": "2020-01-01"},
        ],
    )
    assert result["score"] >= 70
    assert result["grade"] in ("A", "B")
    assert "breakdown" in result


def test_score_new_bodega_neutral():
    result = compute_bodega_score(
        bodega={"linea_aprobada": 500, "linea_disponible": 500},
        features={},
        stats={"total_pedidos": 0, "pedidos_pagados": 0},
        pedidos=[],
    )
    assert 50 <= result["score"] <= 85
