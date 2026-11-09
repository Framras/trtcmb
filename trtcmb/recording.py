from datetime import date
from typing import NamedTuple

from frappe.utils import flt, getdate

from trtcmb.dates import calendar_days

FIRST_WORKING_DAY = "First Working Day"
IMMEDIATE_DAY = "Immediate Day"


class AnnouncedRate(NamedTuple):
    announced_on: date
    rates: dict


class RecordingRule:
    """Shared EVDS placement; subclasses only decide how empty days are filled."""

    name: str

    def fill_empty(
        self,
        recorded: dict[date, dict],
        series_names: set[str],
        save_from: date,
        save_until: date,
        *,
        seed_before: dict[str, float],
        seed_after: dict[str, float],
    ) -> None:
        """Fill days with no EVDS rate. Immediate Day leaves gaps for the bulletin layer."""
        return None

    def rates(
        self, announcements: list[AnnouncedRate], save_from, save_until
    ) -> list[tuple[date, dict]]:
        save_from = getdate(save_from)
        save_until = getdate(save_until)
        recorded, series_names, seed_before, seed_after = place_announced_rates(
            announcements, save_from, save_until
        )
        self.fill_empty(
            recorded,
            series_names,
            save_from,
            save_until,
            seed_before=seed_before,
            seed_after=seed_after,
        )
        return [(day, recorded[day]) for day in sorted(recorded)]


class FirstWorkingDay(RecordingRule):
    """EVDS days keep their rate. Empty days use the previous non-empty EVDS rate."""

    name = FIRST_WORKING_DAY

    def fill_empty(
        self,
        recorded: dict[date, dict],
        series_names: set[str],
        save_from: date,
        save_until: date,
        *,
        seed_before: dict[str, float],
        seed_after: dict[str, float],
    ) -> None:
        fill_forward(recorded, series_names, save_from, save_until, seed_before=seed_before)


class ImmediateDay(RecordingRule):
    """EVDS days keep their rate. Empty days are filled from the TCMB bulletin."""

    name = IMMEDIATE_DAY


RECORDING_RULES: dict[str, RecordingRule] = {
    rule.name: rule for rule in (FirstWorkingDay(), ImmediateDay())
}


def normalize_recording_rule(value: str | None) -> str:
    if value in RECORDING_RULES:
        return value
    return FIRST_WORKING_DAY


def rates_for_rule(rule_name: str | None, announcements: list[AnnouncedRate], save_from, save_until):
    return RECORDING_RULES[normalize_recording_rule(rule_name)].rates(announcements, save_from, save_until)


def first_working_day_rates(announcements: list[AnnouncedRate], save_from, save_until):
    return RECORDING_RULES[FIRST_WORKING_DAY].rates(announcements, save_from, save_until)


def immediate_day_rates(announcements: list[AnnouncedRate], save_from, save_until):
    return RECORDING_RULES[IMMEDIATE_DAY].rates(announcements, save_from, save_until)


def place_announced_rates(
    announcements: list[AnnouncedRate], save_from, save_until
) -> tuple[dict[date, dict], set[str], dict[str, float], dict[str, float]]:
    """Keep every EVDS rate on the day it was returned. Shared by all strategies."""
    save_from = getdate(save_from)
    save_until = getdate(save_until)
    recorded: dict[date, dict] = {}
    series_names: set[str] = set()
    seed_before: dict[str, float] = {}
    seed_after: dict[str, float] = {}
    for series, points in _series_points(announcements).items():
        series_names.add(series)
        for announced_on, rate in points:
            if save_from <= announced_on <= save_until:
                recorded.setdefault(announced_on, {})[series] = rate
            elif announced_on < save_from:
                seed_before[series] = rate
            elif series not in seed_after:
                seed_after[series] = rate
    return recorded, series_names, seed_before, seed_after


def fill_forward(
    recorded: dict[date, dict],
    series_names: set[str],
    save_from: date,
    save_until: date,
    *,
    seed_before: dict[str, float] | None = None,
) -> None:
    """Empty day <- previous EVDS rate."""
    seed_before = seed_before or {}
    for series in series_names:
        previous = seed_before.get(series)
        for day in calendar_days(save_from, save_until):
            if series in recorded.get(day, {}):
                previous = recorded[day][series]
            elif previous is not None:
                recorded.setdefault(day, {})[series] = previous


def _series_points(announcements: list[AnnouncedRate]) -> dict[str, list[tuple[date, float]]]:
    points_by_series: dict[str, list[tuple[date, float]]] = {}
    for item in announcements:
        announced_on = getdate(item.announced_on)
        for series, rate in item.rates.items():
            numeric = flt(rate)
            if numeric <= 0:
                continue
            points_by_series.setdefault(series, []).append((announced_on, numeric))
    for points in points_by_series.values():
        points.sort(key=lambda point: point[0])
    return points_by_series
