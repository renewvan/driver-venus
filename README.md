# node-venus

Victron Venus OS MQTT → renewvan bus. Bridges everything a Venus OS device
(Cerbo GX, Raspberry Pi running Venus OS, …) already knows about the van's
power system onto the vendor-neutral `battery`, `solar` and `charger`
entities from `hub`'s `schema/`. No new sensing, just a topic remap of an
existing feed.

Use this node **if the van already runs Venus OS**. A van without a GX
device reads its hardware directly with a different node; both publish the
same entities, so nothing downstream cares which one is in use. See
`hub/docs/adr/0008-node-naming-and-entity-neutrality.md`.

## Two persistent MQTT connections

- **Venus OS broker** (subscribe only): `N/<portalId>/#`. Venus only
  re-sends a value when it changes and stops publishing once its last
  subscriber disconnects, so the subscription is held open for the life of
  the process and a `R/<portalId>/keepalive` is sent on connect and every
  30 s so slow-changing values (a full battery's SoC) still appear.
- **Renewvan bus** (publish only, retained): `renewvan/<entity>/<id>/*`, plus
  node liveness on `renewvan/venus/health` (`online`/`offline` via MQTT
  LWT) — deliberately 3 segments, not 4, so it can't be mistaken for an
  entity keyed by a fake `health` id.

## Ids

An entity's `<id>` is its Venus **device instance** (e.g. `290`), the stable
per-device number Venus assigns. It is never derived from the user-editable
device name and there is no static map to maintain: a van's devices are
discovered from the feed.

## Mapping

| Venus source | → renewvan topic | Notes |
|---|---|---|
| `system/0/Batteries[]` `soc`/`voltage`/`current`/`power` | `battery/<instance>/soc_pct`/`voltage_v`/`current_a`/`power_w` | direct copy, signed (+charging) |
| `system/0/Batteries[]` `temperature` | `battery/<instance>/temperature_c` | only when the device has a probe |
| `battery/<n>/TimeToGo` | `battery/<n>/time_to_go_s` | Venus's `null` clears the topic; its ~10-day cap (863999.9375 s) is published as-is |
| `battery/<n>/History/TimeSinceLastFullCharge` | `battery/<n>/time_since_full_charge_s` | |
| `system/0/SystemState/State` | `battery/<id>/charge_state` | one system-wide value, fanned out to every battery id seen |
| `solarcharger/<n>/Yield/Power` | `solar/<n>/power_w` | |
| `solarcharger/<n>/Dc/0/Voltage`/`Current` | `solar/<n>/battery_voltage_v`/`battery_current_a` | |
| `solarcharger/<n>/Pv/V`/`Pv/I` | `solar/<n>/pv_voltage_v`/`pv_current_a` | |
| `solarcharger/<n>/History/Daily/0/Yield` | `solar/<n>/yield_today_wh` | kWh → Wh |
| `solarcharger/<n>/History/Daily/<0..N-1>/Yield`, `History/Overall/DaysAvailable` | `solar/<n>/yield_history_wh` | one retained JSON array, newest first (index 0 = today), kWh → Wh. A Venus `null` slot is a `null` entry (no data), never `0`. See below |
| `solarcharger/<n>/State` | `solar/<n>/charge_state` | |
| `alternator/<n>/Dc/0/Voltage`/`Current`/`Power`, `Dc/In/V` | `charger/<n>/voltage_v`/`current_a`/`power_w`/`input_voltage_v` | DC-DC charger; `source` = `alternator` |
| `charger/<n>/Dc/0/Voltage`/`Current` | `charger/<n>/voltage_v`/`current_a` | AC charger (e.g. BlueSmart); `source` = `ac`. Venus publishes AC *input* power, not output, so `power_w` is not set |
| `alternator/<n>/State`, `charger/<n>/State` | `charger/<n>/charge_state` | 246 → `absorption`, 247 → `equalize`, 248 (BatterySafe) → `float`; any other unmapped code (e.g. 11, power supply) → `unknown` |

`Batteries[].state`/`.bmsstate`/`.name`/`.id` are never read. Anything Venus
publishes that the schema has no property for is ignored. A value that goes
`null` clears its retained topic (an empty retained payload), so a reading
that stopped being valid does not linger on the bus.

**Solar history.** Venus publishes a controller's day log as one message per
day slot (`History/Daily/0..30/Yield`, kWh, slot 0 = today) and the slot count
in `History/Overall/DaysAvailable`. A fresh subscribe delivers every slot at
once and each `R/<portal>/keepalive` makes Venus send them all again, so the
node folds them into one `yield_history_wh` array (the only stateful part of
the mapping, `SolarYieldHistory`). The array is published after the burst of
slot messages has been quiet for 2 s, and only when it is complete (every slot
`DaysAvailable` promises has been re-received since the last publish) and
different from the last one: never half-filled at startup, never half-shifted
at the day rollover (a burst that stalls waits for the rest), and not again on
every keepalive. `DaysAvailable` of 0 publishes nothing. A controller with fewer days logged publishes a shorter
array. Decision and reasoning: `hub` `docs/adr/0009`.

The mapping is pure (`node_venus/mapping.py`, no network/MQTT client) and is
what `tests/test_mapping.py` exercises against fixture Venus payloads, no
broker or GX device required. Fixtures marked as captured are real payloads
from a Venus OS device with a SmartShunt, an MPPT and an Orion DC-DC charger.

## Configuration

Environment variables (matches `hub`'s `docker-compose.yml` `node-venus:`
service block):

| Variable | Default | Notes |
|---|---|---|
| `MQTT_HOST` | `mosquitto` | Renewvan bus broker |
| `MQTT_PORT` | `1883` | |
| `MQTT_USERNAME` | _(none)_ | |
| `MQTT_PASSWORD` | _(none)_ | |
| `VENUS_MQTT_HOST` | _(required)_ | The Venus OS device's own broker |
| `VENUS_MQTT_PORT` | `1883` | |
| `VENUS_PORTAL_ID` | _(required)_ | Venus OS portal ID (`N/<portalId>/…`), from the device |

## Running

```bash
pip install -r requirements.txt
VENUS_MQTT_HOST=192.168.1.50 VENUS_PORTAL_ID=abc123 python -m node_venus.main
```

## Testing

```bash
pip install -r requirements.txt -r requirements-test.txt
pytest tests/ -v
```

## Releasing

Tagging a GitHub release builds and publishes
`ghcr.io/<owner>/node-venus:<tag>`, which `hub`'s deployment compose
file pins by tag (never builds from source — see
`hub/docs/adr/0001-compose-services-via-pinned-images-not-git-submodules.md`).
