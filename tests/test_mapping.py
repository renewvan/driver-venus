"""Fixture-payload tests for the Venus OS -> renewvan bus mapping — no live
broker or GX device required.
"""

import pytest

from node_venus.mapping import (
    SolarYieldHistory,
    map_batteries,
    map_charge_state,
    map_service_message,
    split_service_topic,
)
from tests.fixtures import victron as fx


# --- batteries (system/0/Batteries aggregate) ---------------------------------


def test_smartshunt_publishes_core_fields_under_instance_id():
    pairs = dict(map_batteries(fx.BATTERIES_SMARTSHUNT))
    assert pairs["renewvan/battery/290/soc_pct"] == 99.30000305175781
    assert pairs["renewvan/battery/290/voltage_v"] == 13.4399995803833
    assert pairs["renewvan/battery/290/current_a"] == 0.6000000238418579
    assert pairs["renewvan/battery/290/power_w"] == 8.064000129699707


def test_shunt_without_temperature_probe_publishes_no_temperature():
    # A shunt with no probe has no temperature; the optional property must
    # be absent rather than published as null/zero.
    pairs = dict(map_batteries(fx.BATTERIES_SMARTSHUNT))
    assert "renewvan/battery/290/temperature_c" not in pairs


def test_each_battery_gets_its_own_id_and_probe_is_per_battery():
    pairs = dict(map_batteries(fx.BATTERIES_TWO_BANKS))
    assert pairs["renewvan/battery/290/temperature_c"] == 21.5
    assert pairs["renewvan/battery/512/soc_pct"] == 55.0
    assert "renewvan/battery/512/temperature_c" not in pairs


def test_battery_state_fields_are_never_published():
    pairs = dict(map_batteries(fx.BATTERIES_SMARTSHUNT))
    assert not any(t.endswith(("/state", "/name", "/id")) for t in pairs)


def test_battery_without_instance_is_skipped():
    assert map_batteries(fx.BATTERIES_NO_INSTANCE) == []


def test_empty_batteries_array_maps_to_nothing():
    assert map_batteries(fx.BATTERIES_EMPTY) == []


# --- system charge state ------------------------------------------------------


def test_charge_state_fans_out_to_every_known_battery_id():
    pairs = dict(map_charge_state(fx.SYSTEM_STATE_BULK, ["290", "512"]))
    assert pairs["renewvan/battery/290/charge_state"] == "bulk"
    assert pairs["renewvan/battery/512/charge_state"] == "bulk"


def test_charge_state_high_code():
    pairs = dict(map_charge_state(fx.SYSTEM_STATE_SCHEDULED_RECHARGE, ["290"]))
    assert pairs["renewvan/battery/290/charge_state"] == "scheduled_recharge"


def test_charge_state_unrecognized_code_is_unknown():
    pairs = dict(map_charge_state(fx.SYSTEM_STATE_UNRECOGNIZED_CODE, ["290"]))
    assert pairs["renewvan/battery/290/charge_state"] == "unknown"


def test_charge_state_null_clears_the_retained_topic():
    assert map_charge_state(fx.SYSTEM_STATE_NULL, ["290"]) == [
        ("renewvan/battery/290/charge_state", None)
    ]


def test_charge_state_with_no_known_batteries_publishes_nothing():
    assert map_charge_state(fx.SYSTEM_STATE_BULK, []) == []


# --- topic splitting ----------------------------------------------------------


def test_split_service_topic_extracts_service_instance_path():
    topic = "N/b827eb0cd27c/solarcharger/291/Dc/0/Voltage"
    assert split_service_topic(topic, "b827eb0cd27c") == ("solarcharger", "291", "Dc/0/Voltage")


