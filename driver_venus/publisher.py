"""Persistent MQTT connection to the renewvan bus with LWT and a
retained-topic publish helper. Same shape as the other renewvan/driver-*
publishers, plus clearing a retained topic when the source reading goes
invalid, and the retained Driver info published on every connect just before
`online`.
"""

from __future__ import annotations

import json
import logging
import threading

import paho.mqtt.client as mqtt

from driver_venus.config import MqttConfig

logger = logging.getLogger(__name__)

# 3 segments, not 4: liveness for the whole driver, so it cannot be mistaken
# for an entity keyed by a fake `health` id.
HEALTH_TOPIC = "renewvan/venus/health"
# Retained Driver info, same 3-segment shape; see hub schema/driver-info.schema.json.
INFO_TOPIC = "renewvan/venus/info"


class Publisher:
    def __init__(self, config: MqttConfig, info: str) -> None:
        self._config = config
        self._info = info
        # Retained identity topics (`driver`, `name`) of every discovered instance, replayed
        # on every (re)connect. A cleared topic is dropped.
        self._identity: dict[str, object] = {}
        self._identity_lock = threading.Lock()
        self._client = mqtt.Client(client_id="driver-venus", clean_session=False)
        if config.username:
            self._client.username_pw_set(config.username, config.password)
        self._client.will_set(HEALTH_TOPIC, payload="offline", qos=1, retain=True)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect

    def _on_connect(self, client, userdata, flags, rc):  # noqa: ANN001
        if rc == 0:
            logger.info(
                "Connected to renewvan-bus MQTT broker %s:%s", self._config.host, self._config.port
            )
            # Info first, then online: a consumer that sees online always finds info
            # retained. Never cleared on offline or by the will ("last seen vX").
            client.publish(INFO_TOPIC, payload=self._info, qos=1, retain=True)
            with self._identity_lock:
                identity = list(self._identity.items())
            for topic, payload in identity:
                self.publish(topic, payload)
            client.publish(HEALTH_TOPIC, payload="online", qos=1, retain=True)
        else:
            logger.error("Renewvan-bus MQTT connect failed with rc=%s", rc)

    def connect(self) -> None:
        self._client.connect(self._config.host, self._config.port)
        self._client.loop_start()

    def publish(self, topic: str, payload: object) -> None:
        """Publish a retained value. `None` clears the retained topic (an
        empty retained payload), so a reading that stopped being valid
        does not linger on the bus."""
        if payload is None:
            self._client.publish(topic, payload=None, qos=1, retain=True)
            return
        self._client.publish(topic, payload=json.dumps(payload), qos=1, retain=True)

    def publish_identity(self, topic: str, payload: object) -> None:
        """Publish a retained identity value (an entity instance's `driver` / `name`)
        and remember it so every reconnect publishes it again. `None` clears the
        topic and forgets it."""
        with self._identity_lock:
            if payload is None:
                self._identity.pop(topic, None)
            else:
                self._identity[topic] = payload
        self.publish(topic, payload)

    def disconnect(self) -> None:
        self._client.publish(HEALTH_TOPIC, payload="offline", qos=1, retain=True)
        self._client.loop_stop()
        self._client.disconnect()
