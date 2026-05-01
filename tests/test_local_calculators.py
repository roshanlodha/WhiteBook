from app.local_calculators import LOCAL_CALCULATORS


def test_local_calculators_registry_is_intentionally_empty() -> None:
    assert LOCAL_CALCULATORS == {}
