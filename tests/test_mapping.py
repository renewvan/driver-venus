"""Fixture-payload tests for the Venus OS -> renewvan bus mapping — no live
broker or GX device required.
"""

import json
from pathlib import Path

import pytest

from driver_venus.mapping import (
    BatteryBms,
    BatteryFuelGauge,
    InstanceIdentity,
    SolarYieldHistory,
    map_batteries,
    map_charge_state,
    map_service_message,
    split_service_topic,
)
from tests.fixtures import victron as fx

CAPTURE = Path(__file__).parent / "fixtures" / "venus_capture_2026-10-16.json"


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


# --- battery fuel gauge -> capacity_ah / remaining_ah ------------------------

CAPACITY_TOPIC = "renewvan/battery/290/capacity_ah"
REMAINING_TOPIC = "renewvan/battery/290/remaining_ah"


def test_fuel_gauge_publishes_capacity_and_remaining_from_consumed_ah():
    gauge = BatteryFuelGauge()
    assert gauge.handle("battery", "290", "Capacity", fx.CAPACITY) == [(CAPACITY_TOPIC, 314.0)]
    # 314.0 + -24.8, without float noise.
    assert gauge.handle("battery", "290", "ConsumedAmphours", fx.CONSUMED_AMPHOURS) == [
        (REMAINING_TOPIC, 289.2)
    ]


def test_fuel_gauge_waits_for_both_paths_whatever_the_arrival_order():
    gauge = BatteryFuelGauge()
    assert gauge.handle("battery", "290", "ConsumedAmphours", fx.CONSUMED_AMPHOURS) == []
    assert gauge.handle("battery", "290", "Capacity", fx.CAPACITY) == [
        (CAPACITY_TOPIC, 314.0),
        (REMAINING_TOPIC, 289.2),
    ]


def test_fuel_gauge_null_consumed_clears_remaining_but_keeps_capacity():
    gauge = BatteryFuelGauge()
    gauge.handle("battery", "290", "Capacity", fx.CAPACITY)
    gauge.handle("battery", "290", "ConsumedAmphours", fx.CONSUMED_AMPHOURS)
    assert gauge.handle("battery", "290", "ConsumedAmphours", {"value": None}) == [
        (REMAINING_TOPIC, None)
    ]
    # Already cleared: a second null says nothing more.
    assert gauge.handle("battery", "290", "ConsumedAmphours", {"value": None}) == []


def test_fuel_gauge_null_capacity_clears_both():
    gauge = BatteryFuelGauge()
    gauge.handle("battery", "290", "Capacity", fx.CAPACITY)
    gauge.handle("battery", "290", "ConsumedAmphours", fx.CONSUMED_AMPHOURS)
    assert gauge.handle("battery", "290", "Capacity", {"value": None}) == [
        (CAPACITY_TOPIC, None),
        (REMAINING_TOPIC, None),
    ]


def test_fuel_gauge_remaining_never_goes_below_zero():
    gauge = BatteryFuelGauge()
    gauge.handle("battery", "290", "Capacity", {"value": 100.0})
    assert gauge.handle("battery", "290", "ConsumedAmphours", {"value": -120.0}) == [
        (REMAINING_TOPIC, 0.0)
    ]


def test_fuel_gauge_skips_a_service_that_reports_installed_capacity():
    # Such a service may use `Capacity` for the remaining Ah: publish neither,
    # and clear what an earlier message already put out.
    gauge = BatteryFuelGauge()
    gauge.handle("battery", "512", "Capacity", {"value": 250.0})
    assert gauge.handle("battery", "512", "InstalledCapacity", {"value": 280.0}) == [
        ("renewvan/battery/512/capacity_ah", None),
        ("renewvan/battery/512/remaining_ah", None),
    ]
    assert gauge.handle("battery", "512", "Capacity", {"value": 250.0}) == []
    assert gauge.handle("battery", "512", "ConsumedAmphours", {"value": -30.0}) == []


