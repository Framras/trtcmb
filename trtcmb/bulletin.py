"""TCMB XML bulletin reader for Immediate Day empty days.

EVDS row dates are validity days. Bulletin dates are determination days.
Shared EVDS placement never changes. Only Immediate Day fills days with no
EVDS rate from the previous business day's bulletin (walking back on 404).
"""

from __future__ import annotations

from datetime import date, datetime
from xml.etree import ElementTree as ET

import frappe
import requests
from frappe import _
from frappe.utils import flt, formatdate, getdate

from trtcmb.dates import calendar_days, previous_business_day
from trtcmb.recording import IMMEDIATE_DAY, fill_forward, normalize_recording_rule
from trtcmb.TCMBCurrency import RETRYABLE_STATUS, TCMBCurrency
from trtcmb.TCMBCurrencyExchange import TCMBCurrencyExchange

BULLETIN_BASE_URL = "https://www.tcmb.gov.tr/kurlar/"
BULLETIN_LOOKBACK_BUSINESS_DAYS = 10
_FOREX_BY_CODE = {
    TCMBCurrencyExchange.buying_code: "ForexBuying",
    TCMBCurrencyExchange.selling_code: "ForexSelling",
}


class BulletinNotFound(Exception):
    """No bulletin XML exists for the requested day (HTTP 404)."""


def bulletin_url(for_date) -> str:
    day = getdate(for_date)
    return f"{BULLETIN_BASE_URL}{day.strftime('%Y%m')}/{day.strftime('%d%m%Y')}.xml"


def request_bulletin_xml(url: str, retries: int = 4) -> str | None:
    """Fetch bulletin XML. HTTP 404 means no bulletin that day (return None)."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    last_error: str | None = None

    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=60)
        except requests.RequestException as exc:
            last_error = str(exc)
            TCMBCurrency.pause(2**attempt)
            continue

        if response.status_code == 404:
            return None

        if response.status_code in RETRYABLE_STATUS:
            last_error = _("HTTP {0}").format(response.status_code)
            TCMBCurrency.pause(2**attempt)
            continue

        if response.status_code != 200:
            frappe.throw(
                _("TCMB bulletin error {0}: {1}").format(response.status_code, response.text[:250])
            )

        text = response.text or ""
        if "<Tarih_Date" not in text:
            frappe.throw(_("TCMB bulletin returned a non-XML response: {0}").format(text[:250]))
        return text

    frappe.throw(
        _("TCMB bulletin request failed after retries: {0}").format(last_error or _("unknown error"))
    )


def parse_bulletin_xml(xml_text: str, expected_date) -> dict[str, dict[str, float]]:
    """Return {currency_code: {"A": rate, "S": rate}} for Forex rates only.

    BanknoteBuying / BanknoteSelling are ignored. Values are per unit.
    Bulten_No is optional (absent before 2003).
    """
    expected = getdate(expected_date)
    root = ET.fromstring(xml_text)
    stamp = (root.attrib.get("Tarih") or "").strip()
    bulletin_no = (root.attrib.get("Bulten_No") or "").strip()
    if bulletin_no:
        frappe.logger("trtcmb").info(
            "TCMB bulletin {0} for {1}".format(bulletin_no, formatdate(expected))
        )

    parsed_stamp = _parse_bulletin_tarih(stamp)
    if parsed_stamp != expected:
        frappe.throw(
            _("TCMB bulletin date {0} does not match the requested day {1}.").format(
                stamp or _("(empty)"), formatdate(expected)
            )
        )

    rates: dict[str, dict[str, float]] = {}
    for currency_node in root.findall("Currency"):
        code = (currency_node.attrib.get("CurrencyCode") or currency_node.attrib.get("Kod") or "").strip()
        if not code:
            continue
        unit = flt(currency_node.findtext("Unit") or 1) or 1
        per_code: dict[str, float] = {}
        for rate_code, tag in _FOREX_BY_CODE.items():
            raw = (currency_node.findtext(tag) or "").strip()
            if raw in ("", "."):
                continue
            numeric = flt(raw)
            if numeric > 0:
                per_code[rate_code] = flt(numeric / unit)
        if per_code:
            rates[code] = per_code
    return rates


def bulletin_rates_for_currencies(
    bulletin_rates: dict[str, dict[str, float]], currency_list: list
) -> dict[str, float]:
    """Map bulletin Forex A/S values onto the EVDS response series keys in use."""
    mapped: dict[str, float] = {}
    for currency in currency_list:
        code = currency.get("name")
        per_code = bulletin_rates.get(code) or {}
        for rate_code, fieldname in (
            (TCMBCurrencyExchange.buying_code, "buying_series"),
            (TCMBCurrencyExchange.selling_code, "selling_series"),
        ):
            series = currency.get(fieldname)
            if not series or rate_code not in per_code:
                continue
            mapped[str(series).replace(".", "_")] = per_code[rate_code]
    return mapped


def fetch_bulletin_series(for_date, currency_list: list) -> dict[str, float] | None:
    """Return mapped series rates, or None when that day's bulletin does not exist."""
    xml_text = request_bulletin_xml(bulletin_url(for_date))
    if xml_text is None:
        return None
    return bulletin_rates_for_currencies(parse_bulletin_xml(xml_text, for_date), currency_list)


