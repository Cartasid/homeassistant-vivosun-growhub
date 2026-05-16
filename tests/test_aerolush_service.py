"""Tests for the set_aerolush_aircd diagnostic/fallback service."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vivosun_growhub import async_setup_entry, async_unload_entry
from custom_components.vivosun_growhub.const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    DOMAIN,
    SERVICE_SET_AEROLUSH_AIRCD,
)
from custom_components.vivosun_growhub.models import DeviceInfo
from custom_components.vivosun_growhub.shadow import build_aircd_payload

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest import MonkeyPatch

_AC_DEV_ID = "aerolush-1"
_OTHER_DEV_ID = "heater-1"


class _CoordinatorStub:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self._devices = [
            DeviceInfo(
                device_id=_AC_DEV_ID,
                client_id="vivosun-VSACA08-acc-aerolush-1",
                topic_prefix="prefix/aerolush",
                name="AeroLush C08",
                online=True,
                scene_id=1,
                device_type="air_conditioner",
            ),
            DeviceInfo(
                device_id=_OTHER_DEV_ID,
                client_id="vivosun-VSHTW70-acc-heater-1",
                topic_prefix="prefix/heater",
                name="AeroFlux W70",
                online=True,
                scene_id=1,
                device_type="heater",
            ),
        ]
        self.async_publish_shadow_update = AsyncMock()

    @property
    def devices(self) -> list[DeviceInfo]:
        return list(self._devices)

    async def async_start(self) -> None:
        return None

    async def async_shutdown(self) -> None:
        return None


async def _setup(
    hass: HomeAssistant, monkeypatch: MonkeyPatch
) -> tuple[MockConfigEntry, _CoordinatorStub]:
    monkeypatch.setattr("custom_components.vivosun_growhub.VivosunCoordinator", _CoordinatorStub)
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", AsyncMock(return_value=True))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="test@example.com",
        data={CONF_EMAIL: "test@example.com", CONF_PASSWORD: "secret"},
    )
    assert await async_setup_entry(hass, entry)
    coordinator = cast("_CoordinatorStub", hass.data[DOMAIN][entry.entry_id].coordinator)
    return entry, coordinator


async def test_set_aerolush_aircd_auto_resolves_single_air_conditioner(
    hass: HomeAssistant, monkeypatch: MonkeyPatch
) -> None:
    _, coordinator = await _setup(hass, monkeypatch)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_AEROLUSH_AIRCD,
        {"state": 1, "func": 1, "tTemp": 2400},
        blocking=True,
    )

    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_payload({"state": 1, "func": 1, "tTemp": 2400}),
        device_id=_AC_DEV_ID,
    )


async def test_set_aerolush_aircd_accepts_explicit_device_id(
    hass: HomeAssistant, monkeypatch: MonkeyPatch
) -> None:
    _, coordinator = await _setup(hass, monkeypatch)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_AEROLUSH_AIRCD,
        {"device_id": _AC_DEV_ID, "wdLv": 100},
        blocking=True,
    )

    coordinator.async_publish_shadow_update.assert_awaited_once_with(
        build_aircd_payload({"wdLv": 100}), device_id=_AC_DEV_ID
    )


async def test_set_aerolush_aircd_requires_at_least_one_field(
    hass: HomeAssistant, monkeypatch: MonkeyPatch
) -> None:
    await _setup(hass, monkeypatch)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_AEROLUSH_AIRCD, {}, blocking=True
        )


async def test_set_aerolush_aircd_service_registered_and_removed(
    hass: HomeAssistant, monkeypatch: MonkeyPatch
) -> None:
    entry, _ = await _setup(hass, monkeypatch)
    assert hass.services.has_service(DOMAIN, SERVICE_SET_AEROLUSH_AIRCD) is True

    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True))
    assert await async_unload_entry(hass, entry)
    assert hass.services.has_service(DOMAIN, SERVICE_SET_AEROLUSH_AIRCD) is False
