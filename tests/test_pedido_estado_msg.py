"""Tests línea ESTADO / pedidos activos en WhatsApp."""

import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from app.services.messages import format_pedido_activo_line


def test_preventa_confirmada_sin_numero():
  line = format_pedido_activo_line({
      "estado": "preventa_confirmada",
      "link_token": "90b70e0d091d",
      "total_pedido": 132.22,
      "monto_total_credito": None,
      "fecha_vencimiento": None,
  })
  assert "PRV-90b70e0d" in line
  assert "Pre-venta pendiente" in line
  assert "S/132.22" in line
  assert "Pendiente de confirmar" in line
  assert "None" not in line


def test_pedido_confirmado_crc052():
  line = format_pedido_activo_line({
      "numero": "CRC-052",
      "estado": "recibido",
      "total_pedido": 132.22,
      "monto_financiado": 100.0,
      "monto_contado": 32.22,
      "monto_total_credito": 101.4,
      "fee_monto": 1.4,
      "fecha_vencimiento": "2026-07-15",
  })
  assert "CRC-052" in line
  assert "Recibido" in line
  assert "S/101.40" in line
  assert "15/07/2026" in line
  assert "32.22" in line