def test_fuel_gauge_ignores_other_services_and_paths():
    gauge = BatteryFuelGauge()
    assert gauge.handle("solarcharger", "291", "Capacity", fx.CAPACITY) == []
    assert gauge.handle("battery", "290", "Soc", {"value": 92.6}) == []


# --- BMS limits, cell extremes, allow flags (stateless) ----------------------


@pytest.mark.parametrize(
    "path, prop, value",
    [
        ("Info/MaxChargeVoltage", "charge_voltage_limit_v", 14.2),
        ("Info/MaxChargeCurrent", "charge_current_limit_a", 50.0),
        ("Info/MaxDischargeCurrent", "discharge_current_limit_a", 100.0),
        ("System/MaxCellVoltage", "cell_voltage_max_v", 3.335),
        ("System/MinCellVoltage", "cell_voltage_min_v", 3.329),
        ("Voltages/Diff", "cell_voltage_delta_v", 0.006),
        ("Cell/Diff", "cell_voltage_delta_v", 0.006),
    ],
)
def test_bms_scalars_map_straight_through(path, prop, value):
    payload = {"value": value}
    assert map_service_message("battery", "512", path, payload) == [
        (f"renewvan/battery/512/{prop}", value)
    ]
    assert map_service_message("battery", "512", path, {"value": None}) == [
        (f"renewvan/battery/512/{prop}", None)
    ]


def test_bms_scalars_come_from_the_fixture_unchanged():
    published = {}
    for path, payload in fx.BMS_FORMAT_1.items():
        published.update(map_service_message("battery", "512", path, payload))
    assert published["renewvan/battery/512/charge_voltage_limit_v"] == 14.2
    assert published["renewvan/battery/512/cell_voltage_max_v"] == 3.335
    assert published["renewvan/battery/512/cell_voltage_min_v"] == 3.329
    assert published["renewvan/battery/512/cell_voltage_delta_v"] == 0.006
    # Cell ids, the sum and the probe names have no schema property.
    assert not any("cell_id" in t or "sum" in t for t in published)


def test_allow_flags_publish_booleans_and_unknown_is_false():
    assert map_service_message("battery", "512", "Io/AllowToCharge", {"value": 1}) == [
        ("renewvan/battery/512/allow_charge", True)
    ]
    # Venus reads an unknown FET state as 0 (it never sends null): published as false.
    assert map_service_message("battery", "512", "Io/AllowToDischarge", {"value": 0}) == [
        ("renewvan/battery/512/allow_discharge", False)
    ]


def test_allow_flag_null_clears_and_junk_publishes_nothing():
    assert map_service_message("battery", "512", "Io/AllowToCharge", {"value": None}) == [
        ("renewvan/battery/512/allow_charge", None)
    ]
    assert map_service_message("battery", "512", "Io/AllowToCharge", {"value": 7}) == []
    assert map_service_message("battery", "512", "Io/AllowToCharge", {"value": "on"}) == []


def test_allow_to_balance_and_heat_are_ignored():
    assert map_service_message("battery", "512", "Io/AllowToBalance", {"value": 1}) == []
    assert map_service_message("battery", "512", "Io/AllowToHeat", {"value": 1}) == []


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


def test_solar_history_handle_reports_history_messages_so_a_flush_gets_scheduled():
    history = SolarYieldHistory()
    assert history.handle("solarcharger", "291", "History/Daily/0/Yield", {"value": 0.21}) is True
    assert history.handle("solarcharger", "291", "Yield/Power", {"value": 14.0}) is False


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


