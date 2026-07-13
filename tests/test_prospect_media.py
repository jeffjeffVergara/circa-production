"""2.2 — fotos de prospectos se guardan en Storage (no solo media_id de Meta)."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ.setdefault("SUPABASE_KEY", "test-key")

from app.services import prospect_media as pm
from app.state_machine import _handle_prospecto


def test_parse_ruc_o_dni():
    assert pm.parse_ruc_o_dni("20123456789") == ("20123456789", None)
    assert pm.parse_ruc_o_dni("42868000") == (None, "42868000")
    assert pm.parse_ruc_o_dni("hola") == (None, None)


def test_kind_for_paso():
    assert pm.kind_for_paso("esperando_dni_foto") == "dni"
    assert pm.kind_for_paso("esperando_local_foto") == "local"
    assert pm.kind_for_paso("esperando_datos") == "otro"


def test_persist_image_bytes_dni_path():
    with patch.object(pm, "upload_bytes", return_value=True) as up:
        saved = pm.persist_image_bytes("51999999999", b"fake", "dni", "image/jpeg")
    assert saved is not None
    assert saved["bucket"] == "dni_fotos"
    assert saved["kind"] == "dni"
    assert "prospecto/+51999999999/dni_" in saved["path"]
    up.assert_called_once()


def test_persist_image_bytes_local_bucket():
    with patch.object(pm, "upload_bytes", return_value=True):
        saved = pm.persist_image_bytes("+51988887777", b"x", "local")
    assert saved["bucket"] == "sustentos"
    assert "/local_" in saved["path"]


def test_prospecto_flow_texto_luego_fotos(monkeypatch):
    store = {}

    def fake_upsert(tel, fase, datos=None, bodega_id=None):
        store["session"] = {"fase": fase, "datos": dict(datos or {}), "telefono": tel}

    def fake_get(tel):
        return store.get("session")

    monkeypatch.setattr(pm.db, "upsert_session", fake_upsert)
    monkeypatch.setattr(pm.db, "get_session", fake_get)
    monkeypatch.setattr("app.services.db.upsert_session", fake_upsert)
    monkeypatch.setattr("app.services.db.get_session", fake_get)

    # 1) Hola
    r1 = _handle_prospecto("51911112222", "Hola", "HOLA", None, None)
    assert "Bienvenido" in r1[0]
    assert store["session"]["fase"] == "prospecto"
    assert store["session"]["datos"]["paso"] == "esperando_datos"

    # 2) DNI
    sess = store["session"]
    r2 = _handle_prospecto("51911112222", "42868000", "42868000", None, sess)
    assert "foto de tu DNI" in r2[0]
    assert store["session"]["datos"]["dni"] == "42868000"
    assert store["session"]["datos"]["paso"] == "esperando_dni_foto"

    # 3) Foto DNI
    def fake_persist(tel, media_id, kind, mime_type=None):
        return {"bucket": "dni_fotos", "path": f"prospecto/{tel}/dni_x.jpg", "kind": kind}

    monkeypatch.setattr(pm, "persist_image_from_media_id", fake_persist)
    sess = store["session"]
    r3 = _handle_prospecto("51911112222", "__IMAGE__", "IMAGE", "media-dni-1", sess)
    assert "foto de tu local" in r3[0].lower() or "local" in r3[0].lower()
    assert store["session"]["datos"]["paso"] == "esperando_local_foto"
    assert store["session"]["datos"]["dni_foto_path"]

    # 4) Foto local
    def fake_persist_local(tel, media_id, kind, mime_type=None):
        return {"bucket": "sustentos", "path": f"prospecto/{tel}/local_x.jpg", "kind": kind}

    monkeypatch.setattr(pm, "persist_image_from_media_id", fake_persist_local)
    sess = store["session"]
    r4 = _handle_prospecto("51911112222", "__IMAGE__", "IMAGE", "media-local-1", sess)
    assert "24 horas" in r4[0] or "Listo" in r4[0]
    assert store["session"]["datos"]["paso"] == "completo"
    assert store["session"]["datos"]["local_foto_path"]
