"""The Venus -> bus message path through `Subscriber`, against a recording
publisher: which topics reach the bus, and which of them are retained identity.
"""

import json
from types import SimpleNamespace

import pytest

import driver_venus.subscriber as subscriber_module
from driver_venus.config import AppConfig, MqttConfig, VenusConfig
from driver_venus.subscriber import Subscriber
from tests.fixtures import victron as fx

PORTAL = "PORTAL"


class FakeMqttClient:
    def __init__(self, *args, **kwargs) -> None: ...
    def reconnect_delay_set(self, **kwargs) -> None: ...


class RecordingPublisher:
    def __init__(self) -> None:
        self.values: list[tuple[str, object]] = []
        self.identity: list[tuple[str, object]] = []

    def publish(self, topic: str, payload: object) -> None:
        self.values.append((topic, payload))

    def publish_identity(self, topic: str, payload: object) -> None:
        self.identity.append((topic, payload))


@pytest.fixture
def publisher() -> RecordingPublisher:
    return RecordingPublisher()


@pytest.fixture
def subscriber(monkeypatch: pytest.MonkeyPatch, publisher: RecordingPublisher) -> Subscriber:
    monkeypatch.setattr(subscriber_module.mqtt, "Client", FakeMqttClient)
    config = AppConfig(
        mqtt=MqttConfig(host="localhost", port=1883, username=None, password=None),
        venus=VenusConfig(host="venus.local", port=1883, portal_id=PORTAL),
    )
    return Subscriber(config, publisher)


def send(subscriber: Subscriber, topic: str, payload: object) -> None:
    msg = SimpleNamespace(topic=topic, payload=json.dumps(payload).encode())
    subscriber._on_message(None, None, msg)


def test_battery_instance_names_its_driver_once(
    subscriber: Subscriber, publisher: RecordingPublisher
) -> None:
    topic = f"N/{PORTAL}/system/0/Batteries"
    send(subscriber, topic, fx.BATTERIES_TWO_BANKS)
    send(subscriber, topic, fx.BATTERIES_TWO_BANKS)
    assert publisher.identity == [
        ("renewvan/battery/290/driver", "venus"),
        ("renewvan/battery/512/driver", "venus"),
    ]
    assert ("renewvan/battery/290/soc_pct", 80.0) in publisher.values
    assert not any(t.endswith(("/driver", "/name")) for t, _ in publisher.values)


def test_solar_and_charger_instances_name_their_driver(
    subscriber: Subscriber, publisher: RecordingPublisher
) -> None:
    send(subscriber, f"N/{PORTAL}/solarcharger/291/Yield/Power", fx.SOLAR_YIELD_POWER)
    send(subscriber, f"N/{PORTAL}/alternator/277/Dc/0/Voltage", fx.ALTERNATOR_VOLTAGE)
    assert publisher.identity == [
        ("renewvan/solar/291/driver", "venus"),
        ("renewvan/charger/277/driver", "venus"),
    ]


def test_custom_name_is_published_as_the_instance_name(
    subscriber: Subscriber, publisher: RecordingPublisher
) -> None:
    send(subscriber, f"N/{PORTAL}/battery/290/ProductName", {"value": "SmartShunt"})
    send(subscriber, f"N/{PORTAL}/battery/290/CustomName", {"value": "Van"})
    assert publisher.identity == [
        ("renewvan/battery/290/driver", "venus"),
        ("renewvan/battery/290/name", "SmartShunt"),
        ("renewvan/battery/290/name", "Van"),
    ]
    assert publisher.values == []


def test_name_is_cleared_when_the_label_goes_null(
    subscriber: Subscriber, publisher: RecordingPublisher
) -> None:
    send(subscriber, f"N/{PORTAL}/solarcharger/291/CustomName", {"value": "Roof"})
    publisher.identity.clear()
    send(subscriber, f"N/{PORTAL}/solarcharger/291/CustomName", {"value": None})
    assert publisher.identity == [("renewvan/solar/291/name", None)]


def test_instance_without_a_label_gets_no_name(
    subscriber: Subscriber, publisher: RecordingPublisher
) -> None:
    send(subscriber, f"N/{PORTAL}/charger/289/Dc/0/Voltage", {"value": 13.2})
    assert publisher.identity == [("renewvan/charger/289/driver", "venus")]


def test_battery_fuel_gauge_reaches_the_bus(
    subscriber: Subscriber, publisher: RecordingPublisher
) -> None:
    send(subscriber, f"N/{PORTAL}/battery/290/Capacity", fx.CAPACITY)
    send(subscriber, f"N/{PORTAL}/battery/290/ConsumedAmphours", fx.CONSUMED_AMPHOURS)
    assert publisher.values == [
        ("renewvan/battery/290/capacity_ah", 314.0),
        ("renewvan/battery/290/remaining_ah", 289.2),
    ]
    assert publisher.identity == [("renewvan/battery/290/driver", "venus")]


def test_history_flush_does_not_name_the_driver_again(
    subscriber: Subscriber, publisher: RecordingPublisher
) -> None:
    send(subscriber, f"N/{PORTAL}/solarcharger/291/History/Overall/DaysAvailable", {"value": 1})
    send(subscriber, f"N/{PORTAL}/solarcharger/291/History/Daily/0/Yield", {"value": 0.21})
    subscriber._history_timer.cancel()
    publisher.identity.clear()
    publisher.values.clear()
    subscriber._flush_history()
    assert publisher.values == [("renewvan/solar/291/yield_history_wh", [210.0])]
    assert publisher.identity == []  # already named by yield_today_wh
