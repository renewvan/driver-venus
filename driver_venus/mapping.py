"""Pure mapping: Victron Venus OS MQTT messages -> renewvan bus publishes.
No network, no MQTT client — this is the seam unit-tested against fixture
payloads.

Venus publishes two shapes this driver cares about:

- **Aggregates** — `N/<portal>/system/0/Batteries` (one JSON array element
  per battery service) and `N/<portal>/system/0/SystemState/State` (one
  system-wide charge stage). Mapped by `map_batteries` / `map_charge_state`.
- **Per-service paths** — `N/<portal>/<service>/<instance>/<path...>`, one
  scalar per message (`solarcharger`, `alternator`, `charger`, `battery`).
  Mapped by `map_service_message`, one message in -> at most one publish out.

Entity ids are the Venus **device instance** (a stable per-device number,
e.g. `290`), never the user-editable `name` and never a static map: an
open-source driver cannot know which instances a given van has.

Every instance also names this driver (`driver`, retained) and, when Venus
has a label for it, a human `name`: see `InstanceIdentity`.

A `None` value in a returned `(topic, value)` pair means "clear this
retained topic" (Venus sends `null` when a reading stops being valid, e.g.
`TimeToGo` when the device has no estimate). The publisher turns
it into an empty retained payload so a stale value does not linger.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

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
    246: "absorption",  # repeated absorption
    247: "equalize",  # auto equalize / recondition
    248: "float",  # BatterySafe (voltage held below absorption)
    252: "external_control",
}

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
    ("alternator", "Dc/0/Power"): ("charger", "power_w", 1.0),
    ("alternator", "Dc/In/V"): ("charger", "input_voltage_v", 1.0),
    ("charger", "Dc/0/Voltage"): ("charger", "voltage_v", 1.0),
    ("charger", "Dc/0/Current"): ("charger", "current_a", 1.0),
    # Per-battery extras that `Batteries[]` does not carry.
    ("battery", "TimeToGo"): ("battery", "time_to_go_s", 1.0),
    ("battery", "History/TimeSinceLastFullCharge"): ("battery", "time_since_full_charge_s", 1.0),
    # BMS limits (Victron DVCC paths) and the cell extremes a BMS-class
    # battery reports itself (docs/adr/0022 in hub). Source-reported, never computed.
    ("battery", "Info/MaxChargeVoltage"): ("battery", "charge_voltage_limit_v", 1.0),
    ("battery", "Info/MaxChargeCurrent"): ("battery", "charge_current_limit_a", 1.0),
    ("battery", "Info/MaxDischargeCurrent"): ("battery", "discharge_current_limit_a", 1.0),
    ("battery", "System/MaxCellVoltage"): ("battery", "cell_voltage_max_v", 1.0),
    ("battery", "System/MinCellVoltage"): ("battery", "cell_voltage_min_v", 1.0),
    ("battery", "Voltages/Diff"): ("battery", "cell_voltage_delta_v", 1.0),
    ("battery", "Cell/Diff"): ("battery", "cell_voltage_delta_v", 1.0),
}

# (venus service class, venus path) -> (entity, property) for a Venus 0/1 flag
# published as a boolean. Venus reads an unknown FET state as 0, so a `false`
# here cannot be told from "the BMS is not reporting" (hub ADR 0022).
_BOOLEAN_PATHS: dict[tuple[str, str], tuple[str, str]] = {
    ("battery", "Io/AllowToCharge"): ("battery", "allow_charge"),
    ("battery", "Io/AllowToDischarge"): ("battery", "allow_discharge"),
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


# This driver's key: its repo name minus `driver-`, equal to `renewvan/venus/info`.
DRIVER_KEY = "venus"

# Venus service class -> the entity its instances are published as, for the
# label paths below. (`entity_topic` ids come from the same instance number.)
_LABEL_ENTITY: dict[str, str] = {
    "battery": "battery",
    "solarcharger": "solar",
    "alternator": "charger",
    "charger": "charger",
}

# Venus per-service label paths, in the order they win: the user's
# `CustomName`, else the hardware's `ProductName`.
_LABEL_PATHS: tuple[str, ...] = ("CustomName", "ProductName")

_UNPUBLISHED = object()


def entity_topic(entity: str, entity_id: str, prop: str) -> str:
    return f"renewvan/{entity}/{entity_id}/{prop}"


_DAILY_YIELD_PATH = re.compile(r"History/Daily/(\d+)/Yield")
_DAYS_AVAILABLE_PATH = "History/Overall/DaysAvailable"


class SolarYieldHistory:
    """Folds Venus's per-day-slot solar yield messages into one
    `yield_history_wh` array per controller.

    Venus publishes one message per day slot (`History/Daily/<n>/Yield`,
    kWh, slot 0 = today) and the slot count in `History/Overall/
    DaysAvailable`. The renewvan wire carries the whole history as one
    retained array (docs/adr/0009), so this is the one stateful piece of
    the otherwise stateless mapping. No network, no clock.

    The array is published by `flush()`, never from `handle()`: Venus
    sends the slots one message at a time, so publishing as they arrive
    would put half-filled arrays on the bus at startup and half-*shifted*
    ones at the day rollover (every slot moves one place), which is the
    non-atomic state the single array exists to avoid. The caller flushes
    once a burst of slot messages has gone quiet (`subscriber.py`).

    `flush()` returns a controller's array only when every slot
    `DaysAvailable` promises has been (re)received *since the last flush*,
    not merely at some point. Counting slots seen ever would let a burst
    that stalls half way publish new slots beside the previous burst's
    old ones, which is the half-shifted array again; this way a stalled
    burst just waits for the rest. It also only returns an array that
    differs from the last one, so Venus re-sending every slot on each
    keepalive does not republish.

    A slot Venus reports as `null` is a day with no data: `None` in the
    array, never `0`. The array still publishes with the gap in it. A
    negative yield is not a reading the schema allows, so it is treated
    as no data too. `DaysAvailable` of 0 publishes nothing: a controller
    with no days logged has no history, which is the property being
    absent, not an empty chart.
    """

    def __init__(self) -> None:
        self._days: dict[str, int] = {}
        self._slots: dict[str, dict[int, float | None]] = {}
        self._fresh: dict[str, set[int]] = {}
        self._published: dict[str, list[float | None]] = {}

    def handle(self, service: str, instance: str, path: str, payload: dict) -> bool:
        """Record one per-service message. Returns True if it was a history
        message (so the caller knows to schedule a `flush()`)."""
        if service != "solarcharger":
            return False
        value = payload.get("value")

        if path == _DAYS_AVAILABLE_PATH:
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                return False
            self._days[instance] = int(value)
            return True

        match = _DAILY_YIELD_PATH.fullmatch(path)
        if match is None:
            return False
        slot = int(match.group(1))
        # Round like the scalar mapping: 0.21 kWh * 1000 is 209.99999..., not 210.
        wh = None if value is None or value < 0 else round(value * 1000.0, 3)
        self._slots.setdefault(instance, {})[slot] = wh
        self._fresh.setdefault(instance, set()).add(slot)
        return True

    def flush(self) -> list[tuple[str, object]]:
        """`(topic, array)` for every controller whose history has been
        completely re-received since the last flush and has changed."""
        results: list[tuple[str, object]] = []
        for instance, days in self._days.items():
            fresh = self._fresh.get(instance, set())
            if days < 1 or any(slot not in fresh for slot in range(days)):
                continue
            slots = self._slots[instance]
            history = [slots[slot] for slot in range(days)]
            fresh.clear()
            if self._published.get(instance) == history:
                continue
            self._published[instance] = history
            results.append((entity_topic("solar", instance, "yield_history_wh"), history))
        return results


_INSTALLED_CAPACITY_PATH = "InstalledCapacity"


class BatteryFuelGauge:
    """Maps a battery service's own fuel gauge to `capacity_ah` and
    `remaining_ah`, so consumers can cross-check `soc_pct` against the
    source's counter.

    A shunt on VE.Direct (SmartShunt, BMV) reports `Capacity` as the bank's
    configured capacity and `ConsumedAmphours` as a negative count of the Ah
    drawn since its last sync (captured: 314.0 and -24.8 at a SoC of 92.6).
    `remaining_ah` is therefore `Capacity + ConsumedAmphours`, which needs
    both, so this is stateful like `SolarYieldHistory`. No network, no clock.

    A service that also reports `InstalledCapacity` (a BMS on CAN, for
    instance) may use `Capacity` for the *remaining* Ah instead. That shape
    has not been seen from a real device, so such an instance publishes
    neither property (and clears them, should they already be out) rather
    than a value that may mean something else.

    A null or non-numeric reading clears what it fed. A computed remaining
    below zero is clamped to 0, the schema's minimum.
    """

    def __init__(self) -> None:
        self._capacity: dict[str, float | None] = {}
        self._consumed: dict[str, float | None] = {}
        self._remaining_published: set[str] = set()
        self._installed: set[str] = set()

    def handle(
        self, service: str, instance: str, path: str, payload: dict
    ) -> list[tuple[str, object]]:
        """`(topic, value)` pairs for one per-service message; nothing for any
        message that is not a battery's capacity or consumed Ah."""
        if service != "battery" or instance in self._installed:
            return []
        capacity_topic = entity_topic("battery", instance, "capacity_ah")
        remaining_topic = entity_topic("battery", instance, "remaining_ah")

        if path == _INSTALLED_CAPACITY_PATH:
            self._installed.add(instance)
            return [(capacity_topic, None), (remaining_topic, None)]

        value = payload.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            value = None

        results: list[tuple[str, object]] = []
        if path == "Capacity":
            value = value if value is None or value >= 0 else None
            self._capacity[instance] = value
            results.append((capacity_topic, value))
        elif path == "ConsumedAmphours":
            self._consumed[instance] = value
        else:
            return []

        capacity = self._capacity.get(instance)
        consumed = self._consumed.get(instance)
        if capacity is not None and consumed is not None:
            # Round like the scalar mapping: 314.0 + -24.7999992 is 289.2000008.
            results.append((remaining_topic, max(round(capacity + consumed, 3), 0.0)))
            self._remaining_published.add(instance)
        elif instance in self._remaining_published:
            results.append((remaining_topic, None))
            self._remaining_published.discard(instance)
        return results