def resolve_bulletin_series(
    for_date,
    currency_list: list,
    *,
    fetch_series=None,
    cache: dict[date, dict[str, float] | None] | None = None,
    max_lookback: int = BULLETIN_LOOKBACK_BUSINESS_DAYS,
) -> dict[str, float]:
    """Walk back business days until a bulletin is found, or return {}."""
    fetch = fetch_series or fetch_bulletin_series
    cache = cache if cache is not None else {}
    day = getdate(for_date)
    for _ in range(max_lookback):
        if day not in cache:
            try:
                cache[day] = fetch(day, currency_list)
            except Exception as exc:
                frappe.logger("trtcmb").warning(
                    "TCMB bulletin for {0} was skipped: {1}".format(formatdate(day), exc)
                )
                cache[day] = None
        found = cache[day]
        if found:
            return found
        day = previous_business_day(day)
    return {}


def fill_empty_days_from_bulletin(
    recorded: list[tuple],
    currency_list: list,
    chunk_start,
    chunk_end,
    covered: dict[str, date],
    *,
    fetch_series=None,
    seed_before: dict[str, float] | None = None,
) -> list[tuple]:
    """For Immediate Day: days without an EVDS rate take a bulletin, else the previous EVDS rate."""
    by_day = {getdate(day): dict(rates) for day, rates in recorded}
    bulletin_cache: dict[date, dict[str, float] | None] = {}
    series_names = set(covered)
    seeds = dict(seed_before or {})

    for day in calendar_days(chunk_start, chunk_end):
        needed = [series for series, start in covered.items() if getdate(start) <= day]
        if not needed:
            continue
        missing = [series for series in needed if series not in by_day.get(day, {})]
        if not missing:
            continue
        source_day = previous_business_day(day)
        bulletin_rates = resolve_bulletin_series(
            source_day,
            currency_list,
            fetch_series=fetch_series,
            cache=bulletin_cache,
        )
        if not bulletin_rates:
            continue
        day_rates = by_day.setdefault(day, {})
        for series in missing:
            if series in bulletin_rates:
                day_rates[series] = bulletin_rates[series]

    # Invariant: no processed day stays empty — fall back to the previous EVDS rate.
    fill_forward(
        by_day, series_names, getdate(chunk_start), getdate(chunk_end), seed_before=seeds
    )

    return [(day, by_day[day]) for day in sorted(by_day)]


def apply_strategy_empty_fill(
    recorded: list[tuple],
    currency_list: list,
    chunk_start,
    chunk_end,
    covered: dict[str, date],
    rate_recording_rule: str | None,
    *,
    fetch_series=None,
    seed_before: dict[str, float] | None = None,
) -> list[tuple]:
    """Dispatch empty-day fill. First Working Day already filled from EVDS; Immediate uses bulletin."""
    if normalize_recording_rule(rate_recording_rule) != IMMEDIATE_DAY:
        return recorded
    return fill_empty_days_from_bulletin(
        recorded,
        currency_list,
        chunk_start,
        chunk_end,
        covered,
        fetch_series=fetch_series,
        seed_before=seed_before,
    )


def _parse_bulletin_tarih(value: str) -> date | None:
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return getdate(datetime.strptime(value, fmt))
        except ValueError:
            continue
    return getdate(value)
