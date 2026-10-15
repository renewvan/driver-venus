"""Persistent MQTT subscription against the Victron Venus OS device's own
broker — a separate connection from the renewvan-bus Publisher.

Venus OS stops publishing a path once its last subscriber disconnects, and
only re-sends a value when it changes. So the subscription is held open for
the life of the process, and a `R/<portal>/keepalive` is published on
connect and periodically afterwards to make Venus (re)publish current
values — otherwise a slow-changing value (a full battery's SoC) would not
appear until it next moved.

Thin I/O adapter around paho-mqtt; not unit-tested (see mapping.py for the
tested seam).
"""

from __future__ import annotations

import json
import logging
import threading
import time

import paho.mqtt.client as mqtt

from node_venus.config import AppConfig
from node_venus.mapping import (
    SolarYieldHistory,
    map_batteries,
    map_charge_state,
    map_service_message,
    split_service_topic,
)
from node_venus.publisher import Publisher

logger = logging.getLogger(__name__)

KEEPALIVE_INTERVAL_S = 30
# Venus sends a controller's day slots as a burst of one-per-slot messages.
# The history array is published once no history message has arrived for
# this long, so a consumer never sees a half-filled or half-shifted array.
HISTORY_QUIET_PERIOD_S = 2.0


class Subscriber:
    def __init__(self, config: AppConfig, publisher: Publisher) -> None:
        self._config = config
        self._publisher = publisher
        portal = config.venus.portal_id
        self._batteries_topic = f"N/{portal}/system/0/Batteries"
        self._system_state_topic = f"N/{portal}/system/0/SystemState/State"
        self._keepalive_topic = f"R/{portal}/keepalive"
        # Battery ids seen so far: the system-wide charge state is fanned
        # out to exactly these.
        self._battery_ids: set[str] = set()
        # Folds the per-day-slot Venus messages into one history array.
        self._solar_history = SolarYieldHistory()
        self._history_lock = threading.Lock()
        self._history_timer: threading.Timer | None = None

        self._client = mqtt.Client(client_id="node-venus-source", clean_session=False)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):  # noqa: ANN001
        if rc == 0:
            logger.info(
                "Connected to Venus broker %s:%s",
                self._config.venus.host,
                self._config.venus.port,
            )
            client.subscribe(f"N/{self._config.venus.portal_id}/#", qos=1)
            client.publish(self._keepalive_topic, payload="")
        else:
            logger.error("Venus broker connect failed with rc=%s", rc)

    def _on_message(self, client, userdata, msg):  # noqa: ANN001
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Malformed Venus payload on topic=%s", msg.topic)
            return
        if not isinstance(payload, dict):
            return

        if msg.topic == self._batteries_topic:
            pairs = map_batteries(payload)
            for topic, _ in pairs:
                # renewvan/battery/<id>/<prop>
                self._battery_ids.add(topic.split("/")[2])
        elif msg.topic == self._system_state_topic:
            pairs = map_charge_state(payload, sorted(self._battery_ids))
        else:
            parsed = split_service_topic(msg.topic, self._config.venus.portal_id)
            if parsed is None:
                return
            pairs = map_service_message(*parsed, payload)
            with self._history_lock:
                if self._solar_history.handle(*parsed, payload):
                    self._schedule_history_flush()

        for topic, value in pairs:
            self._publisher.publish(topic, value)

    def _schedule_history_flush(self) -> None:
        """(Re)start the quiet-period timer. Caller holds `_history_lock`."""
        if self._history_timer is not None:
            self._history_timer.cancel()
        self._history_timer = threading.Timer(HISTORY_QUIET_PERIOD_S, self._flush_history)
        self._history_timer.daemon = True
        self._history_timer.start()

    def _flush_history(self) -> None:
        with self._history_lock:
            pairs = self._solar_history.flush()
        for topic, value in pairs:
            self._publisher.publish(topic, value)

    def run_forever(self) -> None:
        self._client.connect(self._config.venus.host, self._config.venus.port)
        self._client.loop_start()
        try:
            while True:
                time.sleep(KEEPALIVE_INTERVAL_S)
                self._client.publish(self._keepalive_topic, payload="")
        finally:
            self._client.loop_stop()
