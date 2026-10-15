"""Fixture Venus OS MQTT payloads (decoded `{"value": ...}` envelope).

`BATTERIES_SMARTSHUNT` is the shape captured from a real Venus OS device
with a SmartShunt on VE.Direct: no `temperature` (no probe), instance 290.
"""

# Captured from a live GX: a single SmartShunt, no temperature probe.
BATTERIES_SMARTSHUNT = {
    "value": [
        {
            "active_battery_service": True,
            "current": 0.6000000238418579,
            "id": "com.victronenergy.battery.ttyUSB2",
            "instance": 290,
            "name": "Camila SmartShunt",
            "power": 8.064000129699707,
            "soc": 99.30000305175781,
            "state": 0,
            "voltage": 13.4399995803833,
        }
    ]
}

# Two banks, one with a temperature probe.
BATTERIES_TWO_BANKS = {
    "value": [
        {
            "instance": 290,
            "soc": 80.0,
            "voltage": 13.1,
            "current": -4.0,
            "power": -52.4,
            "temperature": 21.5,
        },
        {"instance": 512, "soc": 55.0, "voltage": 12.6, "current": 0.0, "power": 0.0},
    ]
}

# An element Venus published without an instance: no id to publish under.
BATTERIES_NO_INSTANCE = {"value": [{"soc": 50.0, "voltage": 12.8, "current": 0.0, "power": 0.0}]}

BATTERIES_EMPTY = {"value": []}

SYSTEM_STATE_BULK = {"value": 3}
SYSTEM_STATE_NULL = {"value": None}
SYSTEM_STATE_SCHEDULED_RECHARGE = {"value": 259}
SYSTEM_STATE_UNRECOGNIZED_CODE = {"value": 9999}

# Captured from a live GX.
SOLAR_YIELD_POWER = {"value": 14.0}
SOLAR_PV_VOLTAGE = {"value": 47.529998779296875}
SOLAR_BATTERY_VOLTAGE = {"value": 13.4399995803833}
SOLAR_BATTERY_CURRENT = {"value": 1.399999976158142}
SOLAR_YIELD_TODAY_KWH = {"value": 0.412}
SOLAR_STATE_BULK = {"value": 3}

ALTERNATOR_VOLTAGE = {"value": 13.390000343322754}
ALTERNATOR_INPUT_VOLTAGE = {"value": 12.539999961853027}
ALTERNATOR_POWER = {"value": 243.0}

TIME_SINCE_FULL_CHARGE = {"value": 168723}
TIME_TO_GO = {"value": 98400.0}
# Venus's "no estimate" sentinel (~10 days) and the null it sends when idle.
TIME_TO_GO_SENTINEL = {"value": 863999.9375}
TIME_TO_GO_NULL = {"value": None}