def test_split_service_topic_rejects_other_portals_and_non_instances():
    assert split_service_topic("N/other/solarcharger/291/Pv/V", "b827eb0cd27c") is None
    # `system/0/Batteries`-style aggregates and heartbeat are not per-service
    # scalars: `heartbeat` has no instance segment.
    assert split_service_topic("N/b827eb0cd27c/heartbeat", "b827eb0cd27c") is None
    assert split_service_topic("N/b827eb0cd27c/solarcharger/x/Pv/V", "b827eb0cd27c") is None


# --- solar --------------------------------------------------------------------


def test_solar_power_and_voltages_map_under_instance_id():
    assert map_service_message("solarcharger", "291", "Yield/Power", fx.SOLAR_YIELD_POWER) == [
        ("renewvan/solar/291/power_w", 14.0)
    ]
    assert map_service_message("solarcharger", "291", "Pv/V", fx.SOLAR_PV_VOLTAGE) == [
        ("renewvan/solar/291/pv_voltage_v", 47.529998779296875)
    ]
    assert map_service_message("solarcharger", "291", "Dc/0/Voltage", fx.SOLAR_BATTERY_VOLTAGE) == [
        ("renewvan/solar/291/battery_voltage_v", 13.4399995803833)
    ]


def test_solar_yield_today_converts_kwh_to_wh():
    [(topic, value)] = map_service_message(
        "solarcharger", "291", "History/Daily/0/Yield", fx.SOLAR_YIELD_TODAY_KWH
    )
    assert topic == "renewvan/solar/291/yield_today_wh"
    assert value == 412.0


def test_solar_yield_today_has_no_float_noise():
    # Captured from a live GX: 0.12 kWh * 1000 is 119.99999731... in
    # floating point.
    [(_, value)] = map_service_message(
        "solarcharger", "291", "History/Daily/0/Yield", {"value": 0.11999999731779099}
    )
    assert value == 120.0


def test_solar_state_maps_to_charge_state():
    assert map_service_message("solarcharger", "291", "State", fx.SOLAR_STATE_BULK) == [
        ("renewvan/solar/291/charge_state", "bulk")
    ]


def test_solar_unrecognized_state_is_unknown():
    assert map_service_message("solarcharger", "291", "State", {"value": 9999}) == [
        ("renewvan/solar/291/charge_state", "unknown")
    ]


def test_solar_null_value_clears_the_retained_topic():
    assert map_service_message("solarcharger", "291", "Pv/V", {"value": None}) == [
        ("renewvan/solar/291/pv_voltage_v", None)
    ]


# --- charger (alternator / mains) ---------------------------------------------


def test_alternator_voltage_publishes_charger_voltage_and_source():
    pairs = dict(map_service_message("alternator", "288", "Dc/0/Voltage", fx.ALTERNATOR_VOLTAGE))
    assert pairs["renewvan/charger/288/voltage_v"] == 13.390000343322754
    assert pairs["renewvan/charger/288/source"] == "alternator"


def test_alternator_input_voltage():
    assert map_service_message("alternator", "288", "Dc/In/V", fx.ALTERNATOR_INPUT_VOLTAGE) == [
        ("renewvan/charger/288/input_voltage_v", 12.539999961853027)
    ]


def test_mains_charger_service_is_source_ac():
    pairs = dict(map_service_message("charger", "10", "Dc/0/Voltage", {"value": 14.4}))
    assert pairs["renewvan/charger/10/voltage_v"] == 14.4
    assert pairs["renewvan/charger/10/source"] == "ac"


def test_charger_current_does_not_republish_source():
    # `source` rides with voltage only, so it is not re-sent on every
    # current update.
    pairs = map_service_message("alternator", "288", "Dc/0/Current", {"value": 18.2})
    assert pairs == [("renewvan/charger/288/current_a", 18.2)]


def test_alternator_output_power():
    assert map_service_message("alternator", "288", "Dc/0/Power", fx.ALTERNATOR_POWER) == [
        ("renewvan/charger/288/power_w", 243.0)
    ]


