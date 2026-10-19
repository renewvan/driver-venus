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
- **Node info** (retained): `renewvan/venus/info`, one JSON message
  describing this node (see [Node info](#node-info)). Published on **every
  connect, immediately before `online`**, so a consumer that sees `online`
  always finds info already retained. It is **never cleared**: it stays
  retained when the node goes offline or its last will fires, so a consumer
  can say "offline, last seen vX". Payload shape: `hub`'s
  `schema/node-info.schema.json`.

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

The release workflow passes the tag as the `NODE_VERSION` build argument, which
the Dockerfile promotes to an environment variable the node reads (see
[Node info](#node-info)). Nothing else carries a version.

## Node info

The node describes itself to the dashboard with a manifest plus two runtime
values. Contract: `hub`'s `schema/node-info.schema.json` (decision record:
`hub/docs/adr/0011-node-manifest-and-retained-info-topic.md`).

**`manifest.json`** (repo root) is the single source of the static fields:
`node` (`venus`, the topic key, same as `renewvan/venus/health`), `product`,
`source`, `publishes` (`battery`, `solar`, `charger`: one node, three entity
types, which is how the dashboard attributes those instances to this node) and
optional `manufacturer` / `homepage`. `version` and `host_serial` are
**forbidden** in it. The image build copies it beside the module
(`node_venus/manifest.json`); the node reads that copy first and falls back to
the repo-root file for a checkout run.

**`version`** comes from the git release tag and nowhere else. The release
workflow passes it as the `NODE_VERSION` build argument, which becomes an
environment variable the node reads. When `NODE_VERSION` is unset or empty (a
checkout run, a local `docker build`) the node reports the literal **`dev`**.
There is no `version` file or `__version__`, and the `pyproject.toml` version
is a fixed placeholder nothing reads.

**`host_serial`** is the `Serial` line of the host's `/proc/cpuinfo`, read once
at start. A default container can read it, so no compose or Dockerfile change
is needed. It is **omitted** (never faked, never `unknown`) when the file is
unreadable, the line is missing or empty, or the value is all zeros.

`node_venus/node_info.py` is a small helper deliberately **copied** into each
Python node repo rather than shared as a package, so each node releases
independently.

**CI gate:** `.github/workflows/manifest.yml` validates `manifest.json` against
`node-manifest.schema.json`, fetched from `hub` at a **pinned commit**
(`HUB_REF`) with `ajv-cli`, and fails if a manifest containing `version` is
accepted. Bump `HUB_REF` deliberately to adopt a newer contract. To check
locally:

```bash
npx --yes ajv-cli@5 validate -s path/to/hub/schema/node-manifest.schema.json -d manifest.json
```
