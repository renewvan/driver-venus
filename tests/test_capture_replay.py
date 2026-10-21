"""Replays a full capture from a real Venus OS device (SmartShunt, MPPT,
Orion XS, Blue Smart IP22) through the mapping, so a payload shape the
hand-written fixtures miss shows up here. Serial, name and portal ID are
redacted in the capture.
"""

import json
from pathlib import Path

from driver_venus.mapping import map_service_message, split_service_topic

CAPTURE = Path(__file__).parent / "fixtures" / "venus_capture_2026-10-16.json"
PORTAL = "PORTAL"


def _replay_charger() -> dict[str, object]:
    published: dict[str, object] = {}
    for topic, payload in json.loads(CAPTURE.read_text()).items():
        parsed = split_service_topic(topic, PORTAL)
        if parsed is None or parsed[0] != "charger":
            continue
        published.update(map_service_message(*parsed, payload))
    return published


def test_ip22_capture_publishes_only_schema_fields():
    published = _replay_charger()
    assert published == {
        "renewvan/charger/289/voltage_v": 13.279999732971191,
        "renewvan/charger/289/source": "ac",
        "renewvan/charger/289/current_a": 30.0,
        "renewvan/charger/289/charge_state": "bulk",
    }
