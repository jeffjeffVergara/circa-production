# CIRCA — Notas de trabajo (leer antes de tocar nada)

Este archivo guarda hechos verificados del proyecto y errores que YA se cometieron.
Antes de reportar una anomalía de datos, revisar la sección "Errores conocidos".

---

## 🟢 ESQUEMA VIGENTE DE COMISIONES → `circa_corte_v2.py`

**Definido por Paola el 31-ago-2026. Reemplaza al esquema julio.**

1. **Enrolados — S/5.** Bodega cuyo PRIMER pedido financiado cae en el periodo.
   A PAGAR si esa bodega ya pagó **cualquiera** de sus financiamientos; si no,
   EN VUELO (se paga apenas pague).
2. **Financiados — S/1.** Cada pedido financiado creado en el periodo que no sea
   el primero de la bodega. A PAGAR si ese pedido está pagado; si no, EN VUELO.
   **Nunca se miran pedidos de meses anteriores.**
3. **Bono top — S/20** al vendedor con más enrolados. Empate → aviso, se decide
   a mano.
4. Sin metas semanales. Sin retenciones diferenciadas: todo financiado paga
   igual, sin importar la antigüedad de la bodega.
5. **Bono top: solo si el estrella está limpio (filtro 6, 22-sep-2026).** El
   S/20 NO se paga si el vendedor estrella tiene algún pedido VENCIDO en el
   periodo. (El resto del esquema no cambia; no hay bloqueo por "bodega al día".)

**No cuenta como financiamiento:** `monto_financiado = 0`; pedido pagado en
efectivo (`pagado_cash` / `metodo_pago='efectivo'`) aunque conserve monto; pedido
aún NO entregado (criterio por **estado**, ver punto 0b); cancelados/rechazados.

**Los tres estados:**

| estado | qué significa | ¿se paga? |
|---|---|---|
| A PAGAR | la bodega ya pagó | sí, ahora |
| EN VUELO | no pagó pero **sigue dentro de su plazo** (los 7 días) | sí, apenas pague |
| VENCIDO | **ya cumplió su ciclo de plazo y no pagó** | sí, apenas pague |

VENCIDO **no es una pérdida** para el vendedor: se separa de EN VUELO solo para
mostrar dónde hay que cobrar. Criterio: `fecha_vencimiento < hoy` y sin pagar.
Los 7 días corren desde la ENTREGA, no desde la visita.

Cada pedido se evalúa **solo**: no hay bloqueo por "bodega al día". Si una bodega
tiene un pedido vencido y dos pagados, los dos pagados se cobran igual. Tampoco
hay arrastre.

⚠️ `circa_corte_comisiones.py` es el ENTRY que corre la tarea diaria, pero su
`main()` original (esquema JULIO) quedó **obsoleto**: ese archivo ahora DELEGA a
`circa_corte_v2.py` (agosto + filtro 6) y conserva solo los helpers de datos que
v2 importa (`fetch_todo`, `parse_ts`, etc.). El corte oficial = v2. (22-sep-2026)

Resultado del corte 01→30-ago-2026 con v2:
**A PAGAR S/149 · EN VUELO S/51 · VENCIDO S/4**, 25 enrolados (19 ya pagando) y
59 financiados (34 cobrados). ⭐ Top: V0034 Amaro con 6 enrolados (+S/20), tras
reasignarle SUPERMERCADOS ALDEA y DAMIANO ZUÑIGA JHUNIOR.

⚠️ **Trampa ya pisada tres veces el 31-ago-2026:** usar una columna que NO está
en el `select` de `fetch_todo`. Llega vacía y la regla que la usa **falla en
silencio** (no da error, da cero). Pasó con `fecha_entregado` — marcó medio corte
como no entregado — y con `fecha_vencimiento` — dio VENCIDO S/0 teniendo 5
pedidos vencidos. Al agregar una regla, verificar primero que su columna esté en
el select. `pedidos` tiene 67 columnas; el select del script v1 solo trae 13.

### Cuándo pagó la bodega: `fecha_pagado` NO es la fecha del pago

**[Confirmado 31-ago-2026, reportado por Paola con el caso PACARA CRC-129.]**

Hay dos campos distintos y significan cosas distintas:

| campo | qué es |
|---|---|
| `pago_cliente_sustento_subido_at` | cuándo la **bodega** subió su comprobante |
| `fecha_pagado` / `pagado_at` | cuándo **Circa** lo marcó pagado en el sistema |

El panel web muestra el sustento. PACARA CRC-129: sustento 28-ago, marcado
pagado 31-ago → con `fecha_pagado` sola quedaba fuera del corte al 30 y salía
VENCIDO **teniendo pagado**.

**5 pedidos con ese desfase**, dos cruzando cierre de mes: CRC-041 (25-jun →
3-jul), CRC-042 (26-jun → 4-jul), CRC-040 (23-jun → 30-jun), CRC-129 (28-ago →
31-ago), CRC-090 (6-ago → 7-ago). Solo 75 de 138 pagos tienen sustento, así que
hace falta el fallback.

