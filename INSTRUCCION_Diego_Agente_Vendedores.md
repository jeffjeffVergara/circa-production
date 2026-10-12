# Cómo correr el Agente Diario de Vendedores (para Diego · Mac)

Guía para dejar corriendo `circa_agente_vendedores.py` en tu Mac, conectado a la
Supabase de Circa (la misma de producción).

**Qué hace:** genera los mensajes diarios de WhatsApp (mensaje de grupo + privados
por vendedor). **Solo lee** de la base de datos e imprime texto en pantalla —
**no escribe, no modifica ni borra nada** en Supabase. Correrlo es seguro.

---

## ⚠️ Antes de empezar — lee esto

El archivo principal **`circa_agente_vendedores.py` NO está en el repositorio de
GitHub** (vive solo en la carpeta local de Paola). Los demás archivos que necesita
(`circa_corte_comisiones.py`, `app/services/fees.py`) sí están en el repo.

Por eso el setup tiene dos fuentes:

1. **Del repo de GitHub** → todo menos el agente.
2. **De Paola, aparte** → el archivo `circa_agente_vendedores.py` (versión actual,
   con la cobranza incluida en los privados).

---

## Requisitos previos

- **Python 3.10 o superior** (el proyecto usa 3.12). Verifica con:
  ```bash
  python3 --version
  ```
- **git** instalado.
- **Acceso al repo privado** `github.com/palisacpe-crypto/circa-production` (pídele
  a Paola que te agregue como colaborador).
- **Credenciales de Supabase** (`SUPABASE_URL` y `SUPABASE_KEY`) — te las pasa Paola
  de forma segura (ver Paso 3). No las pongas en ningún chat público.

---

## Paso 1 — Clonar el repo y entrar

```bash
git clone https://github.com/palisacpe-crypto/circa-production.git
cd circa-production
```

Esto te trae `circa_corte_comisiones.py` y la carpeta `app/` (con `services/fees.py`),
que el agente necesita.

## Paso 2 — Copiar el archivo del agente

Pídele a Paola el archivo **`circa_agente_vendedores.py`** (por AirDrop, Drive o
Slack) y colócalo en la **raíz del repo**, junto a `circa_corte_comisiones.py`:

```
circa-production/
├── circa_agente_vendedores.py   ← este te lo pasa Paola
├── circa_corte_comisiones.py    ← viene del repo
└── app/
    └── services/
        └── fees.py              ← viene del repo
```

> Importante: los tres deben quedar en esas rutas. El agente importa a los otros dos
> por ruta relativa; si los mueves, deja de calcular comisiones o el total a pagar.

## Paso 3 — Entorno de Python e instalar la dependencia

El agente tiene **una sola dependencia externa: `supabase`**. Crea un entorno
aislado e instálala:

```bash
python3 -m venv venv
source venv/bin/activate
pip install supabase
```

*(Si prefieres instalar todo el stack del proyecto: `pip install -r requirements.txt`,
pero no es necesario para este agente.)*

## Paso 4 — Crear el archivo `.env`

En la raíz del repo, crea un archivo llamado `.env` con estas dos líneas:

```
SUPABASE_URL=<te lo pasa Paola>
SUPABASE_KEY=<te lo pasa Paola>
```

- Son **exactamente los mismos valores** del `.env` que ya usa Paola.
- `SUPABASE_KEY` es la clave con permisos de lectura completa (service role): trátala
  como una contraseña. **Nunca** la subas a GitHub ni la pegues en un chat abierto.
- El `.env` ya está en `.gitignore`, así que git no lo va a subir. Verifica que sea
  así antes de hacer cualquier commit.

## Paso 5 — Correr el agente

Con el `venv` activado (`source venv/bin/activate`):

```bash
# Mensaje de GRUPO
python3 circa_agente_vendedores.py

# Mensajes PRIVADOS (uno por vendedor, con su cobranza del día)
python3 circa_agente_vendedores.py --privados

# Copiar la salida directo al portapapeles (Mac)
python3 circa_agente_vendedores.py --copiar
python3 circa_agente_vendedores.py --privados --copiar
```

Cada privado sale con una línea `>>> PARA: Vxxxx · Nombre · wa.me/…` como título;
esa línea es tu guía para saber a quién pegarle el mensaje — **no se pega**, solo va
el texto de abajo.

---

## Verificación rápida

Corre `python3 circa_agente_vendedores.py`. Si ves el mensaje de grupo con la fecha
de hoy, despachos, cobranzas y comisiones → está conectado y funcionando.

Si en `stderr` aparece un aviso con `⚠️` o `⛔`, no es un error del programa: son
alertas para revisar (bodegas con línea que no aparecen, pedidos sin atribuir, etc.).

---

## Problemas comunes

| Síntoma | Causa / solución |
|---|---|
| `ModuleNotFoundError: No module named 'supabase'` | No activaste el `venv` o no instalaste la dependencia. Corre `source venv/bin/activate` y `pip install supabase`. |
| `❌ Faltan SUPABASE_URL / SUPABASE_KEY` | No existe el `.env` en la raíz, o le faltan las variables. Revisa el Paso 4. |
| El mensaje sale **sin** el bloque de comisiones | Falta `circa_corte_comisiones.py` en la raíz, o no calculó. El agente avisa por `stderr` y sigue sin ese bloque. |
| Los montos de cobranza salen "crudos" (sin mora/true-up) | Falta `app/services/fees.py` o su ruta. Verifica la estructura del Paso 2. |
| `Using SOCKS proxy … socksio not installed` | Solo pasa detrás de un proxy SOCKS corporativo. Si te sale: `pip install "httpx[socks]"`. En una red normal no aparece. |

---

## Nota para mantenerlo al día

Como el agente **no está en el repo**, cada vez que Paola lo actualice (nuevos copys,
cambios de lógica) tiene que reenviarte el archivo. Alternativa más limpia: subir
`circa_agente_vendedores.py` al repo para que baste con `git pull`. Habla eso con Paola.
