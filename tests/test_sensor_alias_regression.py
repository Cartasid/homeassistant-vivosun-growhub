"""Regression tests for controller sensor fallback channel aliases."""

from custom_components.vivosun_growhub.sensor import _ALL_SENSOR_DESCRIPTIONS


def test_e42a_plus_fallback_aliases_match_upstream_mapping() -> None:
    """Probe data is inside; built-in data is outside on E42A+ fallback payloads."""
    descriptions = {description.channel_key: description for description in _ALL_SENSOR_DESCRIPTIONS}

    assert descriptions["inTemp"].channel_key_aliases == ("pTemp",)
    assert descriptions["inHumi"].channel_key_aliases == ("pHumi",)
    assert descriptions["inVpd"].channel_key_aliases == ("pVpd",)
    assert descriptions["outTemp"].channel_key_aliases == ("bTemp",)
    assert descriptions["outHumi"].channel_key_aliases == ("bHumi",)
    assert descriptions["outVpd"].channel_key_aliases == ("bVpd",)
