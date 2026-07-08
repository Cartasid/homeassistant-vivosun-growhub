"""Climate platform for the Vivosun GrowHub integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    AIRCD_FAN_QUIET,
    AIRCD_FAN_STANDARD,
    AIRCD_FUNC_COOL,
    AIRCD_FUNC_DRY,
    AIRCD_FUNC_FAN,
    AIRCD_FUNC_HEAT,
    DEFAULT_TEMP_UNIT,
    DOMAIN,
    MODE_AUTO,
    MODE_MANUAL,
    TEMP_SCALE_FACTOR,
)
from .coordinator import VivosunCoordinator
from .entity_helpers import build_device_info, is_entity_available, sensor_slice, shadow_slice
from .shadow import (
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
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .models import RuntimeData

_OPTIONS_TEMP_UNIT = "temp_unit"
_UNIT_FAHRENHEIT = "fahrenheit"
_HEAT_PRESETS = ("manual", "auto")
_TURN_ON_FEATURE = getattr(ClimateEntityFeature, "TURN_ON", ClimateEntityFeature(0))
_TURN_OFF_FEATURE = getattr(ClimateEntityFeature, "TURN_OFF", ClimateEntityFeature(0))
_EXPLICIT_TURN_FEATURES = _TURN_ON_FEATURE | _TURN_OFF_FEATURE

_AIRCD_FAN_QUIET = "quiet"
_AIRCD_FAN_STANDARD = "standard"
_AIRCD_FUNC_TO_HVAC_MODE: dict[int, HVACMode] = {
    AIRCD_FUNC_COOL: HVACMode.COOL,
    AIRCD_FUNC_HEAT: HVACMode.HEAT,
    AIRCD_FUNC_DRY: HVACMode.DRY,
    AIRCD_FUNC_FAN: HVACMode.FAN_ONLY,
}
_HVAC_MODE_TO_AIRCD_FUNC: dict[HVACMode, int] = {
    HVACMode.COOL: AIRCD_FUNC_COOL,
    HVACMode.HEAT: AIRCD_FUNC_HEAT,
    HVACMode.DRY: AIRCD_FUNC_DRY,
    HVACMode.FAN_ONLY: AIRCD_FUNC_FAN,
}
_HVAC_MODE_TO_ACTION: dict[HVACMode, HVACAction] = {
    HVACMode.COOL: HVACAction.COOLING,
    HVACMode.HEAT: HVACAction.HEATING,
    HVACMode.DRY: HVACAction.DRYING,
    HVACMode.FAN_ONLY: HVACAction.FAN,
}


def _runtime(hass: HomeAssistant, entry: ConfigEntry) -> RuntimeData:
    return cast("RuntimeData", hass.data[DOMAIN][entry.entry_id])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vivosun climate entities from a config entry."""
    coordinator = _runtime(hass, entry).coordinator
    if coordinator is None:
        return

    heaters = [d for d in coordinator.devices if d.device_type == "heater"]
    if heaters:
        async_add_entities(
            [VivosunHeaterClimateEntity(coordinator, entry, d.device_id) for d in heaters]
        )

    air_conditioners = [d for d in coordinator.devices if d.device_type == "air_conditioner"]
    if air_conditioners:
        async_add_entities(
            [VivosunAeroLushClimateEntity(coordinator, entry, d.device_id) for d in air_conditioners]
        )


