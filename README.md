# driver-venus

Victron Venus OS MQTT → renewvan bus. Bridges everything a Venus OS device
(Cerbo GX, Raspberry Pi running Venus OS, …) already knows about the van's
power system onto the vendor-neutral `battery`, `solar` and `charger`
entities from `hub`'s `schema/`. No new sensing, just a topic remap of an
existing feed.

Use this driver **if the van already runs Venus OS**. A van without a GX
device reads its hardware directly with a different driver; both publish the
same entities, so nothing downstream cares which one is in use. See
`hub/docs/adr/0008-node-naming-and-entity-neutrality.md`.

## Two persistent MQTT connections

- **Venus OS broker** (subscribe only): `N/<portalId>/#`. Venus only
  re-sends a value when it changes and stops publishing once its last
  subscriber disconnects, so the subscription is held open for the life of
  the process and a `R/<portalId>/keepalive` is sent on connect and every
  30 s so slow-changing values (a full battery's SoC) still appear.
- **Renewvan bus** (publish only, retained): `renewvan/<entity>/<id>/*`, plus
  driver liveness on `renewvan/venus/health` (`online`/`offline` via MQTT
  LWT) — deliberately 3 segments, not 4, so it can't be mistaken for an
  entity keyed by a fake `health` id.
- **Driver info** (retained): `renewvan/venus/info`, one JSON message
  describing this driver (see [Driver info](#driver-info)). Published on **every
  connect, immediately before `online`**, so a consumer that sees `online`
  always finds info already retained. It is **never cleared**: it stays
  retained when the driver goes offline or its last will fires, so a consumer
  can say "offline, last seen vX". Payload shape: `hub`'s
  `schema/driver-info.schema.json`.

## Ids

An entity's `<id>` is its Venus **device instance** (e.g. `290`), the stable
per-device number Venus assigns. It is never derived from the user-editable
device name and there is no static map to maintain: a van's devices are
discovered from the feed.

Every instance also publishes two retained identity topics under its own
`renewvan/<entity>/<id>/`, for `battery`, `solar` and `charger`:

| Topic | Payload | When |
|---|---|---|
| `driver` | `"venus"` (this driver's key, the `renewvan/venus/info` segment) | when the instance is first discovered, and again on every bus reconnect |
| `name` | the instance's label as a JSON string | Venus's `CustomName`, else its `ProductName` (`<service>/<n>/CustomName` / `ProductName`); republished when it changes and again on every bus reconnect. Cleared (empty retained payload) when Venus stops providing a usable label (null, empty or non-string). An instance Venus gives no label for publishes no `name` |

The dashboard uses `driver` to attribute an instance to this driver when
another driver (e.g. `wattcycle`) publishes the same entity type.

## Mapping

| Venus source | → renewvan topic | Notes |
|---|---|---|
| `system/0/Batteries[]` `soc`/`voltage`/`current`/`power` | `battery/<instance>/soc_pct`/`voltage_v`/`current_a`/`power_w` | direct copy, signed (+charging) |
| `system/0/Batteries[]` `temperature` | `battery/<instance>/temperature_c` | only when the device has a probe |
| `battery/<n>/TimeToGo` | `battery/<n>/time_to_go_s` | Venus's `null` clears the topic; its ~10-day cap (863999.9375 s) is published as-is |
| `battery/<n>/History/TimeSinceLastFullCharge` | `battery/<n>/time_since_full_charge_s` | |
| `battery/<n>/Capacity` | `battery/<n>/capacity_ah` | a shunt's configured bank capacity |
| `battery/<n>/Capacity` + `ConsumedAmphours` | `battery/<n>/remaining_ah` | capacity plus the shunt's (negative) Ah drawn since its last sync, clamped at 0; published once both are known. A service that reports `InstalledCapacity` (whose `Capacity` may already be the remaining Ah) publishes neither |
| `battery/<n>/Voltages/Cell<N>` or `Cell/<N>/Volts` | `battery/<n>/cell_voltages_v` | one retained array, index _i_ = cell _i_+1, volts. A `null` cell is a `null` slot, never `0`. See below |
| `battery/<n>/Balances/Cell<N>` | `battery/<n>/cell_balancing` | one retained boolean array aligned with `cell_voltages_v`; absent if that is. Venus reads a BMS that does not report balancing as `0`, so that publishes `false` |
| `battery/<n>/System/Temperature1..4`, `System/MOSTemperature` | `battery/<n>/temperatures_c` | one retained array in that order (the MOSFET last); a probe Venus has no value for is `null`, keeping its index |
| `battery/<n>/System/MaxCellVoltage` / `MinCellVoltage`, `Voltages/Diff` or `Cell/Diff` | `battery/<n>/cell_voltage_max_v` / `cell_voltage_min_v` / `cell_voltage_delta_v` | only what Venus reports, never computed here |
| `battery/<n>/Io/AllowToCharge` / `Io/AllowToDischarge` | `battery/<n>/allow_charge` / `allow_discharge` | Venus reads an unknown FET state as `0`, so a `false` cannot be told from "not reporting" |
| `battery/<n>/Info/MaxChargeVoltage` / `MaxChargeCurrent` / `MaxDischargeCurrent` | `battery/<n>/charge_voltage_limit_v` / `charge_current_limit_a` / `discharge_current_limit_a` | |
| `battery/<n>/Alarms/*` | `battery/<n>/protections` | one retained array of schema names; only alarm level `2` is active (warnings are ignored). See below |
| `system/0/SystemState/State` | `battery/<id>/charge_state` | one system-wide value, fanned out to every battery id seen |
| `solarcharger/<n>/Yield/Power` | `solar/<n>/power_w` | |
| `solarcharger/<n>/Dc/0/Voltage`/`Current` | `solar/<n>/battery_voltage_v`/`battery_current_a` | |
| `solarcharger/<n>/Pv/V`/`Pv/I` | `solar/<n>/pv_voltage_v`/`pv_current_a` | |
| `solarcharger/<n>/History/Daily/0/Yield` | `solar/<n>/yield_today_wh` | kWh → Wh |
| `solarcharger/<n>/History/Daily/<0..N-1>/Yield`, `History/Overall/DaysAvailable` | `solar/<n>/yield_history_wh` | one retained JSON array, newest first (index 0 = today), kWh → Wh. A Venus `null` slot is a `null` entry (no data), never `0`. See below |
| `solarcharger/<n>/State` | `solar/<n>/charge_state` | |
| `alternator/<n>/Dc/0/Voltage`/`Current`/`Power`, `Dc/In/V` | `charger/<n>/voltage_v`/`current_a`/`power_w`/`input_voltage_v` | DC-DC charger; `source` = `alternator` |
| `charger/<n>/Dc/0/Voltage`/`Current` | `charger/<n>/voltage_v`/`current_a` | AC charger (e.g. BlueSmart); `source` = `ac`. Venus publishes AC *input* power, not output, so `power_w` is not set |
| `battery/<n>/CustomName` / `ProductName` | `battery/<n>/name` | `CustomName`, else `ProductName`; cleared when neither is usable |
| `solarcharger/<n>/CustomName` / `ProductName` | `solar/<n>/name` | same |
| `alternator/<n>/CustomName` / `ProductName`, `charger/<n>/CustomName` / `ProductName` | `charger/<n>/name` | same |
| `alternator/<n>/State`, `charger/<n>/State` | `charger/<n>/charge_state` | 246 → `absorption`, 247 → `equalize`, 248 (BatterySafe) → `float`; any other unmapped code (e.g. 11, power supply) → `unknown` |

**BMS data.** The cell, probe, balancing, limit, allow and alarm rows are read from
the per-device paths `N/<portal>/battery/<instance>/...` (the same instance id as
`Batteries[]`, already covered by the `N/<portalId>/#` subscription), not from
`system/0/Batteries`. They are `dbus-serialbattery` extensions whose layout depends
on its configuration (`BATTERY_CELL_DATA_FORMAT`) and BMS, so each is published only
when Venus sends it: a plain SmartShunt publishes none of the cell data. Victron's
own paths are the `Io/AllowTo*`, `Info/Max*` and `Alarms/*` ones. Contract: `hub`
`docs/adr/0022-per-cell-bms-data-lives-on-battery.md`. Like the solar history, each
array is built from one message per slot (`BatteryBms`), published once the burst has
been quiet for 2 s and only when it differs from the last publish, and replaced
wholesale at its new length if the cell count changes. When no cell has a value the
array is absent (cleared), never `[]` or all `null`s.

`protections` maps alarms by name: `HighCellVoltage` `cell_overvoltage`,
`LowCellVoltage` `cell_undervoltage`, `HighVoltage` `pack_overvoltage`, `LowVoltage`
`pack_undervoltage`, `HighChargeTemperature` / `LowChargeTemperature`
`charge_overtemperature` / `charge_undertemperature`, `HighTemperature` /
`LowTemperature` `overtemperature` / `undertemperature`, `HighChargeCurrent` /
`HighDischargeCurrent` `charge_overcurrent` / `discharge_overcurrent`,
`InternalFailure` `internal_fault`, `CellImbalance` `cell_imbalance`. Any other alarm
at level 2 publishes `other` (and is logged); `LowSoc`, `BmsCable`, `FuseBlown`,
`StateOfHealth` and the starter-battery alarms are ignored. `[]` means alarms are
reported and none is at level 2; the property is absent while every alarm is `null`.

`Batteries[].state`/`.bmsstate`/`.name`/`.id` are never read. Anything Venus
publishes that the schema has no property for is ignored. A value that goes
`null` clears its retained topic (an empty retained payload), so a reading
that stopped being valid does not linger on the bus.

**Solar history.** Venus publishes a controller's day log as one message per
day slot (`History/Daily/0..30/Yield`, kWh, slot 0 = today) and the slot count
in `History/Overall/DaysAvailable`. A fresh subscribe delivers every slot at
once and each `R/<portal>/keepalive` makes Venus send them all again, so the
driver folds them into one `yield_history_wh` array (the only stateful part of
the mapping, `SolarYieldHistory`). The array is published after the burst of
slot messages has been quiet for 2 s, and only when it is complete (every slot
`DaysAvailable` promises has been re-received since the last publish) and
different from the last one: never half-filled at startup, never half-shifted
at the day rollover (a burst that stalls waits for the rest), and not again on
every keepalive. `DaysAvailable` of 0 publishes nothing. A controller with fewer days logged publishes a shorter
array. Decision and reasoning: `hub` `docs/adr/0009`.

The mapping is pure (`driver_venus/mapping.py`, no network/MQTT client) and is
what `tests/test_mapping.py` exercises against fixture Venus payloads, no
broker or GX device required. Fixtures marked as captured are real payloads
from a Venus OS device with a SmartShunt, an MPPT and an Orion DC-DC charger.

## Configuration

Environment variables (matches `hub`'s `docker-compose.yml` `driver-venus:`
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
VENUS_MQTT_HOST=192.168.1.50 VENUS_PORTAL_ID=abc123 python -m driver_venus.main
```

## Testing

```bash
pip install -r requirements.txt -r requirements-test.txt
pytest tests/ -v
```

## Releasing

Start a release from **Actions → Release → Run workflow**, or
`gh workflow run release.yml -f bump=minor` (`patch`, `major`, or `-f version=0.2.0`
to set it explicitly). One run works out the next version from the latest `v*` tag,
tags `main`, creates the GitHub release and builds and publishes
`ghcr.io/<owner>/driver-venus:<tag>` (and `:latest`), which `hub`'s deployment compose
file pins by tag (never builds from source — see
`hub/docs/adr/0001-compose-services-via-pinned-images-not-git-submodules.md`).

A beta from a feature branch: dispatch the workflow on that branch with **prerelease**
ticked. It runs the tests, publishes only its own tag (never `:latest`) and writes nothing
to `main`. The process is shared by every renewvan repo and lives in `hub` (`hub/docs/adr/0015-one-release-process-via-reusable-workflows.md`);
this repo's `release.yml` only says what it ships.

The release workflow passes the tag as the `DRIVER_VERSION` build argument, which
the Dockerfile promotes to an environment variable the driver reads (see
[Driver info](#driver-info)). Nothing else carries a version.

## Driver info

The driver describes itself to the dashboard with a manifest plus two runtime
values. Contract: `hub`'s `schema/driver-info.schema.json` (decision record:
`hub/docs/adr/0011-node-manifest-and-retained-info-topic.md`).

**`manifest.json`** (repo root) is the single source of the static fields:
`driver` (`venus`, the topic key, same as `renewvan/venus/health`), `product`,
`source`, `publishes` (`battery`, `solar`, `charger`: one driver, three entity
types, which is how the dashboard attributes instances that do not name their `driver` to this driver) and
optional `manufacturer` / `homepage`. `version` and `board_serial` are
**forbidden** in it. The image build copies it beside the module
(`driver_venus/manifest.json`); the driver reads that copy first and falls back to
the repo-root file for a checkout run.

**`version`** comes from the git release tag and nowhere else. The release
workflow passes it as the `DRIVER_VERSION` build argument, which becomes an
environment variable the driver reads. When `DRIVER_VERSION` is unset or empty (a
checkout run, a local `docker build`) the driver reports the literal **`dev`**.
There is no `version` file or `__version__`, and the `pyproject.toml` version
is a fixed placeholder nothing reads.

**`board_serial`** is the `Serial` line of the board's `/proc/cpuinfo`, read once
at start. A default container can read it, so no compose or Dockerfile change
is needed. It is **omitted** (never faked, never `unknown`) when the file is
unreadable, the line is missing or empty, or the value is all zeros.

`driver_venus/driver_info.py` is a small helper deliberately **copied** into each
Python driver repo rather than shared as a package, so each driver releases
independently.

**CI gate:** `.github/workflows/manifest.yml` calls hub's reusable manifest workflow,
which validates `manifest.json` against `driver-manifest.schema.json` at a **pinned hub
commit** (`hub-ref`, the same SHA the workflow is pinned with) and fails if a manifest
containing `version` is accepted. Bump both together to adopt a newer contract. To check
locally:

```bash
npx --yes ajv-cli@5 validate -s path/to/hub/schema/driver-manifest.schema.json -d manifest.json
```
