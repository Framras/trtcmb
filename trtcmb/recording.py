from datetime import date
from typing import NamedTuple

from frappe.utils import add_days, flt, getdate

from trtcmb.dates import calendar_days

FIRST_WORKING_DAY = "First Working Day"
IMMEDIATE_DAY = "Immediate Day"


class AnnouncedRate(NamedTuple):
    announced_on: date
    rates: dict


class RecordingRule:
    """Template for dating an announced rate. Subclasses choose only the date span."""

    name: str

    def bounds(self, announced_on: date, next_on: date | None, save_until: date) -> tuple[date, date]:
        raise NotImplementedError

    def rates(
        self, announcements: list[AnnouncedRate], save_from, save_until
    ) -> list[tuple[date, dict]]:
        save_from = getdate(save_from)
        save_until = getdate(save_until)
        recorded: dict[date, dict] = {}

        for series, points in _series_points(announcements).items():
            for index, (announced_on, rate) in enumerate(points):
                next_on = points[index + 1][0] if index + 1 < len(points) else None
                start, end = self.bounds(announced_on, next_on, save_until)
                for day in calendar_days(start, end):
                    if save_from <= day <= save_until:
                        recorded.setdefault(day, {})[series] = rate

        return [(day, recorded[day]) for day in sorted(recorded)]


class FirstWorkingDay(RecordingRule):
    """Store a rate on the announcement day and on the holidays that follow it."""

    name = FIRST_WORKING_DAY

    def bounds(self, announced_on: date, next_on: date | None, save_until: date) -> tuple[date, date]:
        if next_on:
            return announced_on, getdate(add_days(next_on, -1))
        return announced_on, save_until


class ImmediateDay(RecordingRule):
    """Store each announced rate on its day, then fill empty days both ways.

    Going forward, an empty day keeps the previous rate. Going backward, empty
    days take the first found later rate. A Sales Invoice on an announcement day
    therefore uses that day's own TCMB rate.
    """

    name = IMMEDIATE_DAY

    def bounds(self, announced_on: date, next_on: date | None, save_until: date) -> tuple[date, date]:
        if next_on:
            return announced_on, getdate(add_days(next_on, -1))
        return announced_on, save_until

    def rates(
        self, announcements: list[AnnouncedRate], save_from, save_until
    ) -> list[tuple[date, dict]]:
        save_from = getdate(save_from)
        save_until = getdate(save_until)
        recorded = {day: dict(rates) for day, rates in super().rates(announcements, save_from, save_until)}
        series_names: set[str] = {series for rates in recorded.values() for series in rates}
        for item in announcements:
            for series, rate in item.rates.items():
                if flt(rate) > 0:
                    series_names.add(series)

        for series in series_names:
            next_rate = None
            for day in reversed(list(calendar_days(save_from, save_until))):
                if series in recorded.get(day, {}):
                    next_rate = recorded[day][series]
                elif next_rate is not None:
                    recorded.setdefault(day, {})[series] = next_rate

        return [(day, recorded[day]) for day in sorted(recorded)]


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
