"""Tests for Vivosun climate platform."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.const import UnitOfTemperature
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vivosun_growhub.climate import (
    VivosunAeroLushClimateEntity,
    VivosunHeaterClimateEntity,
    async_setup_entry,
)
from custom_components.vivosun_growhub.const import DOMAIN, MODE_AUTO, MODE_MANUAL
from custom_components.vivosun_growhub.models import DeviceInfo, RuntimeData
from custom_components.vivosun_growhub.shadow import (
    build_aircd_fan_level_payload,
    build_aircd_payload,
    build_aircd_state_payload,
    build_aircd_target_humidity_payload,
    build_aircd_target_temp_payload,
    build_heat_mode_payload,
    build_heat_on_payload,
    build_heat_target_payload,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity import Entity

    from custom_components.vivosun_growhub.coordinator import VivosunCoordinator

_DEV_ID = "heater-1"


class _StubCoordinator:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self._device = DeviceInfo(
            device_id=_DEV_ID,
            client_id="vivosun-VSHEATW70-acc-heater-1",
            topic_prefix="prefix/heater",
            name="AeroFlux W70",
            online=True,
            scene_id=66078,
            device_type="heater",
        )
        self.is_mqtt_connected = True
        self.async_publish_shadow_update = AsyncMock()

    @property
    def devices(self) -> list[DeviceInfo]:
        return [self._device]

    def get_device(self, device_id: str) -> DeviceInfo | None:
        if device_id == self._device.device_id:
            return self._device
        return None


def _make_entity(
    coordinator: _StubCoordinator, *, temp_unit: str = "celsius"
) -> VivosunHeaterClimateEntity:
    entry = MockConfigEntry(domain=DOMAIN, title="t", data={}, options={"temp_unit": temp_unit})
    return VivosunHeaterClimateEntity(cast("VivosunCoordinator", coordinator), entry, _DEV_ID)


async def test_climate_setup_creates_one_entity(hass: HomeAssistant) -> None:
    coordinator = _StubCoordinator()
    entry = MockConfigEntry(domain=DOMAIN, title="t", data={})
    runtime = RuntimeData(entry_id=entry.entry_id, coordinator=cast("VivosunCoordinator", coordinator))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    added: list[VivosunHeaterClimateEntity] = []

    def _add(new_entities: Iterable[Entity], update_before_add: bool = False) -> None:
        _ = update_before_add
        added.extend(cast("Iterable[VivosunHeaterClimateEntity]", new_entities))

    await async_setup_entry(hass, entry, _add)

    assert len(added) == 1
    assert added[0].unique_id == f"vivosun_growhub_{_DEV_ID}_climate"


async def test_climate_state_mapping_in_celsius() -> None:
    coordinator = _StubCoordinator()
    coordinator.data = {
        "shadows": {
            _DEV_ID: {
                "heat": {
                    "on": True,
                    "state": 1,
                    "mode": MODE_AUTO,
                    "target_temp": 2350,
                    "level": 7,
                },
                "connection": {"connected": True},
            }
        },
        "sensors": {_DEV_ID: {"pTemp": 2175}},
    }
    entity = _make_entity(coordinator)

    assert entity.temperature_unit == UnitOfTemperature.CELSIUS
    assert entity.hvac_mode == HVACMode.HEAT
    assert entity.hvac_action == HVACAction.HEATING
    assert entity.target_temperature == 23.5
    assert entity.current_temperature == 21.75
    assert entity.preset_mode == "auto"
    assert entity.extra_state_attributes == {"level": 7}
    assert entity.available is True
    assert entity.device_info.get("model") == "VSHEATW70"


async def test_climate_state_mapping_in_fahrenheit() -> None:
    coordinator = _StubCoordinator()
    coordinator.data = {
        "shadows": {_DEV_ID: {"heat": {"on": True, "state": 0, "mode": MODE_MANUAL, "target_temp": 2350}}},
        "sensors": {_DEV_ID: {"pTemp": 2175}},
    }
    entity = _make_entity(coordinator, temp_unit="fahrenheit")

    assert entity.temperature_unit == UnitOfTemperature.FAHRENHEIT
    assert entity.hvac_mode == HVACMode.HEAT
    assert entity.hvac_action == HVACAction.IDLE
    assert entity.target_temperature == pytest.approx(74.3)
    assert entity.current_temperature == pytest.approx(71.15)
    assert entity.preset_mode == "manual"


async def test_climate_fahrenheit_bounds_match_display_unit() -> None:
    coordinator = _StubCoordinator()
    entity = _make_entity(coordinator, temp_unit="fahrenheit")

    assert entity.min_temp == 32
    assert entity.max_temp == 104


async def test_climate_commands_publish_expected_shadow_payloads() -> None:
    coordinator = _StubCoordinator()
    entity = _make_entity(coordinator)

    await entity.async_set_hvac_mode(HVACMode.HEAT)
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_heat_on_payload(True), device_id=_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    await entity.async_turn_off()
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_heat_on_payload(False), device_id=_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    await entity.async_set_temperature(temperature=23.5)
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_heat_target_payload(2350), device_id=_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    entity_f = _make_entity(coordinator, temp_unit="fahrenheit")
    await entity_f.async_set_temperature(temperature=77.0)
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_heat_target_payload(2500), device_id=_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    await entity.async_set_preset_mode("auto")
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_heat_mode_payload(MODE_AUTO), device_id=_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    await entity.async_set_preset_mode("manual")
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_heat_mode_payload(MODE_MANUAL), device_id=_DEV_ID
    )


_AC_DEV_ID = "aerolush-1"


class _AeroLushStubCoordinator:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self._device = DeviceInfo(
            device_id=_AC_DEV_ID,
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
        if device_id == self._device.device_id:
            return self._device
        return None


def _make_ac_entity(
    coordinator: _AeroLushStubCoordinator, *, temp_unit: str = "celsius"
) -> VivosunAeroLushClimateEntity:
    entry = MockConfigEntry(domain=DOMAIN, title="t", data={}, options={"temp_unit": temp_unit})
    return VivosunAeroLushClimateEntity(cast("VivosunCoordinator", coordinator), entry, _AC_DEV_ID)


async def test_climate_setup_creates_aerolush_entity(hass: HomeAssistant) -> None:
    coordinator = _AeroLushStubCoordinator()
    entry = MockConfigEntry(domain=DOMAIN, title="t", data={})
    runtime = RuntimeData(entry_id=entry.entry_id, coordinator=cast("VivosunCoordinator", coordinator))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    added: list[VivosunAeroLushClimateEntity] = []

    def _add(new_entities: Iterable[Entity], update_before_add: bool = False) -> None:
        _ = update_before_add
        added.extend(cast("Iterable[VivosunAeroLushClimateEntity]", new_entities))

    await async_setup_entry(hass, entry, _add)

    assert len(added) == 1
    assert isinstance(added[0], VivosunAeroLushClimateEntity)
    assert added[0].unique_id == f"vivosun_growhub_{_AC_DEV_ID}_aerolush_c08_climate"


async def test_aerolush_state_mapping_cool_in_celsius() -> None:
    coordinator = _AeroLushStubCoordinator()
    coordinator.data = {
        "shadows": {
            _AC_DEV_ID: {
                "aircd": {
                    "state": 1,
                    "on": True,
                    "function": 1,
                    "fan_level": 100,
                    "target_temp": 2398,
                    "target_humidity": 4966,
                    "in_plan": 0,
                    "pause": 0,
                },
                "connection": {"connected": True},
            }
        },
        "sensors": {_AC_DEV_ID: {"pTemp": 2175, "pHumi": 5012}},
    }
    entity = _make_ac_entity(coordinator)

    assert entity.temperature_unit == UnitOfTemperature.CELSIUS
    assert entity.hvac_mode == HVACMode.COOL
    assert entity.hvac_action == HVACAction.COOLING
    assert entity.target_temperature == pytest.approx(23.98)
    assert entity.target_humidity == pytest.approx(49.66)
    assert entity.current_temperature == pytest.approx(21.75)
    assert entity.current_humidity == pytest.approx(50.12)
    assert entity.fan_mode == "standard"
    assert entity.available is True
    assert entity.device_info.get("model") == "VSACA08"
    assert entity.extra_state_attributes == {
        "raw_state": 1,
        "raw_function": 1,
        "raw_fan_level": 100,
        "in_plan": 0,
        "pause": 0,
    }


async def test_aerolush_hvac_mode_off_and_function_modes() -> None:
    coordinator = _AeroLushStubCoordinator()
    coordinator.data = {"shadows": {_AC_DEV_ID: {"aircd": {"state": 0}}}}
    entity = _make_ac_entity(coordinator)
    assert entity.hvac_mode == HVACMode.OFF
    assert entity.hvac_action == HVACAction.OFF

    for func, mode, action in (
        (2, HVACMode.HEAT, HVACAction.HEATING),
        (3, HVACMode.DRY, HVACAction.DRYING),
        (4, HVACMode.FAN_ONLY, HVACAction.FAN),
    ):
        coordinator.data = {"shadows": {_AC_DEV_ID: {"aircd": {"state": 1, "function": func}}}}
        assert entity.hvac_mode == mode
        assert entity.hvac_action == action


async def test_aerolush_fahrenheit_bounds_and_conversion() -> None:
    coordinator = _AeroLushStubCoordinator()
    coordinator.data = {
        "shadows": {_AC_DEV_ID: {"aircd": {"state": 1, "function": 1, "target_temp": 2400}}},
        "sensors": {_AC_DEV_ID: {"inTemp": 2000}},
    }
    entity = _make_ac_entity(coordinator, temp_unit="fahrenheit")

    assert entity.temperature_unit == UnitOfTemperature.FAHRENHEIT
    assert entity.min_temp == pytest.approx(50.0)
    assert entity.max_temp == pytest.approx(104.0)
    assert entity.target_temperature == pytest.approx(75.2)
    assert entity.current_temperature == pytest.approx(68.0)


async def test_aerolush_commands_publish_expected_shadow_payloads() -> None:
    coordinator = _AeroLushStubCoordinator()
    entity = _make_ac_entity(coordinator)

    await entity.async_set_hvac_mode(HVACMode.COOL)
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_payload({"state": 1, "func": 1}), device_id=_AC_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    await entity.async_set_hvac_mode(HVACMode.OFF)
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_state_payload(False), device_id=_AC_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    await entity.async_set_temperature(temperature=24.0)
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_target_temp_payload(2400), device_id=_AC_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    entity_f = _make_ac_entity(coordinator, temp_unit="fahrenheit")
    await entity_f.async_set_temperature(temperature=75.2)
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_target_temp_payload(2400), device_id=_AC_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    await entity.async_set_humidity(55)
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_target_humidity_payload(5500), device_id=_AC_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    await entity.async_set_fan_mode("quiet")
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_fan_level_payload(50), device_id=_AC_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    await entity.async_set_fan_mode("standard")
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_fan_level_payload(100), device_id=_AC_DEV_ID
    )


async def test_aerolush_turn_on_defaults_to_fan_only_without_known_function() -> None:
    coordinator = _AeroLushStubCoordinator()
    entity = _make_ac_entity(coordinator)

    await entity.async_turn_on()
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_payload({"state": 1, "func": 4}), device_id=_AC_DEV_ID
    )

    coordinator.async_publish_shadow_update.reset_mock()
    coordinator.data = {"shadows": {_AC_DEV_ID: {"aircd": {"state": 0, "function": 1}}}}
    await entity.async_turn_on()
    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_state_payload(True), device_id=_AC_DEV_ID
    )