# dbus-serialbattery's `/Voltages/Cell<N>` (format 1/3) and `/Cell/<N>/Volts`
# (format 2/3); the two layouts carry the same cell, so both feed one slot.
_CELL_VOLTS_PATHS = (re.compile(r"Voltages/Cell(\d+)"), re.compile(r"Cell/(\d+)/Volts"))
_CELL_BALANCE_PATH = re.compile(r"Balances/Cell(\d+)")
_ALARM_PATH = re.compile(r"Alarms/(\w+)")
# The schema's `maxItems` for `cell_voltages_v` / `cell_balancing`.
_MAX_CELLS = 32

# Probe order of `temperatures_c`: the four numbered probes, then the MOSFET.
# An index is a fixed probe, so a consumer can tell which is which.
_TEMPERATURE_PATHS: tuple[str, ...] = (
    "System/Temperature1",
    "System/Temperature2",
    "System/Temperature3",
    "System/Temperature4",
    "System/MOSTemperature",
)

# Venus `Alarms/<name>` -> `protections` name (hub battery schema vocabulary).
_ALARM_PROTECTIONS: dict[str, str] = {
    "HighCellVoltage": "cell_overvoltage",
    "LowCellVoltage": "cell_undervoltage",
    "HighVoltage": "pack_overvoltage",
    "LowVoltage": "pack_undervoltage",
    "HighChargeTemperature": "charge_overtemperature",
    "LowChargeTemperature": "charge_undertemperature",
    "HighChargeCurrent": "charge_overcurrent",
    "HighDischargeCurrent": "discharge_overcurrent",
    "InternalFailure": "internal_fault",
    "CellImbalance": "cell_imbalance",
    "HighTemperature": "overtemperature",
    "LowTemperature": "undertemperature",
}

