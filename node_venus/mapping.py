"""Pure mapping: Victron Venus OS MQTT messages -> renewvan bus publishes.
No network, no MQTT client — this is the seam unit-tested against fixture
payloads.

Venus publishes two shapes this node cares about:

- **Aggregates** — `N/<portal>/system/0/Batteries` (one JSON array element
  per battery service) and `N/<portal>/system/0/SystemState/State` (one
  system-wide charge stage). Mapped by `map_batteries` / `map_charge_state`.
- **Per-service paths** — `N/<portal>/<service>/<instance>/<path...>`, one
  scalar per message (`solarcharger`, `alternator`, `charger`, `battery`).
  Mapped by `map_service_message`, one message in -> at most one publish out.

Entity ids are the Venus **device instance** (a stable per-device number,
e.g. `290`), never the user-editable `name` and never a static map: an
open-source node cannot know which instances a given van has.

A `None` value in a returned `(topic, value)` pair means "clear this
retained topic" (Venus sends `null` when a reading stops being valid, e.g.
`TimeToGo` once the battery is no longer discharging). The publisher turns
it into an empty retained payload so a stale value does not linger.
"""

from __future__ import annotations

# Venus `Batteries[]` field -> battery entity property. Venus already uses
# the same +charging/-discharging sign convention as the schema.
_BATTERY_FIELDS: dict[str, str] = {
    "soc": "soc_pct",
    "voltage": "voltage_v",
    "current": "current_a",
    "power": "power_w",
    "temperature": "temperature_c",
}

# Venus SystemState/State code -> battery `charge_state`. Any code not in
# this table maps to "unknown" (forward-compat with future firmware).
# Source: victronenergy/venus wiki "Aggregated System State".
SYSTEM_STATE_CODES: dict[int, str] = {
    0: "off",
    1: "low_power",
    2: "fault",
    3: "bulk",
    4: "absorption",
    5: "float",
    6: "storage",
    7: "equalize",
    8: "passthru",
    9: "inverting",
    10: "assisting",
    244: "sustain",
    252: "external_control",
    256: "discharging",
    257: "sustain_ess",
    258: "recharge",
    259: "scheduled_recharge",
}

# Venus charger/solarcharger `State` code -> `charge_state` for those
# entities (a subset of the system-state codes; Venus reuses the numbers).
CHARGER_STATE_CODES: dict[int, str] = {
    0: "off",
    2: "fault",
    3: "bulk",
    4: "absorption",
    5: "float",
    6: "storage",
    7: "equalize",
    252: "external_control",
}

# Venus reports "no estimate" as ~864000 s (10 days, observed as
# 863999.9375 on a live GX) while idle/charging, or as null. Neither is a
# meaningful ETA, so anything at or above this threshold is treated as
# "no estimate". It sits just under the sentinel to absorb the float
# rounding Venus applies.
_NO_ESTIMATE_S = 863999

# (venus service class, venus path) -> (entity, property, scale).
# `scale` converts Venus's unit to the schema's. Only paths the schema has
# a property for are listed; everything else Venus publishes is ignored.
_SERVICE_PATHS: dict[tuple[str, str], tuple[str, str, float]] = {
    ("solarcharger", "Yield/Power"): ("solar", "power_w", 1.0),
    ("solarcharger", "Dc/0/Voltage"): ("solar", "battery_voltage_v", 1.0),
    ("solarcharger", "Dc/0/Current"): ("solar", "battery_current_a", 1.0),
    ("solarcharger", "Pv/V"): ("solar", "pv_voltage_v", 1.0),
    ("solarcharger", "Pv/I"): ("solar", "pv_current_a", 1.0),
    # Venus reports yield in kWh; the schema uses Wh.
    ("solarcharger", "History/Daily/0/Yield"): ("solar", "yield_today_wh", 1000.0),
    ("alternator", "Dc/0/Voltage"): ("charger", "voltage_v", 1.0),
    ("alternator", "Dc/0/Current"): ("charger", "current_a", 1.0),
    ("alternator", "Dc/In/V"): ("charger", "input_voltage_v", 1.0),
    ("charger", "Dc/0/Voltage"): ("charger", "voltage_v", 1.0),
    ("charger", "Dc/0/Current"): ("charger", "current_a", 1.0),
    # Per-battery extras that `Batteries[]` does not carry.
    ("battery", "TimeToGo"): ("battery", "time_to_go_s", 1.0),
    ("battery", "History/TimeSinceLastFullCharge"): ("battery", "time_since_full_charge_s", 1.0),
}

