import json, subprocess

TOKEN = "EAAVSjwOk9msBRJkYpK53eFWkETqDJZAuj1GNGq3WR9QiGwpyV0Jcfa01ZC6EXnzYpc0E7N5dvBJbqOMwLWcHVuidBjLlk0G7V2PRruD7ZANclS6ZA3IS0QccFcfDK3e8nSUAZBfXE40GHZBEUNabKpDZC2IsuycfOu40yEn4nlelSjH7euijL74P8tWij5cZAAZDZD"
FLOW_ID = "1269572371317647"
PHONE_ID = "1076586305533033"
TO = "51993557282"

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    return r.stdout.strip()

# Step 1: Create minimal Flow JSON
print("STEP 1: Creating minimal Flow JSON...")
flow = {
    "version": "3.0",
    "data_api_version": "3.0",
    "routing_model": {
        "CATALOG": ["CATALOG"],
    },
    "screens": [
        {
            "id": "CATALOG",
            "title": "Catálogo Circa",
            "data": {
                "categorias": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "main-content": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "description": {"type": "string"}
                                }
                            }
                        }
                    },
                    "__example__": [{"id": "bebidas", "main-content": {"title": "Bebidas", "description": "Gaseosas, agua, jugos"}}]
                },
                "bodega_id": {"type": "string", "__example__": "test"},
                "distribuidor_id": {"type": "string", "__example__": "test"},
                "cart_summary": {"type": "string", "__example__": ""}
            },
            "layout": {
                "type": "SingleColumnLayout",
                "children": [
                    {
                        "type": "NavigationList",
                        "name": "cat_selection",
                        "label": "Elige una categoria",
                        "list-items": "${data.categorias}",
                        "on-click-action": {
                            "name": "data_exchange",
                            "payload": {
                                "categoria": "${form.cat_selection}",
                                "bodega_id": "${data.bodega_id}",
                                "distribuidor_id": "${data.distribuidor_id}"
                            }
                        }
                    }
                ]
            }
        }
    ]
}

with open("app/flows/flow_catalogo.json", "w") as f:
    json.dump(flow, f, indent=2, ensure_ascii=False)
print("  Screens: CATALOG (single screen, self-referencing)")
print("  ✅ JSON created")

# Step 2: Upload
print("\nSTEP 2: Uploading...")
result = run(f'curl -s --max-time 60 -X POST "https://graph.facebook.com/v23.0/{FLOW_ID}/assets" -H "Authorization: Bearer {TOKEN}" -F "asset_type=FLOW_JSON" -F "name=flow.json" -F "file=@app/flows/flow_catalogo.json;type=application/json"')
print(f"  {result}")

# Step 3: Publish
print("\nSTEP 3: Publishing...")
result = run(f'curl -s --max-time 30 -X POST "https://graph.facebook.com/v23.0/{FLOW_ID}/publish" -H "Authorization: Bearer {TOKEN}"')
print(f"  {result}")

# Step 4: Update endpoint
print("\nSTEP 4: Updating catalogo.py...")
with open("app/flows/catalogo.py") as f:
    code = f.read()

# Make _screen_categorias return CATALOG screen (not CATEGORIAS)
code = code.replace('"screen": "CATEGORIAS"', '"screen": "CATALOG"')
# Also handle CATALOG in the router
if '"CATALOG"' not in code:
    code = code.replace(
        '"CATEGORIAS": _handle_categoria_selected,',
        '"CATALOG": _handle_categoria_selected,\n        "CATEGORIAS": _handle_categoria_selected,'
    )
with open("app/flows/catalogo.py", "w") as f:
    f.write(code)
print("  ✅ Updated")

# Step 5: Deploy
print("\nSTEP 5: Deploying...")
run("git add -A")
run('git commit -m "Minimal single-screen flow to fix routing"')
run("git push origin main")
deploy = run("railway up 2>&1 | tail -3")
print(f"  {deploy}")

# Step 6: Send test
print("\nSTEP 6: Sending v18...")
msg = json.dumps({
    "messaging_product": "whatsapp", "to": TO,
    "type": "interactive",
    "interactive": {
        "type": "flow",
        "body": {"text": "📦 Catálogo v18 — minimal flow"},
        "action": {"name": "flow", "parameters": {
            "flow_message_version": "3",
            "flow_id": FLOW_ID,
            "flow_cta": "Abrir catálogo",
            "flow_action": "navigate",
            "flow_action_payload": {
                "screen": "CATALOG",
                "data": {"bodega_id": "b1b2c3d4-0001-4000-8000-000000000001"}
            }
        }}
    }
})
result = run(f"""curl -s --max-time 30 -X POST "https://graph.facebook.com/v23.0/{PHONE_ID}/messages" -H "Authorization: Bearer {TOKEN}" -H "Content-Type: application/json" -d '{msg}'""")
print(f"  {result}")
print("\n✅ Open v18 on your PHONE!")
