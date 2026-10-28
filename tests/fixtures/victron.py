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

# SmartShunt fuel gauge, captured from the live GX on 2026-10-28: the
# configured bank capacity and the (negative) Ah drawn since the last sync.
CAPACITY = {"value": 314.0}
CONSUMED_AMPHOURS = {"value": -24.799999237060547}


# --- Solar daily history -------------------------------------------------
# Captured from a live GX (Venus OS v3.80, portal b827eb0cd27c) with one
# MPPT, device instance 291, on 2026-10-15: `N/<portal>/solarcharger/291/
# History/Daily/<0..30>/Yield` (kWh, newest first: 0 = today) plus
# `History/Overall/DaysAvailable`. A fresh subscribe delivers all of them
# at once (not as retained messages), and a `R/<portal>/keepalive` makes
# Venus send them all again. Real zero-yield days (0.0) are in the data.
SOLAR_DAYS_AVAILABLE = {"value": 31}
SOLAR_YIELD_HISTORY_KWH = [
    {"value": 0.20999999344348907},  # History/Daily/0/Yield
    {"value": 0.18000000715255737},  # History/Daily/1/Yield
    {"value": 0.1899999976158142},  # History/Daily/2/Yield
    {"value": 0.14000000059604645},  # History/Daily/3/Yield
    {"value": 0.1599999964237213},  # History/Daily/4/Yield
    {"value": 0.12999999523162842},  # History/Daily/5/Yield
    {"value": 0.009999999776482582},  # History/Daily/6/Yield
    {"value": 0.0},  # History/Daily/7/Yield
    {"value": 0.0},  # History/Daily/8/Yield
    {"value": 0.0},  # History/Daily/9/Yield
    {"value": 0.03999999910593033},  # History/Daily/10/Yield
    {"value": 0.30000001192092896},  # History/Daily/11/Yield
    {"value": 0.27000001072883606},  # History/Daily/12/Yield
    {"value": 0.2199999988079071},  # History/Daily/13/Yield
    {"value": 0.20000000298023224},  # History/Daily/14/Yield
    {"value": 0.28999999165534973},  # History/Daily/15/Yield
    {"value": 0.25999999046325684},  # History/Daily/16/Yield
    {"value": 0.25999999046325684},  # History/Daily/17/Yield
    {"value": 0.17000000178813934},  # History/Daily/18/Yield
    {"value": 0.009999999776482582},  # History/Daily/19/Yield
    {"value": 0.0},  # History/Daily/20/Yield
    {"value": 0.0},  # History/Daily/21/Yield
    {"value": 0.0},  # History/Daily/22/Yield
    {"value": 0.0},  # History/Daily/23/Yield
    {"value": 0.0},  # History/Daily/24/Yield
    {"value": 0.0},  # History/Daily/25/Yield
    {"value": 0.0},  # History/Daily/26/Yield
    {"value": 0.0},  # History/Daily/27/Yield
    {"value": 0.0},  # History/Daily/28/Yield
    {"value": 0.0},  # History/Daily/29/Yield
    {"value": 0.0},  # History/Daily/30/Yield
]