def test_solar_history_stalled_rollover_burst_waits_instead_of_mixing_old_and_new():
    history = SolarYieldHistory()
    _record(history, _captured_messages())
    [(_, before)] = history.flush()

    # Midnight, but the burst stalls after two slots and a flush fires.
    shifted = [{"value": 0.0}] + fx.SOLAR_YIELD_HISTORY_KWH[:-1]
    messages = [(f"History/Daily/{n}/Yield", p) for n, p in enumerate(shifted)]
    _record(history, messages[:2])
    assert history.flush() == []  # not [new, new, old, old, ...]

    # The rest of the burst arrives: now the whole new array goes out at once.
    _record(history, messages[2:])
    assert history.flush() == [(HISTORY_TOPIC, [0.0] + before[:-1])]


def test_solar_history_days_available_zero_publishes_no_history():
    history = SolarYieldHistory()
    _record(history, [("History/Overall/DaysAvailable", {"value": 0})])
    assert history.flush() == []


def test_solar_history_negative_yield_is_no_data_not_a_negative_bar():
    history = SolarYieldHistory()
    _record(
        history,
        [
            ("History/Overall/DaysAvailable", {"value": 2}),
            ("History/Daily/0/Yield", {"value": 0.21}),
            ("History/Daily/1/Yield", {"value": -0.5}),
        ],
    )
    assert history.flush() == [(HISTORY_TOPIC, [210.0, None])]


def test_solar_history_shrinking_days_available_drops_the_oldest_slots():
    history = SolarYieldHistory()
    _record(history, _captured_messages())
    history.flush()

    _record(history, [("History/Overall/DaysAvailable", {"value": 3})])
    _record(history, _captured_messages()[1:])  # keepalive re-send of every slot
    [(_, array)] = history.flush()
    assert array == [210.0, 180.0, 190.0]


# --- instance identity: `driver` and `name` -----------------------------------


def test_first_sight_of_an_instance_names_its_driver():
    identity = InstanceIdentity()
    pairs = map_batteries(fx.BATTERIES_TWO_BANKS)
    assert identity.driver_pairs(pairs) == [
        ("renewvan/battery/290/driver", "venus"),
        ("renewvan/battery/512/driver", "venus"),
    ]


def test_driver_is_published_once_per_instance_not_per_message():
    identity = InstanceIdentity()
    pairs = map_batteries(fx.BATTERIES_SMARTSHUNT)
    identity.driver_pairs(pairs)
    assert identity.driver_pairs(pairs) == []
    # another property of the same instance is not a new instance
    assert identity.driver_pairs([("renewvan/battery/290/charge_state", "bulk")]) == []


def test_each_entity_type_gets_its_driver():
    identity = InstanceIdentity()
    pairs = [
        ("renewvan/solar/291/power_w", 14.0),
        ("renewvan/charger/289/voltage_v", 13.2),
        ("renewvan/charger/289/source", "ac"),
    ]
    assert identity.driver_pairs(pairs) == [
        ("renewvan/solar/291/driver", "venus"),
        ("renewvan/charger/289/driver", "venus"),
    ]


def _label(identity: InstanceIdentity, service: str, instance: str, path: str, value):
    return identity.label_pairs(service, instance, path, {"value": value})


def test_custom_name_is_the_instance_name():
    identity = InstanceIdentity()
    assert _label(identity, "battery", "290", "CustomName", "Van") == [
        ("renewvan/battery/290/name", "Van")
    ]


def test_product_name_is_the_name_when_there_is_no_custom_name():
    identity = InstanceIdentity()
    assert _label(identity, "solarcharger", "291", "ProductName", "SmartSolar MPPT") == [
        ("renewvan/solar/291/name", "SmartSolar MPPT")
    ]


def test_custom_name_wins_over_product_name_in_either_order():
    for first, second in (("CustomName", "ProductName"), ("ProductName", "CustomName")):
        identity = InstanceIdentity()
        values = {"CustomName": "Van", "ProductName": "SmartShunt"}
        _label(identity, "battery", "290", first, values[first])
        _label(identity, "battery", "290", second, values[second])
        assert _label(identity, "battery", "290", "CustomName", "Van") == []
        assert identity._names[("battery", "290")] == "Van"


