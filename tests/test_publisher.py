import pytest

import driver_venus.publisher as publisher_module
from driver_venus.config import MqttConfig
from driver_venus.publisher import HEALTH_TOPIC, INFO_TOPIC, Publisher

INFO = '{"driver": "venus", "version": "v1"}'


class FakeClient:
    """Records what the broker would receive, in order."""

    def __init__(self, *args, **kwargs) -> None:
        self.published: list[tuple[str, str | None, bool]] = []
        self.will: tuple[str, str, bool] | None = None

    def username_pw_set(self, *args) -> None: ...
    def reconnect_delay_set(self, **kwargs) -> None: ...
    def loop_stop(self) -> None: ...
    def disconnect(self) -> None: ...

    def will_set(self, topic, payload, qos, retain) -> None:
        self.will = (topic, payload, retain)

    def publish(self, topic, payload, qos, retain) -> None:
        self.published.append((topic, payload, retain))


@pytest.fixture
def publisher(monkeypatch: pytest.MonkeyPatch) -> Publisher:
    monkeypatch.setattr(publisher_module.mqtt, "Client", FakeClient)
    config = MqttConfig(host="localhost", port=1883, username=None, password=None)
    return Publisher(config, info=INFO)


def connect(publisher: Publisher) -> FakeClient:
    client = publisher._client
    publisher._on_connect(client, None, {}, 0)
    return client


def test_info_is_published_retained_immediately_before_online(publisher: Publisher) -> None:
    client = connect(publisher)
    assert client.published == [
        ("renewvan/venus/info", INFO, True),
        ("renewvan/venus/health", "online", True),
    ]


def test_info_is_published_again_on_every_reconnect(publisher: Publisher) -> None:
    client = connect(publisher)
    client.published.clear()
    connect(publisher)
    assert client.published == [(INFO_TOPIC, INFO, True), (HEALTH_TOPIC, "online", True)]


def test_identity_is_published_retained_and_replayed_on_every_reconnect(
    publisher: Publisher,
) -> None:
    client = connect(publisher)
    publisher.publish_identity("renewvan/battery/290/driver", "venus")
    publisher.publish_identity("renewvan/battery/290/name", "Van")
    assert client.published[-2:] == [
        ("renewvan/battery/290/driver", '"venus"', True),
        ("renewvan/battery/290/name", '"Van"', True),
    ]
    client.published.clear()
    connect(publisher)
    assert client.published == [
        (INFO_TOPIC, INFO, True),
        ("renewvan/battery/290/driver", '"venus"', True),
        ("renewvan/battery/290/name", '"Van"', True),
        (HEALTH_TOPIC, "online", True),
    ]


def test_cleared_identity_is_cleared_on_the_bus_and_not_replayed(publisher: Publisher) -> None:
    client = connect(publisher)
    publisher.publish_identity("renewvan/battery/290/name", "Van")
    publisher.publish_identity("renewvan/battery/290/name", None)
    assert client.published[-1] == ("renewvan/battery/290/name", None, True)
    client.published.clear()
    connect(publisher)
    assert client.published == [(INFO_TOPIC, INFO, True), (HEALTH_TOPIC, "online", True)]


def test_failed_connect_publishes_nothing(publisher: Publisher) -> None:
    client = publisher._client
    publisher._on_connect(client, None, {}, 5)
    assert client.published == []


def test_info_is_never_cleared_when_the_driver_goes_offline(publisher: Publisher) -> None:
    client = connect(publisher)
    client.published.clear()
    publisher.disconnect()
    assert client.published == [(HEALTH_TOPIC, "offline", True)]
    # the broker publishes the last will on an unclean death: offline on health only
    assert client.will == (HEALTH_TOPIC, "offline", True)


def test_main_publishes_the_stamped_version_in_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DRIVER_VERSION reaches the info published on connect, through main()."""
    import json

    import driver_venus.main as main_module

    class StopRun(Exception):
        pass

    class StubSubscriber:
        def __init__(self, *args, **kwargs) -> None: ...

        def run_forever(self) -> None:
            raise StopRun

    clients: list[FakeClient] = []

    class RecordingClient(FakeClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            clients.append(self)

        def connect(self, *args) -> None: ...
        def loop_start(self) -> None: ...

    monkeypatch.setenv("VENUS_MQTT_HOST", "venus.local")
    monkeypatch.setenv("VENUS_PORTAL_ID", "abc")
    monkeypatch.setattr(publisher_module.mqtt, "Client", RecordingClient)
    monkeypatch.setattr(main_module, "Subscriber", StubSubscriber)
    monkeypatch.setattr("sys.argv", ["driver-venus"])

    for env, expected in (("v4.5.6", "v4.5.6"), (None, "dev")):
        if env is None:
            monkeypatch.delenv("DRIVER_VERSION", raising=False)
        else:
            monkeypatch.setenv("DRIVER_VERSION", env)
        clients.clear()
        with pytest.raises(StopRun):
            main_module.main()
        client = clients[0]
        client.published.clear()  # main()'s finally already published offline
        # paho calls on_connect once the socket is up; do it by hand.
        client.on_connect(client, None, {}, 0)
        assert [(t, r) for t, _, r in client.published] == [
            ("renewvan/venus/info", True),
            ("renewvan/venus/health", True),
        ]
        assert json.loads(client.published[0][1])["version"] == expected