# Alarms that are not a protection of this pack, so they neither count as
# "the source reports protections" nor publish `other`: a state-of-charge
# warning, a cable, a fuse, the starter battery's own voltage, and
# `StateOfHealth` (registered by dbus-serialbattery but never written).
_IGNORED_ALARMS: frozenset[str] = frozenset(
    {
        "LowSoc",
        "BmsCable",
        "FuseBlown",
        "StateOfHealth",
        "LowStarterVoltage",
        "HighStarterVoltage",
    }
)

# `protections` in the schema's vocabulary order, `other` last.
_PROTECTION_ORDER: tuple[str, ...] = (*_ALARM_PROTECTIONS.values(), "other")

_ABSENT = object()


def _number(value: object) -> float | None:
    """`value` if it is a real number, else None (null, bool, string)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


class BatteryBms:
    """Folds a battery service's per-cell, per-probe, balancing and alarm
    messages into the BMS arrays of the `battery` entity (hub ADR 0022):
    `cell_voltages_v`, `cell_balancing`, `temperatures_c` and `protections`.

    Venus sends these one scalar per message (`Voltages/Cell3`,
    `Balances/Cell3`, `System/Temperature2`, `Alarms/HighVoltage`), but the
    wire carries each as one retained array, so this is stateful like
    `SolarYieldHistory`, with the same shape: `handle()` records and says
    whether the message was one of ours, and the caller publishes with
    `flush()` once the burst has gone quiet. Nothing is published from
    `handle()`, so a consumer never sees a half-filled array at startup. No
    network, no clock.

    These paths are `dbus-serialbattery` extensions and which of them exist
    depends on its configuration and the BMS, so every array is built only
    from what was received:

    - `cell_voltages_v` has one slot per cell up to the highest cell number
      seen; a slot Venus reports as `null`, or never sent, is `None`, and a
      negative or non-numeric reading is no reading. All slots `None` (or no
      cell path seen) means the property is absent, never `[]`.
    - `cell_balancing` is aligned with `cell_voltages_v` (same length, `None`
      where a cell's balance was not seen) and absent when that is, or when no
      `Balances/Cell<N>` was seen or all are `null`. Venus reads a BMS that
      does not report balance state as `0`, so that is published as `false`.
    - `temperatures_c` runs through the last probe path seen (see
      `_TEMPERATURE_PATHS`), `None` for a probe that is `null` or not seen,
      and is absent when every probe is.
    - `protections` lists the schema names of the alarms at level `2`
      (warnings, level `1`, are ignored), in vocabulary order. An alarm with no
      name there publishes `other`. It is absent until at least one alarm
      that is a protection has been read with a value, and `[]` when they all
      read OK.

    A property that has been published and then disappears is cleared
    (`None`). `flush()` returns only what differs from the last publish, so
    Venus re-sending every path on each keepalive does not republish.
    """

    def __init__(self) -> None:
        self._volts: dict[str, dict[int, float | None]] = {}
        self._balances: dict[str, dict[int, bool | None]] = {}
        self._temps: dict[str, dict[str, float | None]] = {}
        self._alarms: dict[str, dict[str, int | None]] = {}
        self._dirty: set[str] = set()
        self._published: dict[tuple[str, str], object] = {}

    def handle(self, service: str, instance: str, path: str, payload: dict) -> bool:
        """Record one per-service message. Returns True if it was one of the
        BMS paths (so the caller knows to schedule a `flush()`)."""
        if service != "battery":
            return False
        value = payload.get("value")

        for pattern in _CELL_VOLTS_PATHS:
            match = pattern.fullmatch(path)
            if match is not None:
                cell = int(match.group(1))
                if not 1 <= cell <= _MAX_CELLS:
                    return False
                volts = _number(value)
                slots = self._volts.setdefault(instance, {})
                slots[cell] = volts if volts is not None and volts >= 0 else None
                break
        else:
            match = _CELL_BALANCE_PATH.fullmatch(path)
            if match is not None:
                cell = int(match.group(1))
                if not 1 <= cell <= _MAX_CELLS:
                    return False
                flag = _number(value)
                self._balances.setdefault(instance, {})[cell] = (
                    bool(flag) if flag in (0, 1) else None
                )
            elif path in _TEMPERATURE_PATHS:
                self._temps.setdefault(instance, {})[path] = _number(value)
            else:
                match = _ALARM_PATH.fullmatch(path)
                if match is None or match.group(1) in _IGNORED_ALARMS:
                    return False
                level = _number(value)
                self._alarms.setdefault(instance, {})[match.group(1)] = (
                    None if level is None else int(level)
                )

        self._dirty.add(instance)
        return True

    def flush(self) -> list[tuple[str, object]]:
        """`(topic, array)` for every BMS array of a touched instance that
        differs from what was last published (`None` clears one)."""
        results: list[tuple[str, object]] = []
        for instance in sorted(self._dirty):
            volts = self._cell_voltages(instance)
            wanted = {
                "cell_voltages_v": volts,
                "cell_balancing": self._cell_balancing(instance, volts),
                "temperatures_c": self._temperatures(instance),
                "protections": self._protections(instance),
            }
            for prop, array in wanted.items():
                if self._published.get((instance, prop), _ABSENT) == (
                    _ABSENT if array is None else array
                ):
                    continue
                if array is None:
                    del self._published[(instance, prop)]
                else:
                    self._published[(instance, prop)] = array
                results.append((entity_topic("battery", instance, prop), array))
        self._dirty.clear()
        return results

    def _cell_voltages(self, instance: str) -> list[float | None] | None:
        slots = self._volts.get(instance, {})
        if not any(v is not None for v in slots.values()):
            return None
        return [slots.get(cell) for cell in range(1, max(slots) + 1)]

    def _cell_balancing(
        self, instance: str, volts: list[float | None] | None
    ) -> list[bool | None] | None:
        slots = self._balances.get(instance, {})
        if volts is None or not any(v is not None for v in slots.values()):
            return None
        return [slots.get(cell) for cell in range(1, len(volts) + 1)]

    def _temperatures(self, instance: str) -> list[float | None] | None:
        probes = self._temps.get(instance, {})
        if not any(v is not None for v in probes.values()):
            return None
        last = max(i for i, path in enumerate(_TEMPERATURE_PATHS) if path in probes)
        return [probes.get(path) for path in _TEMPERATURE_PATHS[: last + 1]]

    def _protections(self, instance: str) -> list[str] | None:
        alarms = self._alarms.get(instance, {})
        if all(level is None for level in alarms.values()):
            return None
        alarming = {name for name, level in alarms.items() if level == 2}
        for name in sorted(alarming - _ALARM_PROTECTIONS.keys()):
            logger.warning(
                "Venus alarm %s on battery %s has no protection name: other", name, instance
            )
        active = {_ALARM_PROTECTIONS.get(name, "other") for name in alarming}
        return [name for name in _PROTECTION_ORDER if name in active]


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
    system-wide value, fanned out to every battery id the driver has seen."""
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

    flag = _BOOLEAN_PATHS.get((service, path))
    if flag is not None:
        topic = entity_topic(flag[0], instance, flag[1])
        if value is None:
            return [(topic, None)]
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value in (0, 1):
            return [(topic, bool(value))]
        return []

    mapped = _SERVICE_PATHS.get((service, path))
    if mapped is None:
        return []
    entity, prop, scale = mapped
    topic = entity_topic(entity, instance, prop)

    if value is None:
        return [(topic, None)]
    # Round scaled values: 0.12 kWh * 1000 is 119.99999731..., not 120.
    scaled = round(value * scale, 3) if scale != 1.0 else value
    results: list[tuple[str, object]] = [(topic, scaled)]

    # A charger's source is implied by which Venus service it is; emit it
    # alongside the first voltage so the identity field is always present.
    if entity == "charger" and prop == "voltage_v" and service in _CHARGER_SOURCE:
        results.append((entity_topic("charger", instance, "source"), _CHARGER_SOURCE[service]))
    return results


class InstanceIdentity:
    """Retained identity of every entity instance this driver publishes:
    `driver` (this driver's key) and `name` (Venus's label).

    Stateful like `SolarYieldHistory`, no network, no clock. The caller
    publishes what it returns as retained identity values.

    `driver_pairs` returns the `driver` publish the first time an instance
    shows up in any set of pairs; `label_pairs` returns the `name` publish
    when an instance's label changes. The name is Venus's `CustomName`, else
    its `ProductName`; an absent, null, empty or non-string label is not
    usable, and when neither is usable the retained `name` is cleared (`None`)
    rather than left stale. The first `null` label also clears, so a name
    retained by an earlier run does not outlive Venus's label. An instance
    Venus gives no label for publishes no `name` at all. A value already
    published is not published again, so Venus re-sending every label on each
    keepalive is silent.
    """

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()
        self._labels: dict[tuple[str, str], dict[str, str | None]] = {}
        self._names: dict[tuple[str, str], object] = {}

    def driver_pairs(self, pairs: list[tuple[str, object]]) -> list[tuple[str, object]]:
        """`driver` pairs for instances in `pairs` not seen before."""
        results: list[tuple[str, object]] = []
        for topic, _ in pairs:
            _, entity, entity_id, _ = topic.split("/", 3)
            if (entity, entity_id) not in self._seen:
                self._seen.add((entity, entity_id))
                results.append((entity_topic(entity, entity_id, "driver"), DRIVER_KEY))
        return results

    def label_pairs(
        self, service: str, instance: str, path: str, payload: dict
    ) -> list[tuple[str, object]]:
        """The `name` pair for a label message when the resulting name changed;
        nothing for any other message."""
        entity = _LABEL_ENTITY.get(service)
        if entity is None or path not in _LABEL_PATHS:
            return []
        key = (entity, instance)
        value = payload.get("value")
        labels = self._labels.setdefault(key, {})
        labels[path] = value.strip() if isinstance(value, str) and value.strip() else None
        name = next((labels[p] for p in _LABEL_PATHS if labels.get(p)), None)
        if self._names.get(key, _UNPUBLISHED) == name:
            return []
        self._names[key] = name
        return [(entity_topic(entity, instance, "name"), name)]
