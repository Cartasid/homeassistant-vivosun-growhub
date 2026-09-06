"""Regression tests for support-capture probe subscriptions."""

from __future__ import annotations

from typing import cast

import pytest

from custom_components.vivosun_growhub.coordinator import VivosunCoordinator
from custom_components.vivosun_growhub.models import DeviceInfo
from custom_components.vivosun_growhub.mqtt_client import MQTTConnectionError
from custom_components.vivosun_growhub.support_capture import SupportCaptureManager


class _ProbeStub:
    def __init__(self, *, fail_topic: str | None = None) -> None:
        self.connected = True
        self.fail_topic = fail_topic
        self.subscribed: list[str] = []
        self.disconnect_calls = 0

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def subscribe(self, topics: list[tuple[str, int]]) -> None:
        assert len(topics) == 1
        topic, _qos = topics[0]
        self.subscribed.append(topic)
        if topic == self.fail_topic:
            self.connected = False
            raise MQTTConnectionError("MQTT client disconnected")

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False


def _coordinator() -> VivosunCoordinator:
    coordinator = object.__new__(VivosunCoordinator)
    coordinator._devices = [
        DeviceInfo(
            device_id="device-1",
            client_id="thing-1",
            topic_prefix="topic/1",
            name="AeroLush C08",
            online=True,
            scene_id=1,
            device_type="air_conditioner",
        ),
        DeviceInfo(
            device_id="device-2",
            client_id="thing-2",
            topic_prefix="topic/2",
            name="Device B",
            online=True,
            scene_id=2,
            device_type="humidifier",
        ),
    ]
    coordinator._support_capture = SupportCaptureManager()
    coordinator._support_capture_probe_client = None
    return coordinator


def test_support_capture_probe_uses_safe_prefix_first_topics() -> None:
    coordinator = _coordinator()

    topics = coordinator._support_capture_topic_names()

    assert topics == [
        "topic/1/#",
        "topic/2/#",
        "$aws/things/thing-1/shadow/get/rejected",
        "$aws/things/thing-1/shadow/update/rejected",
        "$aws/things/thing-2/shadow/get/rejected",
        "$aws/things/thing-2/shadow/update/rejected",
    ]
    assert not any("/shadow/name/" in topic for topic in topics)


@pytest.mark.asyncio
async def test_support_capture_classifies_probe_disconnect_without_losing_reason() -> None:
    coordinator = _coordinator()
    topics = coordinator._support_capture_topic_names()
    coordinator._support_capture.start(
        max_events=100,
        devices=[],
        subscription_topics=topics,
    )
    probe = _ProbeStub(fail_topic="topic/1/#")
    coordinator._support_capture_probe_client = cast("object", probe)

    await coordinator._async_subscribe_support_capture_topics()

    snapshot = coordinator._support_capture.snapshot()
    results = {
        cast("str", result["topic"]): result
        for result in cast("list[dict[str, object]]", snapshot["subscription_results"])
    }

    assert results["topic/1/#"]["status"] == "connection_closed"
    assert results["topic/1/#"]["reason"] == "mqtt_disconnected"
    assert results["topic/2/#"]["status"] == "deferred"
    assert coordinator._support_capture_probe_client is None
    assert probe.disconnect_calls == 1