class VivosunHeaterClimateEntity(CoordinatorEntity[VivosunCoordinator], ClimateEntity):  # type: ignore[misc]
    """Representation of a Vivosun AeroFlux heater."""

    _attr_has_entity_name = True
    _attr_name = "Heater"
    _attr_hvac_modes: ClassVar[list[HVACMode]] = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        _EXPLICIT_TURN_FEATURES
        | ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_preset_modes: ClassVar[list[str]] = list(_HEAT_PRESETS)
    _attr_min_temp = 0
    _attr_max_temp = 40
    _attr_target_temperature_step = 1
    _enable_turn_on_off_backwards_compatibility = ClimateEntityFeature(0) == _EXPLICIT_TURN_FEATURES

    def __init__(
        self,
        coordinator: VivosunCoordinator,
        entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize the heater climate entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._entry = entry
        self._attr_unique_id = f"vivosun_growhub_{device_id}_climate"

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit for this entity."""
        if self._temp_unit_config() == _UNIT_FAHRENHEIT:
            return str(UnitOfTemperature.FAHRENHEIT)
        return str(UnitOfTemperature.CELSIUS)

    @property
    def min_temp(self) -> float:
        """Return the configured minimum target temperature."""
        if self._temp_unit_config() == _UNIT_FAHRENHEIT:
            return 32.0
        return float(self._attr_min_temp)

    @property
    def max_temp(self) -> float:
        """Return the configured maximum target temperature."""
        if self._temp_unit_config() == _UNIT_FAHRENHEIT:
            return 104.0
        return float(self._attr_max_temp)

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        heat = self._heat_state()
        on = heat.get("on")
        if isinstance(on, bool) and on:
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action."""
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        heat = self._heat_state()
        state = heat.get("state")
        if isinstance(state, int) and state == 1:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        heat = self._heat_state()
        target = heat.get("target_temp")
        if isinstance(target, int):
            value = target / TEMP_SCALE_FACTOR
            if self._temp_unit_config() == _UNIT_FAHRENHEIT:
                return (value * 9 / 5) + 32
            return value
        return None

    @property
    def current_temperature(self) -> float | None:
        """Return current temperature from probe sensor."""
        sensors = sensor_slice(self.coordinator, self._device_id)
        raw = sensors.get("pTemp")
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int):
            value = raw / TEMP_SCALE_FACTOR
            if self._temp_unit_config() == _UNIT_FAHRENHEIT:
                return (value * 9 / 5) + 32
            return value
        return None

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        heat = self._heat_state()
        mode = heat.get("mode")
        if isinstance(mode, int):
            return "auto" if mode == MODE_AUTO else "manual"
        return None

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return is_entity_available(self.coordinator, self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this entity."""
        return build_device_info(self.coordinator, self._device_id)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return additional heater state attributes."""
        heat = self._heat_state()
        attrs: dict[str, object] = {}
        level = heat.get("level")
        if isinstance(level, int):
            attrs["level"] = level
        return attrs

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode (HEAT or OFF)."""
        on = hvac_mode == HVACMode.HEAT
        await self.coordinator.async_publish_shadow_update(
            build_heat_on_payload(on), device_id=self._device_id
        )

    async def async_turn_on(self) -> None:
        """Turn the heater on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn the heater off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: object) -> None:
        """Set the target temperature."""
        temperature = kwargs.get("temperature")
        if not isinstance(temperature, (int, float)):
            return
        # Convert from display unit back to Celsius for raw storage
        if self._temp_unit_config() == _UNIT_FAHRENHEIT:
            temperature = (temperature - 32) * 5 / 9
        target_raw = int(temperature * TEMP_SCALE_FACTOR)
        await self.coordinator.async_publish_shadow_update(
            build_heat_target_payload(target_raw), device_id=self._device_id
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode (manual or auto)."""
        if preset_mode == "auto":
            await self.coordinator.async_publish_shadow_update(
                build_heat_mode_payload(MODE_AUTO), device_id=self._device_id
            )
        elif preset_mode == "manual":
            await self.coordinator.async_publish_shadow_update(
                build_heat_mode_payload(MODE_MANUAL), device_id=self._device_id
            )

    def _heat_state(self) -> Mapping[str, object]:
        return shadow_slice(self.coordinator, self._device_id, "heat")

    def _temp_unit_config(self) -> str:
        configured_unit = self._entry.options.get(_OPTIONS_TEMP_UNIT, DEFAULT_TEMP_UNIT)
        if isinstance(configured_unit, str):
            return configured_unit
        return DEFAULT_TEMP_UNIT


class VivosunAeroLushClimateEntity(CoordinatorEntity[VivosunCoordinator], ClimateEntity):  # type: ignore[misc]
    """Representation of a Vivosun AeroLush C08 air conditioner."""

    _attr_has_entity_name = True
    _attr_name = "AeroLush C08"
    _attr_hvac_modes: ClassVar[list[HVACMode]] = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
    ]
    _attr_supported_features = (
        _EXPLICIT_TURN_FEATURES
        | ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TARGET_HUMIDITY
        | ClimateEntityFeature.FAN_MODE
    )
    _attr_fan_modes: ClassVar[list[str]] = [_AIRCD_FAN_QUIET, _AIRCD_FAN_STANDARD]
    _attr_min_temp = 10
    _attr_max_temp = 40
    _attr_target_temperature_step = 0.1
    _attr_min_humidity = 0
    _attr_max_humidity = 100
    _attr_target_humidity_step = 1
    _enable_turn_on_off_backwards_compatibility = ClimateEntityFeature(0) == _EXPLICIT_TURN_FEATURES

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return supported features for the current AeroLush function."""
        features = (
            _EXPLICIT_TURN_FEATURES
            | ClimateEntityFeature.TARGET_HUMIDITY
            | ClimateEntityFeature.FAN_MODE
        )
        if self.hvac_mode != HVACMode.DRY:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        return features

    def __init__(
        self,
        coordinator: VivosunCoordinator,
        entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize the AeroLush C08 climate entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._entry = entry
        self._attr_unique_id = f"vivosun_growhub_{device_id}_aerolush_c08_climate"

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit for this entity."""
        if self._temp_unit_config() == _UNIT_FAHRENHEIT:
            return str(UnitOfTemperature.FAHRENHEIT)
        return str(UnitOfTemperature.CELSIUS)

    @property
    def min_temp(self) -> float:
        """Return the configured minimum target temperature."""
        if self._temp_unit_config() == _UNIT_FAHRENHEIT:
            return (float(self._attr_min_temp) * 9 / 5) + 32
        return float(self._attr_min_temp)

    @property
    def max_temp(self) -> float:
        """Return the configured maximum target temperature."""
        if self._temp_unit_config() == _UNIT_FAHRENHEIT:
            return (float(self._attr_max_temp) * 9 / 5) + 32
        return float(self._attr_max_temp)

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current HVAC mode."""
        aircd = self._aircd_state()
        state = aircd.get("state")
        if not (isinstance(state, int) and state == 1):
            return HVACMode.OFF
        function = aircd.get("function")
        if isinstance(function, int):
            return _AIRCD_FUNC_TO_HVAC_MODE.get(function)
        return None

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action."""
        mode = self.hvac_mode
        if mode == HVACMode.OFF:
            return HVACAction.OFF
        if mode is None:
            return HVACAction.IDLE
        return _HVAC_MODE_TO_ACTION.get(mode, HVACAction.IDLE)

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self.hvac_mode == HVACMode.DRY:
            return None
        aircd = self._aircd_state()
        target = aircd.get("target_temp")
        if isinstance(target, int):
            value = target / TEMP_SCALE_FACTOR
            if self._temp_unit_config() == _UNIT_FAHRENHEIT:
                return (value * 9 / 5) + 32
            return value
        return None

    @property
    def target_humidity(self) -> float | None:
        """Return the target humidity."""
        aircd = self._aircd_state()
        target = aircd.get("target_humidity")
        if isinstance(target, int):
            return target / 100
        return None

    @property
    def current_temperature(self) -> float | None:
        """Return current temperature from the first available probe sensor."""
        raw = self._raw_sensor_value(("pTemp", "inTemp", "bTemp"))
        if raw is None:
            return None
        value = raw / TEMP_SCALE_FACTOR
        if self._temp_unit_config() == _UNIT_FAHRENHEIT:
            return (value * 9 / 5) + 32
        return value

    @property
    def current_humidity(self) -> float | None:
        """Return current humidity from the first available probe sensor."""
        raw = self._raw_sensor_value(("pHumi", "inHumi", "bHumi"))
        if raw is None:
            return None
        return raw / 100

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan mode."""
        aircd = self._aircd_state()
        level = aircd.get("fan_level")
        if level == AIRCD_FAN_QUIET:
            return _AIRCD_FAN_QUIET
        if level == AIRCD_FAN_STANDARD:
            return _AIRCD_FAN_STANDARD
        return None

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return is_entity_available(self.coordinator, self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this entity."""
        return build_device_info(self.coordinator, self._device_id)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return raw AeroLush state values for diagnostics."""
        aircd = self._aircd_state()
        attrs: dict[str, object] = {}
        for attr_name, state_key in (
            ("raw_state", "state"),
            ("raw_function", "function"),
            ("raw_fan_level", "fan_level"),
            ("target_vpd_raw", "target_vpd"),
            ("target_min_temp_raw", "target_min_temp"),
            ("in_plan", "in_plan"),
            ("pause", "pause"),
        ):
            value = aircd.get(state_key)
            if value is not None:
                attrs[attr_name] = value
        return attrs

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            payload = build_aircd_state_payload(False)
        else:
            function = _HVAC_MODE_TO_AIRCD_FUNC.get(hvac_mode)
            if function is None:
                raise ValueError(f"Unsupported hvac mode: {hvac_mode}")
            payload = build_aircd_payload({"state": 1, "func": function})
        await self.coordinator.async_publish_shadow_update(payload, device_id=self._device_id)

    async def async_turn_on(self) -> None:
        """Turn the air conditioner on without forcing the compressor on."""
        function = self._aircd_state().get("function")
        if isinstance(function, int) and function in _AIRCD_FUNC_TO_HVAC_MODE:
            payload = build_aircd_state_payload(True)
        else:
            # No known function: default to fan-only so the compressor stays idle.
            payload = build_aircd_payload({"state": 1, "func": AIRCD_FUNC_FAN})
        await self.coordinator.async_publish_shadow_update(payload, device_id=self._device_id)

    async def async_turn_off(self) -> None:
        """Turn the air conditioner off."""
        await self.coordinator.async_publish_shadow_update(
            build_aircd_state_payload(False), device_id=self._device_id
        )

    async def async_set_temperature(self, **kwargs: object) -> None:
        """Set the target temperature."""
        if self.hvac_mode == HVACMode.DRY:
            return
        temperature = kwargs.get("temperature")
        if not isinstance(temperature, (int, float)):
            return
        # Convert from display unit back to Celsius for raw storage.
        if self._temp_unit_config() == _UNIT_FAHRENHEIT:
            temperature = (temperature - 32) * 5 / 9
        target_raw = round(temperature * TEMP_SCALE_FACTOR)
        await self.coordinator.async_publish_shadow_update(
            build_aircd_target_temp_payload(target_raw), device_id=self._device_id
        )

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the target humidity."""
        target_raw = humidity * 100
        await self.coordinator.async_publish_shadow_update(
            build_aircd_target_humidity_payload(target_raw), device_id=self._device_id
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan mode (quiet or standard)."""
        if fan_mode == _AIRCD_FAN_QUIET:
            level = AIRCD_FAN_QUIET
        elif fan_mode == _AIRCD_FAN_STANDARD:
            level = AIRCD_FAN_STANDARD
        else:
            raise ValueError(f"Unsupported fan mode: {fan_mode}")
        await self.coordinator.async_publish_shadow_update(
            build_aircd_fan_level_payload(level), device_id=self._device_id
        )

    def _aircd_state(self) -> Mapping[str, object]:
        return shadow_slice(self.coordinator, self._device_id, "aircd")

    def _temp_unit_config(self) -> str:
        configured_unit = self._entry.options.get(_OPTIONS_TEMP_UNIT, DEFAULT_TEMP_UNIT)
        if isinstance(configured_unit, str):
            return configured_unit
        return DEFAULT_TEMP_UNIT

    def _raw_sensor_value(self, keys: tuple[str, ...]) -> int | None:
        sensors = sensor_slice(self.coordinator, self._device_id)
        for key in keys:
            raw = sensors.get(key)
            if isinstance(raw, bool):
                continue
            if isinstance(raw, int):
                return raw
        return None
