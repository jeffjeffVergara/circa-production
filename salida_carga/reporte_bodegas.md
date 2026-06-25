# Circa - Reporte de carga de bodegas

Generado por cargar_bodega.py  |  1 bodega(s) procesada(s)

---

## MARKET TRADING SOCIEDAD ANONIMA CERRADA

- Archivo: `MARKET TRADING SOCIEDAD ANONIMA CERRADA.xlsx`
- Codigo: C0049914  |  Documento: 20606378239  |  Clasificacion: B

### Analisis de riesgo (ultimos 6 meses)

| Metrica | Valor |
|---|---|
| Periodo | 2025-12-19 -> 2026-06-19 |
| Pedidos | 26 |
| Total comprado | S/2307.68 |
| Ticket promedio | S/88.76 |
| Dias entre pedidos | 7.3 |
| Regularidad de compra | regular (CV 0.56) |
| Consumo diario | S/12.19 |
| Linea necesaria 7 dias | S/85.34 |
| **Tier asignado (conservador)** | **S/100** |

### SQL de carga

```sql
-- ====================================================
-- Bodega: MARKET TRADING SOCIEDAD ANONIMA CERRADA
-- Linea aprobada: S/100  (modelo: consumo 7d = S/85.34)
-- ====================================================
BEGIN;

-- Crear la bodega (estado inactivo, disponible 0 hasta onboarding)
INSERT INTO bodegas (
  distribuidor_id, razon_social, nombre_comercial, telefono_whatsapp,
  ruc, dni_representante, solo_dni_sin_ruc,
  direccion_fiscal, direccion_despacho, distrito,
  es_test, en_piloto, estado, linea_aprobada, linea_disponible)
SELECT 'd1a2b3c4-0001-4000-8000-000000000002', 'MARKET TRADING SOCIEDAD ANONIMA CERRADA', 'MARKET TRADING SOCIEDAD ANONIMA CERRADA', '+51949387007',
       '20606378239', NULL, false,
       'Av Comandante Espinar Nro. 852 Urb. Miraflores (ovalo Gutierrez)', 'Av Comandante Espinar Nro. 852 Urb. Miraflores (ovalo Gutierrez)', 'Miraflores',
       false, true, 'inactivo', 100, 0
WHERE NOT EXISTS (
  SELECT 1 FROM bodegas WHERE telefono_whatsapp = '+51949387007');


SELECT 'bodega' AS tipo, razon_social AS detalle,
       linea_aprobada::text AS aprob, linea_disponible::text AS disp,
       estado::text AS estado
FROM bodegas WHERE telefono_whatsapp = '+51949387007'
UNION ALL
SELECT 'mapping', b.razon_social || ' -> ' || v.codigo,
       bv.rol, bv.grupo, bv.dia_visita
FROM bodega_vendedores bv
JOIN bodegas b ON b.id = bv.bodega_id
JOIN vendedores v ON v.id = bv.vendedor_id
WHERE b.telefono_whatsapp = '+51949387007';

COMMIT;

```

### Mensaje de WhatsApp

```
Buenas Don Sociedad! 👋 Le escribe tu vendedor, de DIMAX.

Le tengo una novedad para su bodega: ahora puede hacer sus pedidos por WhatsApp con Circa. Ve el catalogo completo, arma su pedido cuando quiera y lo recibe igual que siempre - sin tener que esperar a mi visita del la semana.

Y por su buen historial como cliente, ya le tenemos una linea de credito pre-aprobada 🙌 Para que pueda surtir su bodega y pagar con calma.

Activarla le toma 2 minutos. Solo abra este enlace y envie el mensaje que le aparece:
👉 https://wa.me/51986311567?text=Hola

Cualquier duda me avisa. Saludos!
```

---