def test_empty_custom_name_falls_back_to_product_name():
    identity = InstanceIdentity()
    _label(identity, "charger", "289", "ProductName", "Blue Smart IP22")
    assert _label(identity, "charger", "289", "CustomName", "  ") == []
    assert identity._names[("charger", "289")] == "Blue Smart IP22"


def test_name_is_cleared_when_venus_stops_providing_a_label():
    identity = InstanceIdentity()
    _label(identity, "battery", "290", "CustomName", "Van")
    assert _label(identity, "battery", "290", "CustomName", None) == [
        ("renewvan/battery/290/name", None)
    ]


def test_name_falls_back_to_product_name_when_custom_name_is_removed():
    identity = InstanceIdentity()
    _label(identity, "battery", "290", "ProductName", "SmartShunt")
    _label(identity, "battery", "290", "CustomName", "Van")
    assert _label(identity, "battery", "290", "CustomName", None) == [
        ("renewvan/battery/290/name", "SmartShunt")
    ]


def test_a_stale_retained_name_is_cleared_by_the_first_null_label():
    identity = InstanceIdentity()
    assert _label(identity, "battery", "290", "ProductName", None) == [
        ("renewvan/battery/290/name", None)
    ]


def test_unchanged_label_is_not_republished_on_keepalive_resend():
    identity = InstanceIdentity()
    _label(identity, "battery", "290", "CustomName", "Van")
    assert _label(identity, "battery", "290", "CustomName", "Van") == []
    _label(identity, "battery", "290", "CustomName", None)
    assert _label(identity, "battery", "290", "CustomName", None) == []


def test_non_string_label_is_not_a_name():
    identity = InstanceIdentity()
    assert _label(identity, "battery", "290", "CustomName", 5) == [
        ("renewvan/battery/290/name", None)
    ]


def test_alternator_and_charger_labels_name_charger_instances():
    identity = InstanceIdentity()
    assert _label(identity, "alternator", "277", "CustomName", "Orion") == [
        ("renewvan/charger/277/name", "Orion")
    ]
    assert _label(identity, "charger", "289", "CustomName", "Blue Smart") == [
        ("renewvan/charger/289/name", "Blue Smart")
    ]


def test_non_label_paths_and_other_services_produce_no_name():
    identity = InstanceIdentity()
    assert _label(identity, "battery", "290", "Devices/0/CustomName", "Van") == []
    assert _label(identity, "vebus", "276", "CustomName", "Multi") == []
    assert _label(identity, "battery", "290", "Soc", 80) == []


# --- BMS arrays -> cell_voltages_v, cell_balancing, temperatures_c, protections ---

BMS_ID = "512"


def _bms(messages, bms=None, instance=BMS_ID):
    """A `BatteryBms` that has been sent `{path: payload}` and flushed once, as
    after a quiet period; returns `(bms, {property: array})`."""
    bms = bms or BatteryBms()
    for path, payload in messages.items():
        bms.handle("battery", instance, path, payload)
    return bms, _flushed(bms)


def _flushed(bms):
    return {topic.rsplit("/", 1)[1]: array for topic, array in bms.flush()}


def test_bms_format_1_publishes_every_array():
    _, out = _bms(fx.BMS_FORMAT_1 | fx.BMS_ALARMS_OK)
    assert out == {
        "cell_voltages_v": [3.331, 3.329, 3.335, 3.33],
        "cell_balancing": [False, True, False, False],
        # Probes 1-4 then the MOSFET: a probe the BMS lacks is null, keeping its index.
        "temperatures_c": [21.5, 22.0, None, None, 27.4],
        "protections": [],
    }


def test_bms_topics_are_under_the_instance():
    bms = BatteryBms()
    bms.handle("battery", BMS_ID, "Voltages/Cell1", {"value": 3.3})
    assert bms.flush() == [("renewvan/battery/512/cell_voltages_v", [3.3])]


