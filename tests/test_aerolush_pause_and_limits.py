"""Regression tests for AeroLush pause reporting and humidity limits."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock

from homeassistant.components.climate.const import HVACAction, HVACMode
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vivosun_growhub.climate import VivosunAeroLushClimateEntity
from custom_components.vivosun_growhub.const import DOMAIN
from custom_components.vivosun_growhub.coordinator import VivosunCoordinator
from custom_components.vivosun_growhub.models import DeviceInfo
from custom_components.vivosun_growhub.shadow import build_aircd_target_humidity_payload

_DEVICE_ID = "aerolush-1"


class _CoordinatorStub:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self._device = DeviceInfo(
            device_id=_DEVICE_ID,
            client_id="vivosun-VSACA08-acc-aerolush-1",
            topic_prefix="prefix/aerolush",
            name="AeroLush C08",
            online=True,
            scene_id=66078,
            device_type="air_conditioner",
        )
        self.is_mqtt_connected = True
        self.async_publish_shadow_update = AsyncMock()

    @property
    def devices(self) -> list[DeviceInfo]:
        return [self._device]

    def get_device(self, device_id: str) -> DeviceInfo | None:
        return self._device if device_id == _DEVICE_ID else None


def _entity(coordinator: _CoordinatorStub) -> VivosunAeroLushClimateEntity:
    entry = MockConfigEntry(domain=DOMAIN, title="t", data={}, options={})
    return VivosunAeroLushClimateEntity(
        cast("VivosunCoordinator", coordinator), entry, _DEVICE_ID
    )


def test_aerolush_pause_reports_idle_while_mode_remains_dry() -> None:
    coordinator = _CoordinatorStub()
    coordinator.data = {
        "shadows": {
            _DEVICE_ID: {
                "aircd": {
                    "state": 1,
                    "function": 3,
                    "pause": 1,
                    "target_humidity": 4000,
                }
            }
        }
    }
    entity = _entity(coordinator)

    assert entity.hvac_mode == HVACMode.DRY
    assert entity.hvac_action == HVACAction.IDLE
    assert entity.extra_state_attributes["pause"] == 1
    assert entity.extra_state_attributes["activity_status"] == "idle"


def test_aerolush_dry_action_is_unverified_without_runtime_signal() -> None:
    coordinator = _CoordinatorStub()
    raw_aircd = {
        "state": 1,
        "func": 3,
        "pause": 0,
        "wdLv": 100,
        "tHumi": 4000,
        "unknownRuntimeField": 7,
    }
    coordinator.data = {
        "shadows": {
            _DEVICE_ID: {
                "aircd": {
                    "state": 1,
                    "function": 3,
                    "pause": 0,
                    "fan_level": 100,
                    "target_humidity": 4000,
                },
                "reported_supported": {"aircd": raw_aircd},
            }
        }
    }
    entity = _entity(coordinator)

    assert entity.hvac_mode == HVACMode.DRY
    assert entity.hvac_action is None
    assert entity.extra_state_attributes["activity_status"] == "unverified"
    assert entity.extra_state_attributes["raw_aircd"] == raw_aircd


def test_aerolush_off_action_remains_off() -> None:
    coordinator = _CoordinatorStub()
    coordinator.data = {
        "shadows": {
            _DEVICE_ID: {
                "aircd": {
                    "state": 0,
                    "function": 3,
                    "pause": 0,
                }
            }
        }
    }
    entity = _entity(coordinator)

    assert entity.hvac_mode == HVACMode.OFF
    assert entity.hvac_action == HVACAction.OFF
    assert entity.extra_state_attributes["activity_status"] == "off"


def test_aerolush_humidity_minimum_is_40_percent() -> None:
    coordinator = _CoordinatorStub()
    entity = _entity(coordinator)

    assert entity.min_humidity == 40
    assert entity.max_humidity == 100


async def test_aerolush_set_humidity_clamps_to_40_percent() -> None:
    coordinator = _CoordinatorStub()
    entity = _entity(coordinator)

    await entity.async_set_humidity(30)

    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_target_humidity_payload(4000), device_id=_DEVICE_ID
    )
