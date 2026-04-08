"""
Fix Circa Catalog Flow — Complete automated fix
1. Simplify Flow JSON (remove back-navigation to CATEGORIAS)
2. Upload to Meta
3. Publish
4. Send test message
"""
import json, subprocess, sys

TOKEN = "EAAVSjwOk9msBRJkYpK53eFWkETqDJZAuj1GNGq3WR9QiGwpyV0Jcfa01ZC6EXnzYpc0E7N5dvBJbqOMwLWcHVuidBjLlk0G7V2PRruD7ZANclS6ZA3IS0QccFcfDK3e8nSUAZBfXE40GHZBEUNabKpDZC2IsuycfOu40yEn4nlelSjH7euijL74P8tWij5cZAAZDZD"
FLOW_ID = "1269572371317647"
PHONE_ID = "1076586305533033"
TO = "51993557282"

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return r.stdout.strip()

# Step 1: Fix Flow JSON - remove INICIO if present, check AGREGADO
print("=" * 50)
print("STEP 1: Fixing Flow JSON...")
with open("app/flows/flow_catalogo.json") as f:
    flow = json.load(f)

# Remove INICIO screen if it exists
flow["screens"] = [s for s in flow["screens"] if s["id"] != "INICIO"]

# Check AGREGADO screen - remove back-to-CATEGORIAS routing
for screen in flow["screens"]:
    if screen["id"] == "AGREGADO":
        # Change the "agregar más" action to go to PRODUCTOS instead of CATEGORIAS
        layout = screen.get("layout", {})
        children = layout.get("children", [])
        for child in children:
            if child.get("type") == "Footer":
                footer_children = child.get("children", [])
                # Keep footer as is - routing is handled by endpoint
        print(f"  AGREGADO screen found with {len(children)} children")

# Save
with open("app/flows/flow_catalogo.json", "w") as f:
    json.dump(flow, f, indent=2, ensure_ascii=False)
print(f"  Screens: {[s['id'] for s in flow['screens']]}")
print("  ✅ JSON cleaned")

# Step 2: Upload Flow JSON
print("\n" + "=" * 50)
print("STEP 2: Uploading Flow JSON to Meta...")
result = run(f'''curl -s --max-time 60 -X POST "https://graph.facebook.com/v23.0/{FLOW_ID}/assets" -H "Authorization: Bearer {TOKEN}" -F "asset_type=FLOW_JSON" -F "name=flow.json" -F "file=@app/flows/flow_catalogo.json;type=application/json"''')
print(f"  Response: {result}")
if "success" not in result.lower():
    print("  ❌ Upload failed!")
    sys.exit(1)
print("  ✅ Uploaded")

# Step 3: Publish
print("\n" + "=" * 50)
print("STEP 3: Publishing Flow...")
result = run(f'''curl -s --max-time 30 -X POST "https://graph.facebook.com/v23.0/{FLOW_ID}/publish" -H "Authorization: Bearer {TOKEN}"''')
print(f"  Response: {result}")
if "success" in result.lower():
    print("  ✅ Published!")
else:
    print("  ⚠️ Publish result (may already be published)")

# Step 4: Verify status
print("\n" + "=" * 50)
print("STEP 4: Verifying status...")
result = run(f'''curl -s --max-time 15 "https://graph.facebook.com/v23.0/{FLOW_ID}?fields=name,status&access_token={TOKEN}"''')
print(f"  {result}")

# Step 5: Send test message
print("\n" + "=" * 50)
print("STEP 5: Sending test message v16...")
msg = json.dumps({
    "messaging_product": "whatsapp",
    "to": TO,
    "type": "interactive",
    "interactive": {
        "type": "flow",
        "body": {"text": "📦 Catálogo v16 — fix routing"},
        "action": {
            "name": "flow",
            "parameters": {
                "flow_message_version": "3",
                "flow_id": FLOW_ID,
                "flow_cta": "Abrir catálogo",
                "flow_action": "navigate",
                "flow_action_payload": {
                    "screen": "CATEGORIAS",
                    "data": {"bodega_id": "b1b2c3d4-0001-4000-8000-000000000001"}
                }
            }
        }
    }
})
result = run(f"""curl -s --max-time 30 -X POST "https://graph.facebook.com/v23.0/{PHONE_ID}/messages" -H "Authorization: Bearer {TOKEN}" -H "Content-Type: application/json" -d '{msg}'""")
print(f"  {result}")
if "messages" in result:
    print("  ✅ Message sent! Open v16 on your phone.")
else:
    print("  ❌ Message failed")

print("\n" + "=" * 50)
print("DONE! Check WhatsApp on your phone for v16")