def test_bms_format_2_has_voltages_and_no_balancing():
    _, out = _bms(fx.BMS_FORMAT_2)
    assert out == {"cell_voltages_v": [3.331, 3.329, 3.335, 3.33]}


def test_bms_format_3_carries_each_cell_once():
    both = fx.BMS_FORMAT_1 | fx.BMS_FORMAT_2
    _, out = _bms(both)
    assert out["cell_voltages_v"] == [3.331, 3.329, 3.335, 3.33]
    assert out["cell_balancing"] == [False, True, False, False]


def test_bms_publishes_nothing_until_flushed_and_then_once():
    bms = BatteryBms()
    for path, payload in fx.BMS_FORMAT_1.items():
        bms.handle("battery", BMS_ID, path, payload)
    assert len(bms.flush()) == 3  # cells, balancing, temperatures
    assert bms.flush() == []


def test_bms_handle_reports_only_bms_paths():
    bms = BatteryBms()
    assert bms.handle("battery", BMS_ID, "Voltages/Cell1", {"value": 3.3})
    assert bms.handle("battery", BMS_ID, "Balances/Cell1", {"value": 0})
    assert bms.handle("battery", BMS_ID, "System/MOSTemperature", {"value": 20.0})
    assert bms.handle("battery", BMS_ID, "Alarms/HighVoltage", {"value": 0})
    for path in ("Soc", "Dc/0/Voltage", "Voltages/Sum", "System/MaxCellVoltage", "Alarms/LowSoc"):
        assert not bms.handle("battery", BMS_ID, path, {"value": 1})
    assert not bms.handle("solarcharger", "291", "Voltages/Cell1", {"value": 3.3})
    assert not bms.handle("battery", BMS_ID, "Voltages/Cell33", {"value": 3.3})
    assert not bms.handle("battery", BMS_ID, "Voltages/Cell0", {"value": 3.3})


def test_bms_cell_arrays_arrive_in_any_order():
    reversed_ = dict(reversed(list(fx.BMS_FORMAT_1.items())))
    _, out = _bms(reversed_)
    assert out["cell_voltages_v"] == [3.331, 3.329, 3.335, 3.33]
    assert out["cell_balancing"] == [False, True, False, False]


def test_bms_null_cell_is_a_null_slot_never_zero():
    messages = dict(fx.BMS_FORMAT_1) | {"Voltages/Cell3": {"value": None}}
    _, out = _bms(messages)
    assert out["cell_voltages_v"] == [3.331, 3.329, None, 3.33]
    assert len(out["cell_balancing"]) == 4


@pytest.mark.parametrize("bad", [-0.1, "3.3", True])
def test_bms_unreadable_cell_reading_is_a_null_slot(bad):
    _, out = _bms({"Voltages/Cell1": {"value": 3.3}, "Voltages/Cell2": {"value": bad}})
    assert out["cell_voltages_v"] == [3.3, None]


def test_bms_cell_never_received_below_the_last_is_null():
    _, out = _bms({"Voltages/Cell1": {"value": 3.3}, "Voltages/Cell3": {"value": 3.4}})
    assert out["cell_voltages_v"] == [3.3, None, 3.4]


def test_bms_all_cells_null_publishes_no_array():
    _, out = _bms({f"Voltages/Cell{n}": {"value": None} for n in range(1, 5)})
    assert out == {}


def test_bms_balancing_needs_cell_voltages_and_a_known_balance():
    _, out = _bms({"Balances/Cell1": {"value": 1}, "Balances/Cell2": {"value": 0}})
    assert out == {}
    _, out = _bms(
        {
            "Voltages/Cell1": {"value": 3.3},
            "Voltages/Cell2": {"value": 3.3},
            "Balances/Cell1": {"value": None},
            "Balances/Cell2": {"value": None},
        }
    )
    assert out == {"cell_voltages_v": [3.3, 3.3]}


