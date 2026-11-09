from datetime import date

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, formatdate, getdate, nowdate

from trtcmb.dates import (
    EARLIEST_TCMB_DATE,
    calendar_days,
    iter_date_batches,
    resolve_import_start,
    tcmb_date_is_maintained,
)
from trtcmb.recording import AnnouncedRate, normalize_recording_rule, rates_for_rule
from trtcmb.TCMBCurrency import TCMBCurrency
from trtcmb.TCMBCurrencyExchange import (
    DEFAULT_BATCH_DAYS,
    TCMBCurrencyExchange,
    normalize_batch_days,
    normalize_rate_options,
    transaction_flags,
)

BATCH_PAUSE_SECONDS = 1.0
LOOKBACK_LIMIT_DAYS = 30


class TCMBRateNotFound(frappe.ValidationError):
    """No maintained TCMB rate was found for the requested day."""
_RATE_FIELDS = (
    (TCMBCurrencyExchange.buying_code, "buying_series"),
    (TCMBCurrencyExchange.selling_code, "selling_series"),
)
_SETTING_FIELDS = [
    "enable",
    "key",
    "start_date",
    "last_updated",
    "enable_update",
    "batch_days",
    "fetch_buying_rate",
    "buying_rate_for_buying",
    "buying_rate_for_selling",
    "fetch_selling_rate",
    "selling_rate_for_buying",
    "selling_rate_for_selling",
    "rate_recording_rule",
]