def test_mains_charger_has_no_power_path():
    # Venus's `charger` class publishes AC input power (`Ac/In/L1/P`), not
    # the output power the schema's `power_w` means, so it must not be mapped.
    assert map_service_message("charger", "10", "Ac/In/L1/P", {"value": 180.0}) == []


@pytest.mark.parametrize(
    ("code", "stage"),
    [(246, "absorption"), (247, "equalize"), (248, "float"), (11, "unknown")],
)
def test_mains_charger_extended_state_codes(code, stage):
    # Phoenix/BlueSmart chargers report these beyond the basic 0-7 stages.
    assert map_service_message("charger", "10", "State", {"value": code}) == [
        ("renewvan/charger/10/charge_state", stage)
    ]


# --- per-battery extras -------------------------------------------------------


def test_time_since_full_charge_maps_to_battery_extra():
    assert map_service_message(
        "battery", "290", "History/TimeSinceLastFullCharge", fx.TIME_SINCE_FULL_CHARGE
    ) == [("renewvan/battery/290/time_since_full_charge_s", 168723)]


def test_time_to_go_maps_when_meaningful():
    assert map_service_message("battery", "290", "TimeToGo", fx.TIME_TO_GO) == [
        ("renewvan/battery/290/time_to_go_s", 98400.0)
    ]


def test_time_to_go_null_clears_the_topic():
    # Venus sends null when the device has no estimate; clear the retained topic.
    cleared = [("renewvan/battery/290/time_to_go_s", None)]
    assert map_service_message("battery", "290", "TimeToGo", fx.TIME_TO_GO_NULL) == cleared


def test_time_to_go_passes_venus_ten_day_cap_through():
    # Venus caps its estimate at ~864000 s and shows it as `9d 23h`; the hub reports the
    # same value rather than hiding it, so consumers match the Venus screen.
    assert map_service_message("battery", "290", "TimeToGo", fx.TIME_TO_GO_SENTINEL) == [
        ("renewvan/battery/290/time_to_go_s", 863999.9375)
    ]


# --- everything else is ignored -----------------------------------------------


def test_unmapped_service_or_path_maps_to_nothing():
    assert map_service_message("solarcharger", "291", "Pv/Unknown", {"value": 1}) == []
    assert map_service_message("vebus", "276", "Dc/0/Voltage", {"value": 13.0}) == []
    assert map_service_message("logger", "0", "Buffer/FreeDiskSpace", {"value": 1}) == []


# --- Solar daily history -> `yield_history_wh` (docs/adr/0009) -----------

HISTORY_TOPIC = "renewvan/solar/291/yield_history_wh"


def _record(history, messages, instance="291"):
    """Record `(path, payload)` pairs without flushing, like a burst of
    Venus slot messages arriving before the quiet period ends."""
    for path, payload in messages:
        history.handle("solarcharger", instance, path, payload)


def _captured_messages():
    days = [("History/Overall/DaysAvailable", fx.SOLAR_DAYS_AVAILABLE)]
    slots = [
        (f"History/Daily/{n}/Yield", payload)
        for n, payload in enumerate(fx.SOLAR_YIELD_HISTORY_KWH)
    ]
    return days + slots


def test_solar_history_flushes_one_array_newest_first_in_wh():
    history = SolarYieldHistory()
    _record(history, _captured_messages())

    [(topic, array)] = history.flush()

    assert topic == HISTORY_TOPIC
    assert len(array) == 31
    # Captured: today 0.21 kWh, yesterday 0.18, then 0.19 ... (no float noise).
    assert array[:4] == [210.0, 180.0, 190.0, 140.0]
    # A real dark day stays 0 (the controller logged it), not None.
    assert array[7] == 0.0


def test_solar_history_recording_publishes_nothing_by_itself():
    history = SolarYieldHistory()
    assert history.handle("solarcharger", "291", "History/Daily/0/Yield", {"value": 0.21}) is True


