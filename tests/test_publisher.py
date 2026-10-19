import pytest

import node_venus.publisher as publisher_module
from node_venus.config import MqttConfig
from node_venus.publisher import HEALTH_TOPIC, INFO_TOPIC, Publisher

INFO = '{"node": "venus", "version": "v1"}'


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
    assert client.published == [(INFO_TOPIC, INFO, True), (HEALTH_TOPIC, "online", True)]


def test_info_topic_is_three_segments_under_the_node_key() -> None:
    assert INFO_TOPIC == "renewvan/venus/info"


def test_info_is_published_again_on_every_reconnect(publisher: Publisher) -> None:
    client = connect(publisher)
    client.published.clear()
    connect(publisher)
    assert client.published == [(INFO_TOPIC, INFO, True), (HEALTH_TOPIC, "online", True)]


def test_failed_connect_publishes_nothing(publisher: Publisher) -> None:
    client = publisher._client
    publisher._on_connect(client, None, {}, 5)
    assert client.published == []


def test_info_is_never_cleared_when_the_node_goes_offline(publisher: Publisher) -> None:
    client = connect(publisher)
    client.published.clear()
    publisher.disconnect()
    assert client.published == [(HEALTH_TOPIC, "offline", True)]
    # the broker publishes the last will on an unclean death: offline on health only
    assert client.will == (HEALTH_TOPIC, "offline", True)
