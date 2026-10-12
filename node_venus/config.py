"""Config sourced from environment variables — the contract between this
repo and `hub`'s `docker-compose.yml` `node-venus:` service block. Two
separate MQTT connections: the renewvan bus (publish) and the Victron GX /
Venus OS device's own broker (subscribe).

There is deliberately no instance -> id map: entity ids are the Venus
device instance numbers, discovered from the feed (see `mapping.py`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    username: str | None
    password: str | None


@dataclass(frozen=True)
class VenusConfig:
    host: str
    port: int
    portal_id: str


@dataclass(frozen=True)
class AppConfig:
    mqtt: MqttConfig
    venus: VenusConfig


def load_config() -> AppConfig:
    return AppConfig(
        mqtt=MqttConfig(
            host=os.environ.get("MQTT_HOST", "mosquitto"),
            port=int(os.environ.get("MQTT_PORT", "1883")),
            username=os.environ.get("MQTT_USERNAME") or None,
            password=os.environ.get("MQTT_PASSWORD") or None,
        ),
        venus=VenusConfig(
            host=os.environ["VENUS_MQTT_HOST"],
            port=int(os.environ.get("VENUS_MQTT_PORT", "1883")),
            portal_id=os.environ["VENUS_PORTAL_ID"],
        ),
    )