**Regla [decisión de Paola]:** vale la evidencia **más temprana** de las tres. El
vendedor no controla cuánto tarda la verificación. → `fecha_pago_efectiva()` en
`circa_corte_v2.py`.

### Zona horaria: Postgres guarda UTC, el negocio opera en Perú (UTC-5)

Un pago a las 22:58 del 28 en Lima se guarda como `2026-08-29T03:58Z`. Comparar
la fecha **UTC** contra el calendario del negocio lo corre un día. Al 31-ago-2026
afectaba a **8 pedidos** (ej. CRC-104: 17-ago en Perú, 18-ago en UTC).

Todo el v2 convierte con `dia_peru()` antes de comparar. ⚠️ El script v1 y
`circa_agente_vendedores.py` **no lo hacen**: siguen comparando en UTC.

### 📒 `historico_zoom` ES LA TABLA MAESTRA DE RUTA — mirarla SIEMPRE

**[Confirmado 31-ago-2026, señalado por Paola.]** Antes de decir que a una bodega
"le falta" vendedor, día de visita o grupo, **consultar `historico_zoom`**. Es la
carga maestra de ZOOM y trae la ruta completa:

| columna | ejemplo |
|---|---|
| `nombre_cliente` | MORENO MUCHA LUISA ISABEL |
| `cod_vendedor` / `vendedor` | V0023 / ARREDONDO FRANCIA FERNANDO RAFAEL |
| `supervisor` | LEONOR SAFRA |
| `grupo` | MERCADOS · GV BODEGAS 1/2/3 |
| `dia_visita` / `dia_entrega` | SABADO / LUNES |

⚠️ **Formato distinto entre tablas:** `historico_zoom` guarda los días en
MAYÚSCULAS (`JUEVES`); `bodega_vendedores` en minúsculas sin tilde (`jueves`,
`miercoles`, `sabado`). Al copiar hay que aplicar `lower()`, o el reporte diario
de visitas no encontrará la bodega.

⚠️ **`historico_zoom` NO siempre tiene la razón.** Caso SUPERMERCADOS ALDEA
E.I.R.L. (31-ago-2026): tanto `historico_zoom` como `bodega_vendedores` decían
V0006 Ericka Horna, pero **Paola confirmó que la atiende V0034 Amaro**. Se
corrigió `bodega_vendedores`. ⚠️ Si se recarga `historico_zoom` desde ZOOM sin
corregir el origen, **este cambio se puede revertir**. Hay que pedir a ZOOM que
lo arregle en su maestra.

Al revés también pasa: DAMIANO ZUÑIGA JHUNIOR estaba en `bodega_vendedores` como
V0035 Trigo, y `historico_zoom` decía V0034 Amaro — ahí la maestra tenía razón y
`bodega_vendedores` estaba desactualizada. **Cruzar siempre las dos y preguntar
a Paola cuando difieran.**

⚠️ **Los nombres NO son idénticos entre tablas.** `bodegas` dice
"PECEROS ANDIA, GRACIELA" y `historico_zoom` "PECEROS ANDIA RICARDO ELEUTERIO";
"VARGAS MENDOZA, JUAN MANUEL" vs "VARGAS MENDOZA DIANA CAROLINA" — y estas dos
últimas son bodegas **distintas**. No emparejar por apellido a ciegas: confirmar
con Paola cuando el nombre de pila no coincida.

### Mapeos a ADMIN — corregido parcialmente el 31-ago-2026

`DOMINGUEZ ATANACIO, FIDELA` estaba mapeada a `CIRCA01 Admin Circa`, así que su
enrolamiento (CRC-176, S/5) no le sumaba a nadie. **Corregido en la base a V0007
Patricia Cardenas** (confirmado por Paola). `UPDATE bodega_vendedores SET
vendedor_id=... WHERE id='f11bfcdc-6557-4aed-93fe-e701581331f0'`.

A Fidela se le completó además la ruta desde `historico_zoom`: `dia_visita` =
jueves, `dia_entrega` = viernes, `grupo` = GV BODEGAS 1. Ya aparece en el reporte
diario de visitas.

MORENO MUCHA (V0023, sábado/lunes, MERCADOS) y PECEROS ANDIA GRACIELA (V0014
Peña, lunes/martes, GV BODEGAS 2) **las corrigió Paola** el mismo día; sus
mapeos viejos al Admin quedaron en `activo = false`, que es lo correcto.

⚠️ **Queda 1 bodega mapeada a Admin y sin ruta: VARGAS MENDOZA, JUAN MANUEL.**
No tiene pedidos todavía. En `historico_zoom` solo existe "VARGAS MENDOZA DIANA
CAROLINA", que es **otra bodega**, ya mapeada a V0031. Falta que Paola diga qué
vendedor le toca a Juan Manuel.

Estado al 31-ago-2026: de 4640 mapeos activos, **1 sin `dia_visita`** (el de
Juan Manuel). La afirmación de más abajo de que el 100% tiene día de visita era
cierta al 25-ago; las bodegas nuevas entran sin ruta y hay que completarla.

---

### 👔 SUPERVISORES: la maestra es `vendedores.supervisor`, NO `bodega_vendedores`