class TCMBConnection:
    """Load one company's TCMB settings, retrieve rates, and hand them to a recording rule."""

    def __init__(self, company: str | None = None):
        self.a_day = 1
        self.series_separator = "-"
        self.inner_separator = "."
        self.series_prefix = "/series="
        self.start_date_prefix = "&startDate="
        self.end_date_prefix = "&endDate="
        self.datagroup_code = TCMBCurrency.datagroup_code
        self.batch_days = DEFAULT_BATCH_DAYS
        self.batch_pause_seconds = BATCH_PAUSE_SECONDS

        self.company = company or frappe.defaults.get_user_default(TCMBCurrency.company_doctype)
        if not self.company:
            frappe.throw(_("No company found for TCMB EVDS integration."))

        settings = (
            frappe.db.get_value(
                TCMBCurrency.company_setting_doctype,
                self.company,
                _SETTING_FIELDS,
                as_dict=True,
            )
            or {}
        )
        self.enable = cint(settings.get("enable"))
        self.key = settings.get("key")
        self.start_date = settings.get("start_date")
        self.last_updated = settings.get("last_updated")
        self.enable_update = cint(settings.get("enable_update"))
        self.batch_days = normalize_batch_days(settings.get("batch_days"))
        self.rate_options = normalize_rate_options(
            settings.get("fetch_buying_rate"),
            settings.get("buying_rate_for_buying"),
            settings.get("buying_rate_for_selling"),
            settings.get("fetch_selling_rate"),
            settings.get("selling_rate_for_buying"),
            settings.get("selling_rate_for_selling"),
        )
        self.rate_recording_rule = normalize_recording_rule(settings.get("rate_recording_rule"))

    def get_exchange_rates_for_enabled_currencies(self, incremental: bool = True):
        if self.enable != 1:
            return False

        currency_list = TCMBCurrency.get_list_of_enabled_currencies(company=self.company)
        if not currency_list:
            frappe.msgprint(_("No enabled currencies match TCMB EVDS series."))
            return False

        today = getdate(nowdate())
        save_from = resolve_import_start(
            self.start_date,
            today,
            last_updated=self.last_updated,
            incremental=incremental,
        )
        if save_from > today:
            return today

        carried = self._anchor_for_range(currency_list, save_from, today)
        recorded_days = 0
        last_recorded = None
        empty_chunks = 0
        covered: dict[str, date] = {}
        self._note_coverage(covered, carried, save_from)

        for chunk_start, chunk_end in iter_date_batches(save_from, today, self.batch_days):
            TCMBCurrency.pause(self.batch_pause_seconds)
            chunk_rows, total_count = self.get_exchange_rates(currency_list, chunk_start, chunk_end)
            chunk_announcements = announced_rates_in(chunk_rows)
            outage = total_count == 0 and _chunk_has_weekday(chunk_start, chunk_end)
            written_days: list = []
            if not outage:
                self._note_coverage(covered, chunk_announcements, save_from)
                recorded = rates_for_rule(
                    self.rate_recording_rule,
                    carried + chunk_announcements,
                    chunk_start,
                    chunk_end,
                )
                missing = _missing_series_days(recorded, chunk_start, chunk_end, covered)
                if missing:
                    frappe.throw(
                        _("TCMB import for {0} did not record {1}.").format(
                            self.company, ", ".join(missing)
                        )
                    )
                written_days = self.record_exchange_rates(recorded)
            if written_days:
                latest = max(written_days)
                last_recorded = latest if last_recorded is None else max(last_recorded, latest)
                self._advance_last_updated(latest)
                recorded_days += len(written_days)
            if outage:
                empty_chunks += 1
                frappe.logger("trtcmb").warning(
                    "TCMB returned no rates for {0} from {1} to {2}".format(
                        self.company, formatdate(chunk_start), formatdate(chunk_end)
                    )
                )
            carried = _merge_carried(carried, chunk_announcements)
            self._commit_chunk()
            if outage and recorded_days and not written_days:
                break

        frappe.logger("trtcmb").info(
            "TCMB import for {0} from {1} to {2}: recorded {3} days, {4} empty chunks, last_updated {5}".format(
                self.company,
                formatdate(save_from),
                formatdate(today),
                recorded_days,
                empty_chunks,
                formatdate(self.last_updated) if self.last_updated else "",
            )
        )
        if recorded_days == 0:
            frappe.throw(
                _("No TCMB rates were recorded for {0} from {1} to {2}.").format(
                    self.company, formatdate(save_from), formatdate(today)
                )
            )
        return last_recorded

    def _anchor_for_range(self, currency_list: list, save_from, today) -> list[AnnouncedRate]:
        """Return the latest rate of each series before save_from.

        An anchor day that quotes only one series does not hide an earlier rate
        for another series. When nothing is found, the range's own first
        announcement is used and no anchor is carried.
        """
        prior_day = add_days(save_from, -self.a_day)
        try:
            return self._rates_on_or_before(currency_list, prior_day)
        except TCMBRateNotFound:
            first_on = self._scan_forward_for_announcement(currency_list, save_from, today)
            if not first_on:
                raise
            frappe.logger("trtcmb").info(
                "TCMB anchor is missing for {0}; first data is on {1}".format(
                    self.company, formatdate(first_on)
                )
            )
            return []

    def _rates_on_or_before(self, currency_list: list, for_date) -> list[AnnouncedRate]:
        """Walk back until every requested series has a rate, or the lookback ends."""
        if not tcmb_date_is_maintained(for_date):
            frappe.throw(
                _("TCMB does not maintain exchange rates before {0}.").format(formatdate(EARLIEST_TCMB_DATE)),
                exc=TCMBRateNotFound,
            )
        needed = _response_keys(currency_list)
        found: dict[str, tuple[date, float]] = {}
        day = getdate(for_date)
        for depth in range(LOOKBACK_LIMIT_DAYS + 1):
            if not tcmb_date_is_maintained(day):
                break
            if depth:
                TCMBCurrency.pause(self.batch_pause_seconds)
            rows, _total_count = self.get_exchange_rates(currency_list, day, day)
            for item in announced_rates_in(rows):
                for series, rate in item.rates.items():
                    if series not in found:
                        found[series] = (getdate(item.announced_on), rate)
            if needed and needed <= set(found):
                break
            day = getdate(add_days(day, -self.a_day))
        if not found:
            frappe.throw(
                _("No TCMB rate was found within {0} days before {1}.").format(
                    LOOKBACK_LIMIT_DAYS, formatdate(for_date)
                ),
                exc=TCMBRateNotFound,
            )
        return [AnnouncedRate(announced_on, {series: rate}) for series, (announced_on, rate) in found.items()]

    def _note_coverage(self, covered: dict[str, date], announcements: list[AnnouncedRate], save_from) -> None:
        for item in announcements:
            announced_on = getdate(item.announced_on)
            for series in item.rates:
                if series not in covered:
                    covered[series] = announced_on

    def _scan_forward_for_announcement(self, currency_list: list, save_from, today):
        for offset in range(LOOKBACK_LIMIT_DAYS):
            day = getdate(add_days(save_from, offset))
            if day > getdate(today):
                break
            TCMBCurrency.pause(self.batch_pause_seconds)
            rows, _total_count = self.get_exchange_rates(currency_list, day, day)
            found = announced_rates_in(rows)
            if found:
                return found[0].announced_on
        return None

    def _advance_last_updated(self, day) -> None:
        day = getdate(day)
        if self.last_updated and getdate(self.last_updated) >= day:
            return
        self.last_updated = day
        frappe.db.set_value(
            TCMBCurrency.company_setting_doctype,
            self.company,
            "last_updated",
            day,
        )

    def _commit_chunk(self) -> None:
        if not getattr(frappe.flags, "in_test", False):
            frappe.db.commit()

    def connect(self, series_list: list, for_start_date, for_end_date):
        if self.enable != 1:
            return False

        series = self.series_prefix + self.series_separator.join(series_list)
        start = self.start_date_prefix + getdate(for_start_date).strftime(TCMBCurrencyExchange.tcmb_date_format)
        end = self.end_date_prefix + getdate(for_end_date).strftime(TCMBCurrencyExchange.tcmb_date_format)
        return_type = TCMBCurrency.type_prefix + TCMBCurrency.response_type
        url = TCMBCurrency.get_service_path() + series + start + end + return_type
        return TCMBCurrency.request_json(url, str(self.key or ""))

    def retrieve_announced_rate(self, currency_list: list, for_date, depth: int = 0) -> AnnouncedRate:
        """Return the TCMB rate for one day, walking back one day until a rate is received.

        Dates visited only to find a rate are not saved.
        """
        if not tcmb_date_is_maintained(for_date):
            frappe.throw(
                _("TCMB does not maintain exchange rates before {0}.").format(formatdate(EARLIEST_TCMB_DATE)),
                exc=TCMBRateNotFound,
            )
        if depth > LOOKBACK_LIMIT_DAYS:
            frappe.throw(
                _("No TCMB rate was found within {0} days before {1}.").format(
                    LOOKBACK_LIMIT_DAYS, formatdate(for_date)
                ),
                exc=TCMBRateNotFound,
            )
        if depth:
            TCMBCurrency.pause(self.batch_pause_seconds)

        rows, _total_count = self.get_exchange_rates(currency_list, for_date, for_date)
        found = announced_rates_in(rows)
        if found:
            return found[0]

        return self.retrieve_announced_rate(currency_list, add_days(for_date, -self.a_day), depth + 1)

    def record_exchange_rates(self, dated_rates: list[tuple]) -> list:
        """Write rates chosen by a recording rule. Retrieval does not call this."""
        written: list = []
        for day, rates in dated_rates:
            if not rates:
                continue
            TCMBCurrencyExchange.commit_single_currency_exchange_rate(
                {TCMBCurrencyExchange.tcmb_date_key: day, **rates},
                self.enable_update,
                self.rate_options,
            )
            written.append(getdate(day))
        return sorted(written)

    def get_exchange_rates(self, currency_list: list, from_date, to_date) -> tuple[list, int]:
        series_list = self._selected_series(currency_list)
        if not series_list:
            return [], 0
        response = self.connect(series_list, from_date, to_date)
        if not isinstance(response, dict):
            return normalize_rate_items(response), 0
        return normalize_rate_items(response), cint(response.get("totalCount"))

    def _selected_series(self, currency_list: list) -> list[str]:
        selected: list[str] = []
        for currency in currency_list:
            for rate_code, fieldname in _RATE_FIELDS:
                if not transaction_flags(rate_code, self.rate_options):
                    continue
                selected.append(
                    currency.get(fieldname)
                    or self.inner_separator.join(["TP", "DK", currency.get("name"), rate_code])
                )
        if not selected:
            frappe.throw(_("Select a TCMB rate and a transaction type in the company settings."))
        return selected


