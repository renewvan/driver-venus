"""Layered INI config: config.default.ini (shipped) + config.ini (local
override) + environment variables (highest precedence).

Same two-file pattern as every renewvan/driver-* repo (see
driver-tilt/driver_tilt/config.py): config.default.ini ships every key with a
safe default and is never edited at an install; config.ini is a gitignored,
install-local file that overrides only what differs.

Environment variables override both files. They are the contract with
`hub`'s `docker-compose.yml` `driver-venus:` service block, which sets them
from hub's `.env`. Two separate MQTT connections: the renewvan bus (publish)
and the Victron GX / Venus OS device's own broker (subscribe).

There is deliberately no instance -> id map: entity ids are the Venus
device instance numbers, discovered from the feed (see `mapping.py`).
"""

from __future__ import annotations

import configparser
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.default.ini"

# (section, key) -> environment variable that overrides it.
ENV_OVERRIDES: dict[tuple[str, str], str] = {
    ("mqtt", "host"): "MQTT_HOST",
    ("mqtt", "port"): "MQTT_PORT",
    ("mqtt", "username"): "MQTT_USERNAME",
    ("mqtt", "password"): "MQTT_PASSWORD",
    ("venus", "host"): "VENUS_MQTT_HOST",
    ("venus", "port"): "VENUS_MQTT_PORT",
    ("venus", "portal_id"): "VENUS_PORTAL_ID",
}


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


def load_config(
    default_path: Path = DEFAULT_CONFIG_PATH,
    local_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load config.default.ini, layer config.ini (if present), then env vars."""
    env = os.environ if env is None else env
    parser = configparser.ConfigParser()
    parser.read(default_path)
    if local_path is not None and local_path.exists():
        parser.read(local_path)
    else:
        logger.info("No local config override at %s; using defaults only", local_path)

    for section in ("mqtt", "venus"):
        if not parser.has_section(section):
            parser.add_section(section)
    for (section, key), var in ENV_OVERRIDES.items():
        # Empty counts as unset: compose passes `${VAR:-}` for unset values.
        if env.get(var):
            parser[section][key] = env[var]

    mqtt = parser["mqtt"]
    venus = parser["venus"]
    config = AppConfig(
        mqtt=MqttConfig(
            host=mqtt.get("host", "localhost").strip(),
            port=mqtt.getint("port", 1883),
            username=mqtt.get("username", "").strip() or None,
            password=mqtt.get("password", "") or None,
        ),
        venus=VenusConfig(
            host=venus.get("host", "").strip(),
            port=venus.getint("port", 1883),
            portal_id=venus.get("portal_id", "").strip(),
        ),
    )
    _validate(config)
    return config


def _validate(config: AppConfig) -> None:
    """Fail at startup on config that would otherwise misbehave at runtime."""
    if not config.mqtt.host:
        raise ValueError("[mqtt] host is empty (or set MQTT_HOST)")
    if not config.venus.host:
        raise ValueError("[venus] host is required (or set VENUS_MQTT_HOST)")
    if not config.venus.portal_id:
        raise ValueError("[venus] portal_id is required (or set VENUS_PORTAL_ID)")
