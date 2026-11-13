from pathlib import Path

import pytest

from driver_venus.config import DEFAULT_CONFIG_PATH, load_config

VENUS = "[venus]\nhost = 192.168.1.50\nportal_id = abc123\n"


def _local(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.ini"
    path.write_text(text)
    return path


def test_defaults_layered_with_a_local_venus_section(tmp_path: Path) -> None:
    config = load_config(local_path=_local(tmp_path, VENUS), env={})
    assert config.mqtt.host == "localhost"
    assert config.mqtt.port == 1883
    assert config.mqtt.username is None
    assert config.mqtt.password is None
    assert config.venus.host == "192.168.1.50"
    assert config.venus.port == 1883
    assert config.venus.portal_id == "abc123"


def test_local_override_layers_over_defaults(tmp_path: Path) -> None:
    local = _local(tmp_path, "[mqtt]\nhost = 192.168.1.10\nusername = venus\n" + VENUS)
    config = load_config(local_path=local, env={})
    assert config.mqtt.host == "192.168.1.10"
    assert config.mqtt.username == "venus"
    assert config.mqtt.port == 1883  # untouched default


def test_env_overrides_both_files(tmp_path: Path) -> None:
    env = {
        "MQTT_HOST": "mosquitto",
        "MQTT_PORT": "1884",
        "MQTT_USERNAME": "venus",
        "MQTT_PASSWORD": "secret",
        "VENUS_MQTT_HOST": "10.0.0.2",
        "VENUS_MQTT_PORT": "1885",
        "VENUS_PORTAL_ID": "fromenv",
    }
    config = load_config(local_path=_local(tmp_path, VENUS), env=env)
    assert (config.mqtt.host, config.mqtt.port) == ("mosquitto", 1884)
    assert (config.mqtt.username, config.mqtt.password) == ("venus", "secret")
    assert (config.venus.host, config.venus.port, config.venus.portal_id) == (
        "10.0.0.2",
        1885,
        "fromenv",
    )


def test_env_alone_is_enough_without_a_local_file(tmp_path: Path) -> None:
    """hub's compose block sets only env vars and mounts no config.ini."""
    env = {"VENUS_MQTT_HOST": "10.0.0.2", "VENUS_PORTAL_ID": "abc123"}
    config = load_config(local_path=tmp_path / "missing.ini", env=env)
    assert config.venus.host == "10.0.0.2"
    assert config.venus.portal_id == "abc123"


def test_empty_env_var_does_not_override(tmp_path: Path) -> None:
    """compose passes `${MQTT_VENUS_PASSWORD:-}`, i.e. an empty string, when unset."""
    local = _local(tmp_path, "[mqtt]\npassword = fromfile\n" + VENUS)
    config = load_config(local_path=local, env={"MQTT_PASSWORD": "", "MQTT_USERNAME": ""})
    assert config.mqtt.password == "fromfile"
    assert config.mqtt.username is None


@pytest.mark.parametrize(
    ("local", "message"),
    [
        ("", "host is required"),
        ("[venus]\nhost = 192.168.1.50\n", "portal_id is required"),
        ("[venus]\nportal_id = abc123\n", "host is required"),
    ],
)
def test_missing_venus_settings_fail_at_startup(tmp_path: Path, local: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_config(local_path=_local(tmp_path, local), env={})


def test_example_is_a_complete_valid_override() -> None:
    example = DEFAULT_CONFIG_PATH.parent / "config.ini.example"
    config = load_config(local_path=example, env={})
    assert config.venus.portal_id == "abc123"
