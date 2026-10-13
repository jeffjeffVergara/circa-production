"""Un contacto sin wa_id no debe tumbar el parseo del webhook."""
from app.services.meta_webhook import parse_incoming


def _payload(contacts, messages=None):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "contacts": contacts,
                    "messages": messages or [{
                        "from": "51992356793",
                        "id": "wamid.1",
                        "timestamp": "1",
                        "type": "text",
                        "text": {"body": "Hola"},
                    }],
                }
            }]
        }],
    }


def test_contacto_sin_wa_id_no_rompe_el_hola():
    parsed = parse_incoming(_payload([{"profile": {"name": "Rosa"}}]))
    assert len(parsed) == 1
    assert parsed[0]["from"] == "51992356793"
    assert parsed[0]["body"] == "Hola"
    assert parsed[0]["name"] == ""


def test_contacto_con_wa_id_sigue_trayendo_el_nombre():
    parsed = parse_incoming(_payload([{
        "wa_id": "51992356793",
        "profile": {"name": "Rosa"},
    }]))
    assert parsed[0]["name"] == "Rosa"
    assert parsed[0]["body"] == "Hola"


def test_un_contacto_malo_no_borra_el_otro_mensaje():
    parsed = parse_incoming(_payload(
        contacts=[{"profile": {"name": "sin id"}}, {"wa_id": "51926156433", "profile": {"name": "Nereyda"}}],
        messages=[
            {"from": "51992356793", "id": "wamid.1", "type": "text", "text": {"body": "Hola"}},
            {"from": "51926156433", "id": "wamid.2", "type": "text", "text": {"body": "Hola"}},
        ],
    ))
    assert [m["from"] for m in parsed] == ["51992356793", "51926156433"]
    assert parsed[0]["name"] == ""
    assert parsed[1]["name"] == "Nereyda"


def test_contacts_null_o_no_objeto_no_rompe():
    assert parse_incoming(_payload(None))[0]["body"] == "Hola"
    assert parse_incoming(_payload(["no-es-objeto", None]))[0]["body"] == "Hola"


def test_hola_sin_telefono_trae_el_identificador():
    parsed = parse_incoming(_payload(
        contacts=[{
            "profile": {"name": "Richar Cervantes", "username": "richar"},
            "user_id": "PE.1105797845152248",
        }],
        messages=[{
            "from_user_id": "PE.1105797845152248",
            "id": "wamid.1",
            "timestamp": "1",
            "type": "text",
            "text": {"body": "Hola"},
        }],
    ))
    assert len(parsed) == 1
    assert parsed[0]["from"] == ""
    assert parsed[0]["user_id"] == "PE.1105797845152248"
    assert parsed[0]["username"] == "richar"
    assert parsed[0]["name"] == "Richar Cervantes"
    assert parsed[0]["body"] == "Hola"


def test_telefono_y_usuario_se_guardan_juntos():
    parsed = parse_incoming(_payload([{
        "wa_id": "51933930934",
        "user_id": "PE.1105797845152248",
        "profile": {"name": "Richar"},
    }], messages=[{
        "from": "51933930934",
        "from_user_id": "PE.1105797845152248",
        "id": "wamid.1",
        "type": "text",
        "text": {"body": "Hola"},
    }]))
    assert parsed[0]["from"] == "51933930934"
    assert parsed[0]["user_id"] == "PE.1105797845152248"
    assert parsed[0]["name"] == "Richar"