def test_bms_balancing_is_never_padded_or_truncated():
    messages = {f"Voltages/Cell{n}": {"value": 3.3} for n in range(1, 5)}
    messages["Balances/Cell1"] = {"value": 1}
    messages["Balances/Cell7"] = {"value": 1}  # beyond the cells the BMS reports volts for
    _, out = _bms(messages)
    assert out["cell_balancing"] == [True, None, None, None]


def test_bms_cell_count_change_replaces_both_arrays_in_one_flush():
    bms, first = _bms(fx.BMS_FORMAT_1)
    assert len(first["cell_voltages_v"]) == len(first["cell_balancing"]) == 4
    more = {
        f"{kind}{n}": {"value": 3.3 if kind == "Voltages/Cell" else 0}
        for n in (5, 6, 7, 8)
        for kind in ("Voltages/Cell", "Balances/Cell")
    }
    _, second = _bms(more, bms)
    assert len(second["cell_voltages_v"]) == len(second["cell_balancing"]) == 8


def test_bms_unchanged_arrays_are_not_republished():
    bms, _ = _bms(fx.BMS_FORMAT_1 | fx.BMS_ALARMS_OK)
    # A keepalive: Venus re-sends everything.
    assert _bms(fx.BMS_FORMAT_1 | fx.BMS_ALARMS_OK, bms)[1] == {}
    _, out = _bms({"Voltages/Cell1": {"value": 3.4}}, bms)
    assert out == {"cell_voltages_v": [3.4, 3.329, 3.335, 3.33]}


def test_bms_instances_are_kept_apart():
    bms = BatteryBms()
    bms.handle("battery", "512", "Voltages/Cell1", {"value": 3.3})
    bms.handle("battery", "513", "Voltages/Cell1", {"value": 3.4})
    assert dict(bms.flush()) == {
        "renewvan/battery/512/cell_voltages_v": [3.3],
        "renewvan/battery/513/cell_voltages_v": [3.4],
    }


def test_bms_array_that_loses_all_its_data_is_cleared():
    bms, _ = _bms(fx.BMS_FORMAT_1)
    nulls = {path: {"value": None} for path in fx.BMS_FORMAT_1}
    assert dict(_pairs(bms, nulls)) == {
        "renewvan/battery/512/cell_voltages_v": None,
        "renewvan/battery/512/cell_balancing": None,
        "renewvan/battery/512/temperatures_c": None,
    }


def _pairs(bms, messages):
    for path, payload in messages.items():
        bms.handle("battery", BMS_ID, path, payload)
    return bms.flush()


def test_bms_temperatures_run_through_the_last_probe_seen():
    _, out = _bms({"System/Temperature1": {"value": 20.0}})
    assert out == {"temperatures_c": [20.0]}
    _, out = _bms({"System/MOSTemperature": {"value": 30.0}})
    assert out == {"temperatures_c": [None, None, None, None, 30.0]}


def test_bms_temperatures_keep_negative_readings():
    _, out = _bms({"System/Temperature1": {"value": -4.5}, "System/Temperature2": {"value": 0.0}})
    assert out == {"temperatures_c": [-4.5, 0.0]}


def test_bms_all_probes_null_publishes_no_array():
    _, out = _bms(
        {"System/Temperature1": {"value": None}, "System/MOSTemperature": {"value": None}}
    )
    assert out == {}


# --- protections ---------------------------------------------------------------


def _alarms(**levels):
    return {f"Alarms/{name}": {"value": level} for name, level in levels.items()}


def test_protections_only_alarm_level_two_is_active():
    _, out = _bms(_alarms(HighCellVoltage=2, LowCellVoltage=1, HighVoltage=0))
    assert out == {"protections": ["cell_overvoltage"]}


