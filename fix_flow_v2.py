import json, subprocess, sys

TOKEN = "EAAVSjwOk9msBRJkYpK53eFWkETqDJZAuj1GNGq3WR9QiGwpyV0Jcfa01ZC6EXnzYpc0E7N5dvBJbqOMwLWcHVuidBjLlk0G7V2PRruD7ZANclS6ZA3IS0QccFcfDK3e8nSUAZBfXE40GHZBEUNabKpDZC2IsuycfOu40yEn4nlelSjH7euijL74P8tWij5cZAAZDZD"
FLOW_ID = "1269572371317647"
PHONE_ID = "1076586305533033"
TO = "51993557282"

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return r.stdout.strip()

print("STEP 1: Building corrected Flow JSON...")
with open("app/flows/flow_catalogo.json") as f:
    flow = json.load(f)

# Remove INICIO if leftover
flow["screens"] = [s for s in flow["screens"] if s["id"] != "INICIO"]

# Get CATEGORIAS screen
cat_screen = None
for s in flow["screens"]:
    if s["id"] == "CATEGORIAS":
        cat_screen = s
        break

# Create INICIO as a copy of CATEGORIAS but with different ID
# INICIO is the ENTRY POINT - only reached from the message, never from other screens
# Its on-click navigates to PRODUCTOS (same as CATEGORIAS does)
import copy
inicio = copy.deepcopy(cat_screen)
inicio["id"] = "INICIO"
inicio["title"] = "Catálogo Circa"

# CRITICAL: INICIO's NavigationList on-click must use data_exchange
# which goes to the endpoint. Endpoint will return PRODUCTOS screen.
# This is the same behavior as CATEGORIAS.

# Insert INICIO as first screen
flow["screens"].insert(0, inicio)

# Now fix AGREGADO: its "add more" action should go to CATEGORIAS (not INICIO)
# CATEGORIAS is no longer the first screen, so it CAN have incoming nodes
# INICIO is the first screen and has NO incoming nodes

# Save
with open("app/flows/flow_catalogo.json", "w") as f:
    json.dump(flow, f, indent=2, ensure_ascii=False)
screens = [s["id"] for s in flow["screens"]]
print(f"  Screens: {screens}")
print(f"  Entry: INICIO (no incoming nodes)")
print(f"  CATEGORIAS (has incoming from AGREGADO - OK, not first screen)")

# Step 2: Upload
print("\nSTEP 2: Uploading to Meta...")
result = run(f'curl -s --max-time 60 -X POST "https://graph.facebook.com/v23.0/{FLOW_ID}/assets" -H "Authorization: Bearer {TOKEN}" -F "asset_type=FLOW_JSON" -F "name=flow.json" -F "file=@app/flows/flow_catalogo.json;type=application/json"')
print(f"  {result}")
parsed = json.loads(result)
if parsed.get("success"):
    errors = parsed.get("validation_errors", [])
    if errors:
        print(f"  ⚠️ Validation errors: {json.dumps(errors, indent=2)}")
        # Check if errors are blocking
        for e in errors:
            print(f"    - {e.get('error')}: {e.get('message')}")
    else:
        print("  ✅ No validation errors!")
else:
    print("  ❌ Upload failed!")
    sys.exit(1)

# Step 3: Publish
print("\nSTEP 3: Publishing...")
result = run(f'curl -s --max-time 30 -X POST "https://graph.facebook.com/v23.0/{FLOW_ID}/publish" -H "Authorization: Bearer {TOKEN}"')
print(f"  {result}")

# Step 4: Update endpoint to handle INICIO
print("\nSTEP 4: Updating catalogo.py to handle INICIO screen...")
with open("app/flows/catalogo.py") as f:
    code = f.read()
if 'screen == "INICIO"' not in code:
    code = code.replace(
        'if action in ("INIT", "data_exchange", "navigate") or (not screen and not action):',
        'if action in ("INIT", "data_exchange", "navigate") or screen == "INICIO" or (not screen and not action):'
    )
    with open("app/flows/catalogo.py", "w") as f:
        f.write(code)
    print("  ✅ Added INICIO handler")
else:
    print("  Already has INICIO handler")

# Step 5: Git push + deploy
print("\nSTEP 5: Deploying...")
run('git add -A')
run('git commit -m "Fix: add INICIO entry screen to fix routing model"')
push_result = run('git push origin main')
print(f"  git push: {push_result[-80:]}")
deploy_result = run('railway up 2>&1 | tail -5')
print(f"  railway: {deploy_result}")

# Step 6: Send test with INICIO as entry screen
print("\nSTEP 6: Sending test v17 (entry=INICIO)...")
msg = json.dumps({
    "messaging_product": "whatsapp",
    "to": TO,
    "type": "interactive",
    "interactive": {
        "type": "flow",
        "body": {"text": "📦 Catálogo v17 — INICIO entry"},
        "action": {
            "name": "flow",
            "parameters": {
                "flow_message_version": "3",
                "flow_id": FLOW_ID,
                "flow_cta": "Abrir catálogo",
                "flow_action": "navigate",
                "flow_action_payload": {
                    "screen": "INICIO",
                    "data": {"bodega_id": "b1b2c3d4-0001-4000-8000-000000000001"}
                }
            }
        }
    }
})
result = run(f"""curl -s --max-time 30 -X POST "https://graph.facebook.com/v23.0/{PHONE_ID}/messages" -H "Authorization: Bearer {TOKEN}" -H "Content-Type: application/json" -d '{msg}'""")
print(f"  {result}")

print("\n" + "=" * 50)
print("Open v17 on your PHONE and tell me what happens!")