def _chunk_has_weekday(chunk_start, chunk_end) -> bool:
    return any(day.weekday() < 5 for day in calendar_days(chunk_start, chunk_end))


def _response_keys(currency_list: list) -> set[str]:
    keys: set[str] = set()
    for currency in currency_list:
        for fieldname in ("buying_series", "selling_series"):
            series = currency.get(fieldname)
            if series:
                keys.add(str(series).replace(".", "_"))
    return keys


def _merge_carried(carried: list[AnnouncedRate], announcements: list[AnnouncedRate]) -> list[AnnouncedRate]:
    """Keep the latest announcement of each series. A one-currency day does not drop the others."""
    latest: dict[str, tuple[date, float]] = {}
    for item in list(carried) + list(announcements):
        announced_on = getdate(item.announced_on)
        for series, rate in item.rates.items():
            current = latest.get(series)
            if current is None or announced_on >= current[0]:
                latest[series] = (announced_on, rate)
    return [AnnouncedRate(announced_on, {series: rate}) for series, (announced_on, rate) in latest.items()]


def _missing_series_days(recorded: list[tuple], chunk_start, chunk_end, covered: dict[str, date]) -> list[str]:
    present = {getdate(day): set(rates) for day, rates in recorded}
    missing: list[str] = []
    for day in calendar_days(chunk_start, chunk_end):
        for series, start in covered.items():
            if getdate(start) <= day and series not in present.get(day, set()):
                missing.append(f"{formatdate(day)} {series}")
    return missing


def announced_rates_in(rows: list[dict]) -> list[AnnouncedRate]:
    found: list[AnnouncedRate] = []
    for row in rows:
        rates = positive_rates(row)
        if not rates:
            continue
        row_date = TCMBCurrencyExchange.parse_tcmb_date(row.get(TCMBCurrencyExchange.tcmb_date_key))
        if row_date:
            found.append(AnnouncedRate(getdate(row_date), rates))
    return found


def positive_rates(row: dict) -> dict:
    rates = {}
    for key, value in row.items():
        if key == TCMBCurrencyExchange.tcmb_date_key or value in (None, ""):
            continue
        numeric = flt(value)
        if numeric > 0:
            rates[key] = numeric
    return rates


def normalize_rate_items(response_dict) -> list[dict]:
    if not isinstance(response_dict, dict) or "totalCount" not in response_dict:
        frappe.throw(_("Unexpected JSON response from TCMB: {0}").format(str(response_dict)[:250]))

    if cint(response_dict.get("totalCount")) < 1:
        return []

    rows: list[dict] = []
    for item in response_dict.get("items") or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row.pop(TCMBCurrencyExchange.tcmb_strip_key, None)
        reference_date = row.pop("Tarih", None)
        if not reference_date:
            continue
        row[TCMBCurrencyExchange.tcmb_date_key] = reference_date
        rows.append(row)
    return rows
