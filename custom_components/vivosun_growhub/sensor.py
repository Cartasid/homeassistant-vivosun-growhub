"""Sensor platform for the Vivosun GrowHub integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_TEMP_UNIT, DOMAIN, TEMP_SCALE_FACTOR, WATER_LEVEL_SCALE_FACTOR
from .coordinator import VivosunCoordinator
from .entity_helpers import build_device_info, is_entity_available, plan_slice, plan_stage_cache, sensor_slice

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .models import RuntimeData

_OPTIONS_TEMP_UNIT = "temp_unit"
_UNIT_CELSIUS = "celsius"
_UNIT_FAHRENHEIT = "fahrenheit"


@dataclass(frozen=True, kw_only=True)
class VivosunSensorDescription(SensorEntityDescription):  # type: ignore[misc]
    """Description for a Vivosun channel sensor entity."""

    channel_key: str
    quantity: str
    state_class: SensorStateClass = SensorStateClass.MEASUREMENT


_ALL_SENSOR_DESCRIPTIONS: tuple[VivosunSensorDescription, ...] = (
    VivosunSensorDescription(
        key="inside_temperature",
        name="Inside Temperature",
        channel_key="inTemp",
        quantity="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    VivosunSensorDescription(
        key="inside_humidity",
        name="Inside Humidity",
        channel_key="inHumi",
        quantity="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    VivosunSensorDescription(
        key="inside_vpd",
        name="Inside VPD",
        channel_key="inVpd",
        quantity="vpd",
        icon="mdi:leaf",
        native_unit_of_measurement="kPa",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    VivosunSensorDescription(
        key="outside_temperature",
        name="Outside Temperature",
        channel_key="outTemp",
        quantity="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    VivosunSensorDescription(
        key="outside_humidity",
        name="Outside Humidity",
        channel_key="outHumi",
        quantity="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    VivosunSensorDescription(
        key="outside_vpd",
        name="Outside VPD",
        channel_key="outVpd",
        quantity="vpd",
        icon="mdi:leaf",
        native_unit_of_measurement="kPa",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    VivosunSensorDescription(
        key="probe_temperature",
        name="Probe Temperature",
        channel_key="pTemp",
        quantity="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    VivosunSensorDescription(
        key="probe_humidity",
        name="Probe Humidity",
        channel_key="pHumi",
        quantity="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    VivosunSensorDescription(
        key="probe_vpd",
        name="Probe VPD",
        channel_key="pVpd",
        quantity="vpd",
        icon="mdi:leaf",
        native_unit_of_measurement="kPa",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    VivosunSensorDescription(
        key="water_level",
        name="Water Level",
        channel_key="waterLv",
        quantity="water_level",
        icon="mdi:waves-arrow-up",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    VivosunSensorDescription(
        key="core_temperature",
        name="Core Temperature",
        channel_key="coreTemp",
        quantity="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    VivosunSensorDescription(
        key="wifi_signal",
        name="WiFi Signal",
        channel_key="rssi",
        quantity="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
)

_DEVICE_TYPE_SENSORS: dict[str, frozenset[str]] = {
    "controller": frozenset({"inTemp", "inHumi", "inVpd", "outTemp", "outHumi", "outVpd", "coreTemp", "rssi"}),
    "humidifier": frozenset({"pTemp", "pHumi", "pVpd", "waterLv", "coreTemp"}),
    "heater": frozenset({"pTemp", "pHumi", "pVpd"}),
}


def _runtime(hass: HomeAssistant, entry: ConfigEntry) -> RuntimeData:
    return cast("RuntimeData", hass.data[DOMAIN][entry.entry_id])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vivosun sensor entities from a config entry."""
    coordinator = _runtime(hass, entry).coordinator
    if coordinator is None:
        return

    entities: list[SensorEntity] = []
    for device in coordinator.devices:
        allowed_keys = _DEVICE_TYPE_SENSORS.get(device.device_type, frozenset())
        for description in _ALL_SENSOR_DESCRIPTIONS:
            if description.channel_key in allowed_keys:
                entities.append(
                    VivosunChannelSensorEntity(coordinator, entry, description, device.device_id)
                )
        if device.device_type == "controller":
            entities.append(VivosunPlanStageSensor(coordinator, entry, device.device_id))
            entities.append(VivosunPlanLightSensor(coordinator, entry, device.device_id))
            entities.append(VivosunPlanFanSensor(coordinator, entry, device.device_id, fan_key="cfan", name="Circulator Fan"))
            entities.append(VivosunPlanFanSensor(coordinator, entry, device.device_id, fan_key="dfan", name="Duct Fan"))
    async_add_entities(entities)


