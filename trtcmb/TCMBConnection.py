import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

from trtcmb.dates import calendar_days, iter_date_batches, resolve_import_start
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

        announcements = self._collect_announcements(currency_list, save_from, today)
        recorded = rates_for_rule(self.rate_recording_rule, announcements, save_from, today)
        self._save_recorded_rates(recorded, save_from, today)
        return today

    def _collect_announcements(self, currency_list: list, save_from, today) -> list[AnnouncedRate]:
        announcements = [
            self.retrieve_announced_rate(currency_list, add_days(save_from, -self.a_day))
        ]
        pause_before_request = True
        for chunk_start, chunk_end in iter_date_batches(save_from, today, self.batch_days):
            if pause_before_request:
                TCMBCurrency.pause(self.batch_pause_seconds)
            pause_before_request = True
            announcements.extend(
                announced_rates_in(self.get_exchange_rates(currency_list, chunk_start, chunk_end))
            )
        return announcements

    def _save_recorded_rates(self, recorded: list[tuple], save_from, today) -> None:
        recorded_by_date = dict(recorded)
        for chunk_start, chunk_end in iter_date_batches(save_from, today, self.batch_days):
            self.record_exchange_rates(
                [
                    (day, recorded_by_date[day])
                    for day in calendar_days(chunk_start, chunk_end)
                    if day in recorded_by_date
                ]
            )
            frappe.db.set_value(
                TCMBCurrency.company_setting_doctype,
                self.company,
                "last_updated",
                chunk_end,
            )
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
        if depth > LOOKBACK_LIMIT_DAYS:
            frappe.throw(
                _("No TCMB rate was found within {0} days before {1}.").format(
                    LOOKBACK_LIMIT_DAYS, getdate(for_date)
                )
            )
        if depth:
            TCMBCurrency.pause(self.batch_pause_seconds)

        found = announced_rates_in(self.get_exchange_rates(currency_list, for_date, for_date))
        if found:
            return found[0]

        return self.retrieve_announced_rate(currency_list, add_days(for_date, -self.a_day), depth + 1)

    def record_exchange_rates(self, dated_rates: list[tuple]) -> None:
        """Write rates chosen by a recording rule. Retrieval does not call this."""
        for day, rates in dated_rates:
            if not rates:
                continue
            TCMBCurrencyExchange.commit_single_currency_exchange_rate(
                {TCMBCurrencyExchange.tcmb_date_key: day, **rates},
                self.enable_update,
                self.rate_options,
            )

    def get_exchange_rates(self, currency_list: list, from_date, to_date) -> list:
        series_list = self._selected_series(currency_list)
        if not series_list:
            return []
        return normalize_rate_items(self.connect(series_list, from_date, to_date))

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
