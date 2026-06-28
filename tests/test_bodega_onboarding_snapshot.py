from app.services.bodega_onboarding_snapshot import (
    onboarding_alta_fields,
    scoring_alta_from_linea,
    tier_from_linea,
)


def test_tier_from_linea():
    assert tier_from_linea(50) == 100
    assert tier_from_linea(500) == 500
    assert tier_from_linea(999) == 500


def test_scoring_alta_from_linea():
    assert scoring_alta_from_linea(100) == 58
    assert scoring_alta_from_linea(300) == 76
    assert scoring_alta_from_linea(500) == 90


def test_onboarding_alta_fields():
    snap = onboarding_alta_fields(300)
    assert snap["linea_alta"] == 300
    assert snap["scoring_alta"] == 76