# Service class -> the `charger.source` it implies.
_CHARGER_SOURCE: dict[str, str] = {
    "alternator": "alternator",
    "charger": "ac",
}

# Per-service `State` path -> which entity's charge_state it feeds.
_STATE_ENTITY: dict[str, str] = {
    "solarcharger": "solar",
    "charger": "charger",
    "alternator": "charger",
}


def entity_topic(entity: str, entity_id: str, prop: str) -> str:
    return f"renewvan/{entity}/{entity_id}/{prop}"


def map_batteries(payload: dict) -> list[tuple[str, object]]:
    """Map a decoded `N/<portal>/system/0/Batteries` payload (`{"value":
    [...]}`) to `(topic, value)` pairs, one id per element's Venus
    `instance`. An element without an `instance` is skipped (no id)."""
    results: list[tuple[str, object]] = []
    for element in payload.get("value") or []:
        instance = element.get("instance")
        if instance is None:
            continue
        entity_id = str(instance)
        for venus_field, prop in _BATTERY_FIELDS.items():
            if element.get(venus_field) is not None:
                results.append((entity_topic("battery", entity_id, prop), element[venus_field]))
    return results


def map_charge_state(payload: dict, entity_ids: list[str]) -> list[tuple[str, object]]:
    """Map a decoded `SystemState/State` payload to a battery
    `charge_state` per known battery id. The system state is one
    system-wide value, fanned out to every battery id the node has seen."""
    value = payload.get("value")
    if value is None:
        return [(entity_topic("battery", i, "charge_state"), None) for i in entity_ids]
    state = SYSTEM_STATE_CODES.get(value, "unknown")
    return [(entity_topic("battery", i, "charge_state"), state) for i in entity_ids]


def split_service_topic(topic: str, portal_id: str) -> tuple[str, str, str] | None:
    """`N/<portal>/<service>/<instance>/<path...>` -> `(service, instance,
    path)`, or None if the topic is not a per-service path for this
    portal."""
    prefix = f"N/{portal_id}/"
    if not topic.startswith(prefix):
        return None
    parts = topic[len(prefix) :].split("/", 2)
    if len(parts) != 3 or not parts[1].isdigit():
        return None
    return parts[0], parts[1], parts[2]


def map_service_message(
    service: str, instance: str, path: str, payload: dict
) -> list[tuple[str, object]]:
    """Map one per-service message to at most one `(topic, value)` pair
    (a charger service also emits its `source` once per `State` message).
    Unknown (service, path) combinations map to nothing."""
    value = payload.get("value")

    if path == "State" and service in _STATE_ENTITY:
        entity = _STATE_ENTITY[service]
        if value is None:
            return [(entity_topic(entity, instance, "charge_state"), None)]
        state = CHARGER_STATE_CODES.get(value, "unknown")
        return [(entity_topic(entity, instance, "charge_state"), state)]

    mapped = _SERVICE_PATHS.get((service, path))
    if mapped is None:
        return []
    entity, prop, scale = mapped
    topic = entity_topic(entity, instance, prop)

    if value is None:
        return [(topic, None)]
    if prop == "time_to_go_s" and value >= _NO_ESTIMATE_S:
        return [(topic, None)]
    # Round scaled values: 0.12 kWh * 1000 is 119.99999731..., not 120.
    scaled = round(value * scale, 3) if scale != 1.0 else value
    results: list[tuple[str, object]] = [(topic, scaled)]

    # A charger's source is implied by which Venus service it is; emit it
    # alongside the first voltage so the identity field is always present.
    if entity == "charger" and prop == "voltage_v" and service in _CHARGER_SOURCE:
        results.append((entity_topic("charger", instance, "source"), _CHARGER_SOURCE[service]))
    return results