**[Confirmado 04-sep-2026, corregido el mismo día.]** `bodega_vendedores.supervisor`
es un campo **denormalizado** y tenía **8 grafías para 4 personas**, según de qué
carga viniera la fila (ZOOM original = "NOMBRE APELLIDO"; herencias del 02-sep =
"APELLIDOS NOMBRES"):

| persona | variantes encontradas |
|---|---|
| César Urbina | CESAR URBINA · URBINA VELASQUEZ CESAR EDINHO |
| Manuel Mendoza | MANUEL MENDOZA · MENDOZA MELENDEZ MANUEL |
| Angelo Acosta | ANGELO ACOSTA · ACOSTA SERPA ANGELO LELIS |
| María Leonor Safra | SAFRA ALVIS MARIA LEONOR · LEONOR SAFRA · **LEONOR SARA** (typo) |

Efecto: cualquier agrupación por supervisor partía la cartera en dos. El modo
`--supervisores` emitía 8 bloques en vez de 4.

`vendedores.supervisor` en cambio está **limpio**: 4 valores, formato largo, sin
variantes. **Es la fuente de verdad.**

**Regla [decisión de Paola, 04-sep-2026]:** `bodega_vendedores.supervisor` se
**deriva** de `vendedores.supervisor` por `vendedor_id`. Nunca se escribe a mano
ni se toma del archivo de carga.

```sql
update bodega_vendedores bv set supervisor = v.supervisor
  from vendedores v
 where v.id = bv.vendedor_id and v.supervisor is not null
   and bv.supervisor is distinct from v.supervisor;
```

Se corrigieron **3821 filas**. De esas, **3802 eran solo grafía**; las otras **19
eran supervisor distinto de verdad** y se alinearon a `vendedores`:

| vendedor | decía en `bodega_vendedores` | quedó (según `vendedores`) | filas |
|---|---|---|---|
| V0007 Cardenas | SAFRA | ACOSTA | 8 |
| V0039 Llanos | SAFRA | ACOSTA | 6 |
| V0017 Quispe | ACOSTA | MENDOZA | 3 |
| V0020 Buitrón | ACOSTA | MENDOZA | 1 |
| V0010 Zambrano | SAFRA | URBINA | 1 |

Estado final: **4 supervisores, 0 variantes.** Quedan 20 filas con supervisor NULL
y son correctas: pertenecen a ADMIN CIRCA, cuentas `*-OLD`, `VW-PAO`,
`VW-CYNTHIA` y `VWTEST-JV`, que no tienen supervisor comercial.

⚠️ **Esto se revierte si se recarga desde ZOOM sin aplicar la derivación.** Tras
cada carga masiva hay que volver a correr el UPDATE de arriba.

⚠️ **Sigue en pie 1 bodega mapeada a ADMIN CIRCA con rol ABN activo** (la de
VARGAS MENDOZA, JUAN MANUEL). Falta que Paola diga qué vendedor le toca.

---

## ⛔ ERRORES CONOCIDOS — NO REPETIR

### 0d. Panel de Cobranzas del back office: vendedor y supervisor en "—"

**Síntoma:** en el panel de Cobranzas, la columna VENDEDOR muestra `—` para
bodegas que **sí tienen vendedor y supervisor** en `bodega_vendedores`.
Reportado por Paola el 04-sep-2026 (CRC-162, CRC-166, CRC-157, CRC-158, CRC-143).

**No es un problema de datos.** Eran dos filtros del endpoint
`admin_cobranzas()` en `app/routes/distribuidor.py` (~línea 901):

1. **`"limit": "2000"`** — inútil. El tope de **1000 filas es del SERVIDOR**
   (PostgREST `db-max-rows`), el mismo bug ya documentado abajo para
   `circa_agente_vendedores.py`. Con **4308 mapeos ABN activos**, el endpoint
   recibía 1000 → **el 77% del panel quedaba sin vendedor.**
2. **`"rol": "eq.ABN"`** — dejaba fuera a los equipos **MERCADOS (324 bodegas)**
   y **CONFITERIA (14)**, que salían sin vendedor aunque su mapeo estuviera
   perfecto. Así se veían las 4 bodegas de mercados de Safra (V0023, V0024,
   V0032). Cada bodega tiene **un único mapeo activo** (4308+324+14 filas =
   4308+324+14 bodegas distintas), así que quitar el filtro no crea ambigüedad.

**Estado: ✅ CORREGIDO el 04-sep-2026.** Ahora filtra por los `bodega_ids` que ya
están en pantalla (66 hoy), en chunks de 200, de modo que ningún request pueda
volver a acercarse al tope de 1000 por mucho que crezca el negocio. Backup:
`app/routes/distribuidor.py.bak-2026-09-04`.

⚠️ **La columna "VENDEDOR" del panel muestra `codigo` + el primer token del
SUPERVISOR**, no el nombre del vendedor (`backoffice.html` línea 1555). Por eso
se lee "V0010 / URBINA": Urbina es el supervisor de Zambrano. No es un error,
pero confunde.

⚠️ **Mismo bug SIN corregir en otros 4 puntos de `distribuidor.py`.** Todos usan
`limit` contra tablas que ya pasan las 1000 filas:

| línea | consulta | filas reales | riesgo |
|---|---|---|---|
| **1252** | `bodegas` limit 2000 — **alerta de sobregiro** | 4686 | **alto**: puede no ver sobregiros |
| 1289 | `bodegas` limit 2000 — lista de bodegas | 4686 | alto |
| 775 | `events` limit 5000/20000, `messages` 10000 | — | dashboard subestimado |
| 945 | `messages` limit 2000 (ordenado desc) | — | bajo: pierde recordatorios viejos |

No se tocaron: quedan fuera del alcance de lo pedido. **Pendiente de decisión.**

---


### 0e. Pagos PARCIALES ignorados: `_abonos_de_pedido()` depende de Flask

**Síntoma:** una bodega que abonó a cuenta aparece en el correo, el Excel y los
mensajes de WhatsApp debiendo el **total completo**. Reportado por Paola el
22-sep-2026 (RABANAL CRC-205 dio S/50 el 21-sep y el reporte seguía diciendo
S/106).

**Causa raíz [Confirmado].** `fees.total_pagar_desde_pedido()` **sí** sabe
descontar abonos: cuando recibe `abonos=None` los busca con
`_abonos_de_pedido()`. Pero esa función usa `app.services.db.sb`, un cliente que
**solo existe dentro de la app Flask**. Desde un script suelto lanza
`SupabaseException: supabase_key is required`, y su `except Exception: return []`
**se traga el error y responde "este pedido no tiene abonos"**.

Es el mismo patrón del bug 0: un fallo técnico disfrazado de dato de negocio.
Aquí "no pude conectarme" se leía como "no pagó nada". Verificado: pasándole los
abonos a mano, la misma función devuelve S/56.

| Pedido | Decía | Real | Abonado |
|---|---:|---:|---:|
| CRC-205 RABANAL | S/106.00 | **S/56.00** | S/50 |
| CRC-240 AVILA | S/51.50 | **S/1.00** | S/50 |

AVILA era el peor: el reporte pedía S/51.50 cuando faltaba **un sol**.

⚠️ **El back office NO tenía el bug**: corre dentro de Flask, `db.sb` existe y
los abonos se descuentan bien. La discrepancia era solo entre el panel y los
archivos diarios — por eso pasó desapercibida.

**Estado: ✅ CORREGIDO el 22-sep-2026** en los dos scripts. Ambos traen los
abonos con su **propio** cliente y los pasan explícitos
(`total_pagar_desde_pedido(..., abonos=...)`). No se tocó `fees.py` ni la base.