class VivosunChannelSensorEntity(CoordinatorEntity[VivosunCoordinator], SensorEntity):  # type: ignore[misc]
    """Representation of a channel telemetry sensor."""

    entity_description: VivosunSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VivosunCoordinator,
        entry: ConfigEntry,
        description: VivosunSensorDescription,
        device_id: str,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._device_id = device_id
        self._attr_name = description.name
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_unique_id = f"vivosun_growhub_{device_id}_{description.channel_key}"

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return is_entity_available(self.coordinator, self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this entity."""
        return build_device_info(self.coordinator, self._device_id)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return native measurement unit."""
        if self.entity_description.quantity == "temperature":
            if self._temp_unit() == _UNIT_FAHRENHEIT:
                return str(UnitOfTemperature.FAHRENHEIT)
            return str(UnitOfTemperature.CELSIUS)
        return cast("str | None", self.entity_description.native_unit_of_measurement)

    @property
    def native_value(self) -> float | None:
        """Return current sensor value from the latest point-log sample."""
        raw_value = self._raw_channel_value()
        if raw_value is None:
            return None

        if self.entity_description.quantity == "signal_strength":
            return float(raw_value)
        if self.entity_description.quantity == "water_level":
            return raw_value / WATER_LEVEL_SCALE_FACTOR
        value = raw_value / TEMP_SCALE_FACTOR
        if self.entity_description.quantity == "temperature" and self._temp_unit() == _UNIT_FAHRENHEIT:
            return (value * 9 / 5) + 32
        return value

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return extra attributes for non-standard quantities."""
        if self.entity_description.quantity == "vpd":
            return {"quantity": "vpd"}
        return None

    def _raw_channel_value(self) -> int | None:
        sensors = sensor_slice(self.coordinator, self._device_id)
        value = sensors.get(self.entity_description.channel_key)
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    def _temp_unit(self) -> str:
        configured_unit = self._entry.options.get(_OPTIONS_TEMP_UNIT, DEFAULT_TEMP_UNIT)
        if configured_unit == _UNIT_FAHRENHEIT:
            return _UNIT_FAHRENHEIT
        return _UNIT_CELSIUS


def _get_active_stage_info(coordinator: VivosunCoordinator, device_id: str) -> tuple[str | None, dict[str, object]]:
    """Return (stage_name, stage_content) for the active plan stage, or (None, {})."""
    plan = plan_slice(coordinator, device_id)
    active_key = plan.get("active_stage")
    if not active_key:
        return None, {}
    stages = plan.get("stages")
    if not isinstance(stages, dict):
        return None, {}
    stage_entry = stages.get(active_key)
    if not isinstance(stage_entry, dict):
        return None, {}
    stage_id = stage_entry.get("stage_id", "")
    if not stage_id:
        return None, {}
    cache = plan_stage_cache(coordinator)
    info = cache.get(stage_id)
    if info is None:
        return None, {}
    return getattr(info, "stage_name", None), getattr(info, "content", {})


def _seconds_from_midnight() -> int:
    """Return seconds elapsed since midnight UTC."""
    now = datetime.now(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((now - midnight).total_seconds())


def _format_time(seconds: int) -> str:
    """Format seconds-from-midnight as HH:MM."""
    h, m = divmod(seconds // 60, 60)
    return f"{h:02d}:{m:02d}"


def _compute_light_schedule(content: dict[str, object]) -> dict[str, Any]:
    """Compute light schedule info from plan stage content."""
    light = content.get("light")
    if not isinstance(light, dict):
        return {}
    slots = light.get("slot")
    if not isinstance(slots, list) or not slots:
        return {}

    on_slots = [s for s in slots if isinstance(s, dict) and s.get("level", 0) > 0]
    off_slots = [s for s in slots if isinstance(s, dict) and s.get("level", 0) == 0]

    if not on_slots:
        return {"state": "off", "level": 0, "on_hours": 0}

    first_on = on_slots[0]
    on_time = first_on.get("time", 0)
    level = first_on.get("level", 0)
    spectrum = light.get("spec", 0)

    # Calculate on duration from slots
    if len(slots) >= 2:
        times = sorted(s.get("time", 0) for s in slots if isinstance(s, dict))
        on_times = sorted(s.get("time", 0) for s in on_slots)
        off_times = sorted(s.get("time", 0) for s in off_slots if s.get("time", 0) > 0)

        if off_times:
            off_time = off_times[0] if off_times[0] > on_times[0] else 86400
            on_duration = off_time - on_times[0]
        else:
            on_duration = 86400
    else:
        on_duration = 86400

    on_hours = round(on_duration / 3600, 1)

    # Calculate time remaining
    now_secs = _seconds_from_midnight()
    if on_times and off_times and off_times[0] > on_times[0]:
        is_on = on_times[0] <= now_secs < off_times[0]
        if is_on:
            remaining = off_times[0] - now_secs
        else:
            if now_secs < on_times[0]:
                remaining = on_times[0] - now_secs
            else:
                remaining = (86400 - now_secs) + on_times[0]
            remaining = -remaining  # Negative = time until light turns on
    else:
        is_on = True
        remaining = 0

    remaining_h = abs(remaining) / 3600

    return {
        "state": "on" if is_on else "off",
        "level": level,
        "spectrum": spectrum,
        "on_hours": on_hours,
        "on_time": _format_time(on_times[0]) if on_times else "00:00",
        "off_time": _format_time(off_times[0]) if off_times else "00:00",
        "remaining_hours": round(remaining_h, 1),
        "remaining_label": f"{round(remaining_h, 1)}h until {'off' if is_on else 'on'}",
    }


def _compute_fan_schedule(content: dict[str, object], fan_key: str) -> dict[str, Any]:
    """Compute fan schedule info from plan stage content."""
    fan = content.get(fan_key)
    if not isinstance(fan, dict):
        return {}
    slots = fan.get("slot")
    if not isinstance(slots, list) or not slots:
        return {}

    slot = slots[0]
    if not isinstance(slot, dict):
        return {}

    mode = slot.get("mode", 0)
    if mode == 1:
        lv_on = slot.get("lvOn", slot.get("level", 0))
        lv_off = slot.get("lvOff", 0)
        on_dur = slot.get("onDur", 0)
        off_dur = slot.get("offDur", 0)
        on_min = round(on_dur / 60)
        off_min = round(off_dur / 60)
        return {
            "mode": "cycle",
            "level_on": lv_on,
            "level_off": lv_off,
            "on_minutes": on_min,
            "off_minutes": off_min,
            "cycle": f"{on_min}m on / {off_min}m off",
        }
    else:
        level = slot.get("level", 0)
        return {
            "mode": "manual",
            "level": level,
        }


class VivosunPlanStageSensor(CoordinatorEntity[VivosunCoordinator], SensorEntity):  # type: ignore[misc]
    """Sensor showing the active grow plan stage name."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator: VivosunCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._attr_name = "Grow Plan Stage"
        self._attr_unique_id = f"vivosun_growhub_{device_id}_plan_stage"

    @property
    def available(self) -> bool:
        return is_entity_available(self.coordinator, self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        return build_device_info(self.coordinator, self._device_id)

    @property
    def native_value(self) -> str | None:
        name, _ = _get_active_stage_info(self.coordinator, self._device_id)
        return name

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        plan = plan_slice(self.coordinator, self._device_id)
        active_key = plan.get("active_stage")
        stages = plan.get("stages")
        attrs: dict[str, Any] = {}
        if active_key:
            attrs["active_stage_key"] = active_key
        if isinstance(stages, dict):
            for key, entry in stages.items():
                if isinstance(entry, dict) and entry.get("start_time", 0) > 0:
                    attrs[f"{key}_started"] = datetime.fromtimestamp(
                        entry["start_time"], tz=UTC
                    ).isoformat()
        return attrs if attrs else None


class VivosunPlanLightSensor(CoordinatorEntity[VivosunCoordinator], SensorEntity):  # type: ignore[misc]
    """Sensor showing light schedule from the active plan stage."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:lightbulb-on-outline"

    def __init__(self, coordinator: VivosunCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._attr_name = "Plan Light Schedule"
        self._attr_unique_id = f"vivosun_growhub_{device_id}_plan_light"

    @property
    def available(self) -> bool:
        return is_entity_available(self.coordinator, self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        return build_device_info(self.coordinator, self._device_id)

    @property
    def native_value(self) -> str | None:
        _, content = _get_active_stage_info(self.coordinator, self._device_id)
        if not content:
            return None
        info = _compute_light_schedule(content)
        if not info:
            return None
        return info.get("remaining_label")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        _, content = _get_active_stage_info(self.coordinator, self._device_id)
        if not content:
            return None
        info = _compute_light_schedule(content)
        if not info:
            return None
        return {
            "state": info.get("state"),
            "level": info.get("level"),
            "spectrum": info.get("spectrum"),
            "on_hours": info.get("on_hours"),
            "on_time": info.get("on_time"),
            "off_time": info.get("off_time"),
            "remaining_hours": info.get("remaining_hours"),
        }


class VivosunPlanFanSensor(CoordinatorEntity[VivosunCoordinator], SensorEntity):  # type: ignore[misc]
    """Sensor showing fan schedule from the active plan stage."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VivosunCoordinator,
        entry: ConfigEntry,
        device_id: str,
        *,
        fan_key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._fan_key = fan_key
        self._attr_name = f"Plan {name} Schedule"
        self._attr_unique_id = f"vivosun_growhub_{device_id}_plan_{fan_key}"
        self._attr_icon = "mdi:fan"

    @property
    def available(self) -> bool:
        return is_entity_available(self.coordinator, self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        return build_device_info(self.coordinator, self._device_id)

    @property
    def native_value(self) -> str | None:
        _, content = _get_active_stage_info(self.coordinator, self._device_id)
        if not content:
            return None
        info = _compute_fan_schedule(content, self._fan_key)
        if not info:
            return None
        mode = info.get("mode", "off")
        if mode == "cycle":
            return info.get("cycle")
        level = info.get("level", 0)
        return f"{level}%" if level > 0 else "Off"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        _, content = _get_active_stage_info(self.coordinator, self._device_id)
        if not content:
            return None
        info = _compute_fan_schedule(content, self._fan_key)
        return info if info else None