def test_solar_history_never_flushes_a_half_filled_array():
    history = SolarYieldHistory()
    _record(history, _captured_messages()[:-1])  # all but the last slot
    assert history.flush() == []

    _record(history, _captured_messages()[-1:])
    assert len(history.flush()) == 1


def test_solar_history_waits_for_days_available_whatever_the_arrival_order():
    history = SolarYieldHistory()
    messages = _captured_messages()
    _record(history, messages[1:] + messages[:1])  # slots first, DaysAvailable last
    assert [topic for topic, _ in history.flush()] == [HISTORY_TOPIC]


def test_solar_history_keepalive_resend_does_not_republish():
    history = SolarYieldHistory()
    _record(history, _captured_messages())
    assert len(history.flush()) == 1

    # Venus re-sends every slot on the next keepalive: nothing changed.
    _record(history, _captured_messages())
    assert history.flush() == []


def test_solar_history_null_slot_is_a_gap_not_zero():
    history = SolarYieldHistory()
    messages = _captured_messages()
    messages[1 + 5] = ("History/Daily/5/Yield", {"value": None})
    _record(history, messages)

    [(_, array)] = history.flush()

    assert array[5] is None
    assert array[4] == 160.0 and array[6] == 10.0


def test_solar_history_day_rollover_flushes_one_consistent_shifted_array():
    history = SolarYieldHistory()
    _record(history, _captured_messages())
    [(_, before)] = history.flush()

    # Midnight: every slot shifts one place and today starts at 0. The whole
    # burst is recorded, then flushed once: a consumer sees the old array and
    # then the new one, never a mix of the two.
    shifted = [{"value": 0.0}] + fx.SOLAR_YIELD_HISTORY_KWH[:-1]
    _record(history, [(f"History/Daily/{n}/Yield", p) for n, p in enumerate(shifted)])

    assert history.flush() == [(HISTORY_TOPIC, [0.0] + before[:-1])]


def test_solar_history_short_history_for_a_young_controller():
    history = SolarYieldHistory()
    _record(
        history,
        [
            ("History/Overall/DaysAvailable", {"value": 3}),
            ("History/Daily/0/Yield", {"value": 0.21}),
            ("History/Daily/1/Yield", {"value": 0.18}),
            ("History/Daily/2/Yield", {"value": 0.19}),
            # Venus can still send a slot beyond DaysAvailable: it is not history.
            ("History/Daily/3/Yield", {"value": 9.99}),
        ],
    )
    assert history.flush() == [(HISTORY_TOPIC, [210.0, 180.0, 190.0])]


def test_solar_history_keeps_controllers_apart():
    history = SolarYieldHistory()
    _record(history, _captured_messages(), instance="291")
    _record(
        history,
        [
            ("History/Overall/DaysAvailable", {"value": 1}),
            ("History/Daily/0/Yield", {"value": 0.5}),
        ],
        instance="292",
    )
    flushed = dict(history.flush())
    assert set(flushed) == {HISTORY_TOPIC, "renewvan/solar/292/yield_history_wh"}
    assert flushed["renewvan/solar/292/yield_history_wh"] == [500.0]
    assert len(flushed[HISTORY_TOPIC]) == 31


def test_solar_history_ignores_other_services_and_paths():
    history = SolarYieldHistory()
    assert history.handle("battery", "290", "History/Daily/0/Yield", {"value": 1.0}) is False
    other_path = "History/Daily/0/MaxPower"
    assert history.handle("solarcharger", "291", other_path, {"value": 1.0}) is False
    assert history.handle("solarcharger", "291", "Yield/Power", {"value": 14.0}) is False
    assert history.flush() == []


def test_solar_yield_today_still_maps_from_the_captured_slot_zero():
    [(topic, value)] = map_service_message(
        "solarcharger", "291", "History/Daily/0/Yield", fx.SOLAR_YIELD_HISTORY_KWH[0]
    )
    assert (topic, value) == ("renewvan/solar/291/yield_today_wh", 210.0)