def test_protections_come_out_in_vocabulary_order_without_duplicates():
    # `HighTemperature` and `LowVoltage` arrive before the cell alarms; a second
    # alarm that maps to nothing new adds nothing.
    _, out = _bms(
        _alarms(HighTemperature=2, LowVoltage=2, LowCellVoltage=2, HighCellVoltage=2, HighVoltage=2)
    )
    assert out == {
        "protections": [
            "cell_overvoltage",
            "cell_undervoltage",
            "pack_overvoltage",
            "pack_undervoltage",
            "overtemperature",
        ]
    }


@pytest.mark.parametrize(
    "alarm, name",
    [
        ("HighCellVoltage", "cell_overvoltage"),
        ("LowCellVoltage", "cell_undervoltage"),
        ("HighVoltage", "pack_overvoltage"),
        ("LowVoltage", "pack_undervoltage"),
        ("HighChargeTemperature", "charge_overtemperature"),
        ("LowChargeTemperature", "charge_undertemperature"),
        ("HighChargeCurrent", "charge_overcurrent"),
        ("HighDischargeCurrent", "discharge_overcurrent"),
        ("InternalFailure", "internal_fault"),
        ("CellImbalance", "cell_imbalance"),
        ("HighTemperature", "overtemperature"),
        ("LowTemperature", "undertemperature"),
    ],
)
def test_protections_map_each_alarm_by_name(alarm, name):
    _, out = _bms(_alarms(**{alarm: 2}))
    assert out == {"protections": [name]}


def test_protections_unmapped_alarm_is_other_and_logged(caplog):
    with caplog.at_level("WARNING"):
        _, out = _bms(_alarms(HighInternalTemperature=2, MidVoltage=2, Contactor=2))
    assert out == {"protections": ["other"]}
    assert "HighInternalTemperature" in caplog.text


def test_protections_ignored_alarms_are_neither_other_nor_reported():
    _, out = _bms(_alarms(LowSoc=2, BmsCable=2, FuseBlown=2, StateOfHealth=2))
    assert out == {}
    _, out = _bms(_alarms(LowSoc=2, BmsCable=2, FuseBlown=2) | _alarms(HighVoltage=0))
    assert out == {"protections": []}


def test_protections_empty_means_reported_and_none_active():
    _, out = _bms(fx.BMS_ALARMS_OK)
    assert out == {"protections": []}


def test_protections_all_null_alarms_leave_the_property_absent():
    _, out = _bms(_alarms(HighVoltage=None, LowVoltage=None, Alarm=None))
    assert out == {}


def test_protections_one_reported_alarm_is_enough_to_publish():
    _, out = _bms(_alarms(HighVoltage=None, LowVoltage=0))
    assert out == {"protections": []}


def test_protections_update_and_clear():
    bms, out = _bms(fx.BMS_ALARMS_OK)
    assert out == {"protections": []}
    assert _bms(_alarms(LowCellVoltage=2), bms)[1] == {"protections": ["cell_undervoltage"]}
    assert _bms(_alarms(LowCellVoltage=1), bms)[1] == {"protections": []}
    nulls = {path: {"value": None} for path in fx.BMS_ALARMS_OK}
    assert _bms(nulls, bms)[1] == {"protections": None}


def test_the_smartshunt_capture_has_no_cells_probes_limits_or_flags():
    bms = BatteryBms()
    stateless = {}
    for topic, payload in json.loads(CAPTURE.read_text()).items():
        parsed = split_service_topic(topic, "PORTAL")
        if parsed is not None:
            bms.handle(*parsed, payload)
            stateless.update(map_service_message(*parsed, payload))
    props = {t.rsplit("/", 1)[1] for t in stateless}
    assert not props & {"allow_charge", "allow_discharge", "cell_voltage_max_v"}
    assert not any(p.endswith("_limit_v") or p.endswith("_limit_a") for p in props)
    # Its alarms all read OK, which is a source that reports protections with none active.
    assert _flushed(bms) == {"protections": []}