· `circa_cobranzas_diario.py` — `abonos_por_pedido` + columnas **Abonado S/** y
  **Saldo a cobrar S/** en el Excel, y aviso en el correo.
· `circa_agente_vendedores.py` — `_adjuntar_abonos()` / `abonado_de()`; grupo y
  privados muestran "· ya abonó S/X 🧾".

Backups: `*.py.bak-2026-09-22`. Efecto en el corte del 22-sep: vencido
S/2,303.64 → **S/2,203.14**; cartera S/6,106.44 → S/6,005.94.

**Regla general:** `id` tiene que estar en el `select` (si no, ni siquiera se
puede cruzar la tabla `abonos`), y **nunca confiar en que una función de
`app/services/` funcione fuera de Flask** — si usa `db.sb`, desde un script
devuelve vacío en silencio. Pasarle los datos explícitos.

---

### 0. Pagos leídos como impagos: `parse_ts` vs. Python 3.10

**Síntoma:** el corte de comisiones marca VENCIDO ("EN ESPERA: bodega atrasada")
a bodegas que **sí pagaron**, y el A PAGAR sale bajo. Reportado por Paola el
31-ago-2026.

**Causa raíz [Confirmado]:** `parse_ts()` en `circa_corte_comisiones.py` usaba
`datetime.fromisoformat`. En **Python < 3.11** esa función solo acepta fracciones
de segundo de **3 o 6 dígitos**. Postgres serializa `fecha_pagado` con los dígitos
significativos que tenga, así que un timestamp como
`2026-08-20T14:44:44.13623+00:00` (5 dígitos) lanzaba `ValueError`, el `except`
lo tragaba y devolvía `None` → el script leía "nunca pagó".

El sandbox corre **Python 3.10.12**. Medición al 31-ago sobre los 140 pedidos
DIMAX con fecha de pago:

| dígitos de fracción | pedidos | ¿legible en 3.10? |
|---|---|---|
| 6 | 123 | ✅ |
| 5 | 9 | ❌ |
| 4 | 2 | ❌ |
| sin fracción | 6 | ✅ |

**11 de 140 pagos (8%) ilegibles.**

**El amplificador:** la regla de calidad del esquema julio ("el bono se paga solo
si la bodega está al día") bloquea **toda** la comisión de la bodega. Un solo pago
mal leído congela activación + recompras + retenciones de esa bodega entera. Por
eso 11 pagos ilegibles produjeron 34 filas VENCIDO.

**Impacto medido en el corte 01→30-ago-2026:**

| | con bug | corregido |
|---|---|---|
| A PAGAR | S/116 | **S/176** |
| EN VUELO | S/51 | S/57 |
| VENCIDO | S/34 | **S/19** |

Bodegas marcadas atrasadas siendo que estaban al día: MARKET TRADING, CAMBA
CASTRO, CANCHARI QUILCA, CHIRA YAÑAC, SOTO BUITRON, CONGACHI ARIAS.
Vendedor más golpeado: Shirley Peña V0014, S/17 → S/49.

**Estado: ✅ CORREGIDO el 31-ago-2026.** `parse_ts` normaliza la fracción a 6
dígitos antes de `fromisoformat`. Backup previo:
`circa_corte_comisiones.py.bak-2026-08-31`.

**Regla general:** nunca parsear timestamps de PostgREST con `fromisoformat`
pelado mientras el entorno sea Python < 3.11. Y desconfiar de todo `except
ValueError: return None` — un fallo de parseo que devuelve `None` en silencio se
disfraza de dato de negocio ("no pagó") y nadie lo nota.

**✅ Retroactivo REVISADO el 31-ago-2026.** Se corrió cada periodo dos veces con
el mismo mapeo actual, una con `parse_ts` roto y otra con el corregido, para
aislar el efecto del bug de cualquier otro cambio:

| corte | A PAGAR con bug | corregido | no pagado por el bug |
|---|---|---|---|
| junio (01/05–30/06) | S/74 | S/79 | **S/5** (solo V0011 Estrada) |
| julio (01/07–31/07) | S/46 | S/74 | **S/28** (V0019 Huaranca S/20 de eso) |
| agosto (01/08–30/08) | S/116 | S/176 | **S/60** |
| | | **TOTAL** | **S/93** |

**Junio y julio se pagaron cortos por S/33.** Agosto se corrigió antes de pagar.

### 0c. ⛔ El arrastre NO se paga en el corte: ya se pagó a inicios de mes

**REGLA DE NEGOCIO [Confirmada por Paola, 31-ago-2026]:** lo que queda
arrastrando (EN VUELO / EN ESPERA al cierre de un corte) se le paga al vendedor
**los primeros días del mes siguiente**, cuando las bodegas terminan de pagar.
Ese pago ocurre **fuera** del corte mensual.

Por lo tanto: **toda línea "(arrastre)" que el script incluya en el corte ya está
pagada y hay que quitarla.** El script oficial no sabe esto y las suma.

En el corte de agosto eran **34 líneas, S/62**, el 35% del A PAGAR.

| vendedor | S/ de arrastre (ya cobrado) |
|---|---|
| V0011 Estrada | 15 |
| V0014 Peña | 15 |
| V0017 Quispe | 7 |
| V0019 Huaranca | 7 |
| V0022 Jaime | 7 |
| V0016 Nizama | 6 |
| V0015 Peralta | 5 |

**Agravante del fix de `parse_ts`:** el modelo de arrastre garantiza "nada se
paga dos veces" solo si todos los cortes usaron la misma lógica. Al corregir
`parse_ts` cambiaron las fechas de pago legibles y con ellas `lib_bodega`, así
que **19 de esas 34 líneas (S/31) ya figuraban explícitamente como "A PAGAR" en
el corte de julio** — reaparecían por segunda vez en el Excel. Verificado
cruzando pedido a pedido contra el Detalle de julio.

**Estado: ✅ manejado en `ajuste_cash_corte.py`** (`quitar_arrastre_ya_pagado()`).
Elimina todas las filas de arrastre en estado A PAGAR, descuenta el monto del
Resumen y del TOTAL, y deja la hoja "Arrastre ya pagado" con la trazabilidad.
Los contadores de afiliaciones/recompras no se tocan: `reg_arrastre` nunca los
alimenta, así que borrar esas filas no los descuadra.

⚠️ **Los cortes viejos NO se pueden reconstruir exactamente.** Dos motivos:
1. Los códigos de vendedor cambiaron: junio/julio usaban `VW172`, `VW263`,
   `VW55`…; hoy son `V0011`, `V0019`, `V0022`. Hay que emparejar por nombre.
2. El mapeo `bodega_vendedores` cambió desde entonces, y el recálculo usa el
   **actual**. Por eso al recalcular julio aparecen diferencias en ambos
   sentidos (Peña −S/9, Quispe −S/2, y un S/5 que pasa de Carlos Garcia a
   Stpefany Trinidad V0038) que **no son del bug** sino de reatribución.
   No leer esas diferencias como dinero faltante.

---

### 0b. Pedido pagado en EFECTIVO que conserva `monto_financiado > 0`

**Síntoma:** una bodega que al final no compró con financiamiento Circa (pagó
todo en efectivo) igual genera comisión de recompra/activación en el corte.
Reportado por Paola el 31-ago-2026.

**Causa raíz [Confirmado]:** al anular el financiamiento se cambia el estado a
`pagado_cash` (o `metodo_pago = 'efectivo'`) pero **no siempre se limpia
`monto_financiado`**. El script decide por `monto_financiado > 0`, así que lo
sigue tratando como financiado.

Contraste con el flujo correcto, ya documentado más abajo: LEIVA GRACIAN
`CRC-150` sí quedó con `monto_financiado = 0.00` → S/0 automático, sin comisión.

**Alcance real medido al 31-ago-2026 sobre todo DIMAX.** Pedidos con
`estado = 'pagado_cash'` OR `metodo_pago = 'efectivo'`:

| Pedido | Bodega | `monto_financiado` | ¿genera comisión? |
|---|---|---|---|
| CRC-023 | SANCHEZ MAGIN SANDRA | 0.00 | no ✅ |
| CRC-061 | CANCHARI QUILCA OLGA | 0.00 | no ✅ |
| CRC-103 | COTRINA ZAFRA ELENA | 0.00 | no ✅ |
| CRC-152 | CALMET DE VASQUEZ MARTHA | 0.00 | no ✅ |
| **CRC-184** | **CASTELLANOS JUAN PEDRO** | **100.00** | **sí ❌ el único malo** |

Para **ese criterio** es un solo pedido. ⚠️ Pero el criterio es estrecho: solo
detecta lo que quedó marcado como cash *en la base*. Si una bodega pagó en
efectivo y nadie lo registró, el pedido sigue como `pagado`/`entregado` con
financiado > 0 y **es indetectable por datos**. Esa parte solo la sabe Paola o el
distribuidor. No volver a afirmar "es el único caso" sin esa aclaración.

Los pedidos *eliminados* (`preventa_cancelada`, `rechazado`) ya los excluye el
script por estado y además todos tienen `monto_financiado = 0`. Verificado sobre
los 6 de agosto: ninguno aparece en la hoja Detalle del corte. Doble seguro.

**Casuística hermana [Confirmado 31-ago-2026]: preventa aceptada SIN entregar
ya paga activación.** Un pedido `preventa_aceptada` con financiado > 0 genera
S/5 de afiliación aunque la bodega todavía no reciba nada:

| Pedido | Bodega | Vendedor | Creado | Entregado |
|---|---|---|---|---|
| CRC-186 | TARAZONA SANCHEZ, GEORGE | V0013 Dancur | 29-ago | **no** |
| CRC-187 | LUNA GUZMAN JORGE LUIS | V0034 Amaro | 29-ago | **no** |

**✅ RESUELTO 01-sep-2026 [Confirmado por Paola].** La activación **NO se paga
ni al aceptar la preventa ni al entregar**: se paga **cuando la bodega paga su
financiamiento**, o sea a los 7 días del despacho. Aceptar y entregar solo
abren el plazo; el gatillo es el pago.

Esto confirma la regla que ya tenía v2 (A PAGAR solo si pagó, si no EN VUELO) —
no había que cambiar el cálculo, solo faltaba la decisión escrita.

Qué pasó con los dos pedidos del caso:

| Pedido | estado al 01-sep | resultado |
|---|---|---|
| CRC-186 TARAZONA S/491.19 | entregado 31-ago, vence 08-sep, sin pagar | **EN VUELO** — se paga cuando Tarazona pague |
| CRC-187 LUNA GUZMAN S/100 | **preventa_cancelada** | **S/0**, se canceló |

⚠️ Ese `preventa_cancelada` de CRC-187 entró **durante el 01-sep**, después de
generar el mensaje de grupo de la mañana — que por eso lo lista como despacho
pendiente. Los pedidos cambian de estado a lo largo del día: un mensaje
generado a las 7am puede quedar desactualizado para el mediodía.

**Señal de que el financiamiento sí se anuló de verdad:** CASTELLANOS tiene
`linea_disponible = 100.00` sobre `linea_aprobada = 100.00`, o sea el cupo está
liberado al 100%. El resto del sistema ya sabe que no debe nada; el único
residuo es el campo del pedido.

**NO genera cobranza fantasma [Confirmado]:** `q_cobranza()` filtra por
`fecha_vencimiento <= mañana` (la de CRC-184 es NULL, no pasa el filtro) y además
descarta estados que contengan "pagado". Doble protección. El daño se limita a
la comisión.

**Estado al 31-ago-2026: ajustado SOLO en el Excel, a pedido de Paola.**
`ajuste_cash_corte.py` regenera el corte neutralizando estos pedidos en memoria
(`monto_financiado → 0`) y escribe archivos con sufijo `_ajustado` + una hoja
"Ajustes" con la trazabilidad. No toca `circa_corte_comisiones.py` ni la base.

⚠️ **El dato sigue MAL en la base y el script oficial sigue sin la regla.**
Mientras no se corrija, conviven dos cifras para el mismo periodo:

| | oficial | ajustado |
|---|---|---|
| A PAGAR | S/176 | S/176 |
| EN VUELO | S/57 | **S/56** |
| VENCIDO | S/19 | S/19 |

**Pendiente de decisión:** (a) corregir `monto_financiado = 0` en CRC-184 en la
base, y/o (b) meter la regla al script oficial: `pagado_cash` /
`metodo_pago = 'efectivo'` nunca generan comisión financiada, sin importar el
monto. Sin (b), el error se repite cada vez que alguien olvide limpiar el campo.

---

### 1. Falsa alerta "bodegas sin día de visita"

**Síntoma:** `circa_agente_vendedores.py` emite por stderr una alerta del tipo:

```
⚠️  ALERTA: bodegas con línea que NUNCA aparecerán en el reporte:
   · ASCARZA PACHECO DELFINA (sin día de visita)
   · ...
```

**Esto es FALSO. No reportarlo como problema de datos.**

**Verificado el 25-ago-2026 (proyecto Supabase `rhxqcoijzgqlecpdfhde`):**

| Métrica | Valor |
|---|---|
| `bodega_vendedores` total | 4735 |
| `bodega_vendedores` con `activo = true` | 4640 |
| de esas, con `dia_visita` NO nulo | **4640 (el 100%)** |
| filas con `dia_visita` nulo | **0** |

**Todas las bodegas mapeadas y activas tienen día de visita. Siempre.** Si el script
dice lo contrario, el script está mal, no la base.

**Causa raíz [Confirmado]:** el servidor PostgREST de Supabase tiene un tope duro de
**1000 filas por respuesta** (`db-max-rows`). La función `q_panorama_linea()`
(~línea 562) hace:

```python
client.table("bodega_vendedores").select("bodega_id,dia_visita").eq("activo", True).execute()
```

sin paginar → recibe **1000 de 4640 filas**. Arma el diccionario `dias_por_bodega`
con ese 21% y luego cruza las ~25 bodegas con `linea_disponible > 0` contra él. Las
que caen fuera de esas 1000 se clasifican como "huérfanas". Es un artefacto de
paginación, no un hueco de datos.

**`.limit(10000)` NO lo arregla** — el tope es del servidor. Comprobado:
`.limit(10000)` sigue devolviendo 1000. La única solución es paginar con `.range()`:

```python
filas, off = [], 0
while True:
    r = client.table("bodega_vendedores").select("bodega_id,dia_visita") \
              .eq("activo", True).range(off, off + 999).execute()
    d = r.data or []
    filas += d
    if len(d) < 1000:
        break
    off += 1000
# → 4640 filas, 0 sin dia_visita
```

**Estado: ✅ CORREGIDO el 25-ago-2026.** Se agregó el helper `fetch_all()` (~línea
126) y se aplicó a las 4 consultas sobre `bodega_vendedores`. La alerta ya no sale.
Backup del script previo: `circa_agente_vendedores.py.bak-2026-08-25`.

---

## ✅ Mismo bug, ya corregido: `q_lineas_aprobadas_por_vendedor()`

Hacía el mismo `.execute()` sin paginar. Alimenta el **modo `--supervisores`**, que
veía solo ~1000 de 4640 mapeos y **fallaba en silencio**, sin alerta alguna. Medido
el 25-ago antes/después del fix:

| | bodegas listadas en `--supervisores` |
|---|---|
| antes | 961 |
| después | **4586** |

Los supervisores llevaban tiempo tomando decisiones con el 21% de su cartera.

## 🔴 Mismo bug, consecuencia GRAVE: cobranzas mal asignadas

El mapa de cartera (~línea 530, el que alimenta `asignar_vendedor_cartera()`) también
consulta `bodega_vendedores` sin paginar → 1000 de 4640. Cuando una bodega cae fuera
del corte, `mapa.get(bodega_id)` devuelve `None` y el script cae al fallback: usa el
vendedor grabado en el pedido, que según el propio docstring del script "puede quedar
como ADMIN" porque las preventas las sube el admin.

**Resultado: cobranzas y despachos taggeados a @CIRCA01 Admin Circa en vez del
vendedor que realmente visita y cobra.** Verificado el 25-ago-2026:

| Bodega | Taggeada en el reporte | Vendedor real (`bodega_vendedores`) |
|---|---|---|
| BURLANDO MENDOZA ARACELI BELIA | @CIRCA01 Admin | **V0014 Peña Shirley** |
| SALAZAR ROJAS MARY DORIS | @CIRCA01 Admin | **V0014 Peña Shirley** |
| SAUCEDO LOPEZ ANITA MARIBEL | @CIRCA01 Admin | **V0014 Peña Shirley** |
| PACARA ASPAJO GIORGIO ANDREE | @CIRCA01 Admin | **V0034 Amaro Ronald** |
| ASCARZA PACHECO DELFINA | @CIRCA01 Admin | **V0019 Huaranca Luis** |

Eran ~S/450 de cobranza que nadie del equipo comercial estaba persiguiendo porque
aparecían a nombre del Admin.

**✅ Corregido el 25-ago-2026.** Verificado tras el fix: 0 menciones de "Admin" en
grupo y privados; las 5 cobranzas quedaron con su vendedor real. El bloque privado
`>>> PARA: CIRCA01 · Admin Circa` desapareció (25 bloques en vez de 26), porque el
Admin no tiene bodegas propias en cartera.

**Regla de negocio: NADA debe salir taggeado como Admin.** [Confirmado por Paola,
25-ago-2026]. Si en una corrida futura aparece `@CIRCA01 Admin Circa` en despachos o
cobranzas, es un bug — significa que `mapa.get(bodega_id)` devolvió `None` y cayó al
fallback. Revisar primero paginación, después si la bodega perdió su mapeo activo.

## ✅ Bomba de tiempo desactivada: `q_visitas_hoy()`

Tenía `.limit(5000)`, que no sirve de nada contra el tope de 1000 del servidor.
Funcionaba solo porque ningún día llegaba a 1000 mapeos. Conteo al 25-ago:

| día | mapeos activos |
|---|---|
| viernes | **844** |
| lunes | 786 |
| jueves | 770 |
| sábado | 766 |
| martes | 755 |
| miércoles | 719 |

Viernes iba en 844: al cruzar 1000, el reporte diario habría empezado a **perder
bodegas en silencio**. Ya usa `fetch_all()`.

## Consultas que AÚN no paginan (hoy no hace falta)

Tres `.execute()` sobre tablas chicas. Volumen medido el 25-ago:

| consulta | filas hoy |
|---|---|
| `q_despachos()` sobre `pedidos` | 239 en total |
| `q_cobranza()` sobre `pedidos` | 125 en alcance |
| `q_panorama_linea()` sobre `bodegas` con `linea_disponible > 0` | 25 |

`pedidos` crece con el negocio. **Cuando se acerque a 1000, paginar con
`fetch_all()`** o cobranzas y despachos empezarán a truncarse sin avisar.

**Regla general para este repo:** toda consulta a `bodega_vendedores` (4735 filas) o
`bodegas` (4686 filas) debe usar `fetch_all()`. Nunca confiar en `.execute()` pelado
ni en `.limit()` — el tope de 1000 es del servidor.

---

## Reglas de negocio confirmadas por Paola

- **La visita al bodeguero ocurre un día ANTES del despacho.** El `dia_visita`
  registrado en `bodega_vendedores` es el día de la visita, no el de la entrega.
- Se le ha vendido a todas las bodegas mapeadas — por eso todas tienen día de visita.

### Casos que PARECEN anomalías y NO lo son — no volver a levantarlos

**`S/0 (no paga)` en la lista de activaciones del mes.** Significa que la bodega
canceló en efectivo al recibir el producto, así que se anuló el financiamiento
Circa. Sin financiamiento no hay comisión. Es el flujo normal, no un error de datos.

- Ejemplo verificado: LEIVA GRACIAN ELVA MELINDA, pedido `CRC-150`. Pedido el
  jueves 20/08, entregado 22/08, `monto_financiado = 0.00`,
  `monto_contado = 106.49`. Pagó todo en efectivo. Amaro no cobra comisión y está
  bien que sea así.
- El pedido conserva una `fecha_vencimiento` residual (29/08) pese a tener
  financiado 0. **No genera cobranza fantasma**: `q_cobranza()` filtra por
  `.gt("monto_financiado", 0)`. Verificado.

**Línea disponible muy baja (ej. `línea S/5.74`).** Significa que la bodega ya
financió casi todo su cupo aprobado. Es señal de uso sano, no de un dato corrupto.

- Ejemplo verificado: ASCARZA PACHECO DELFINA, pedido `CRC-135`. Línea aprobada
  S/100, `monto_financiado = 94.26` → quedan S/5.74 disponibles.
  `monto_contado = 0.00`: financió el monto total de su compra. Todo correcto.
- Efecto secundario cosmético: el script la lista bajo *"YA TIENEN LÍNEA — ¡que
  financien hoy!"* ofreciendo S/5.74, que no es accionable. No es un bug de datos.

### Los `plazo_dias` corren desde la ENTREGA [Confirmado por Paola, 25-ago-2026]

`fecha_vencimiento = fecha_entregado + plazo_dias`. **No** se cuenta desde la visita.
Verificado con ASCARZA `CRC-135`:

| campo | valor |
|---|---|
| `fecha_visita` | 2026-08-18 (martes) |
| `fecha_entregado` | 2026-08-19 (miércoles) |
| `plazo_dias` | 7 |
| `fecha_vencimiento` | **2026-08-26** (miércoles) = entrega + 7 ✅ |

El sistema y el reporte están correctos. Como la visita ocurre un día antes del
despacho, el vencimiento cae un día después de "visita + plazo" — es fácil
confundirse y creer que una bodega vence un día antes de lo que le toca.
**Al conversar sobre vencimientos, contar siempre desde la entrega.**

---

## Entorno de ejecución (sandbox Linux)

`circa_agente_vendedores.py` no corre out-of-the-box en el sandbox. Instalar antes:

```bash
pip install supabase "httpx[socks]" socksio --break-system-packages
```

Sin `socksio` falla con `ImportError: Using SOCKS proxy...`.

Comandos:

```bash
python3 circa_agente_vendedores.py                # mensaje de GRUPO
python3 circa_agente_vendedores.py --privados     # bloques por vendedor
python3 circa_agente_vendedores.py --supervisores # bloques por supervisor
```

Salidas del día se guardan como `CIRCA_Mensaje_Grupo_YYYY-MM-DD.txt` y
`CIRCA_Mensajes_Privados_YYYY-MM-DD.txt`.

## Proyectos Supabase

- **Circa MVP** → `rhxqcoijzgqlecpdfhde` ← es este, el de producción
- `hzlnjwswyfwgrouwpjpy` → proyecto personal, no es Circa
