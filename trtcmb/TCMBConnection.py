from datetime import date

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, nowdate

from trtcmb.TCMBCurrency import TCMBCurrency
from trtcmb.TCMBCurrencyExchange import (
    DEFAULT_BATCH_DAYS,
    TCMBCurrencyExchange,
    normalize_batch_days,
    normalize_rate_options,
    transaction_flags,
)

BATCH_PAUSE_SECONDS = 1.0


class TCMBConnection:
    def __init__(self, company: str | None = None):
        self.a_day = 1
        self.series_separator = "-"
        self.inner_separator = "."
        self.series_prefix = "/series="
        self.start_date_prefix = "&startDate="
        self.end_date_prefix = "&endDate="
        self.datagroup_code = "bie_dkdovizgn"
        self.batch_days = DEFAULT_BATCH_DAYS
        self.batch_pause_seconds = BATCH_PAUSE_SECONDS

        self.company = company or frappe.defaults.get_user_default(TCMBCurrency.company_doctype)
        if not self.company:
            frappe.throw(_("No company found for TCMB EVDS integration."))

        self.enable = cint(
            frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "enable")
        )
        self.key = frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "key")
        self.start_date = frappe.db.get_value(
            TCMBCurrency.company_setting_doctype, self.company, "start_date"
        )
        self.last_updated = frappe.db.get_value(
            TCMBCurrency.company_setting_doctype, self.company, "last_updated"
        )
        self.enable_update = cint(
            frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "enable_update")
        )
        rate_settings = frappe.db.get_value(
            TCMBCurrency.company_setting_doctype,
            self.company,
            [
                "batch_days",
                "fetch_buying_rate",
                "buying_rate_for_buying",
                "buying_rate_for_selling",
                "fetch_selling_rate",
                "selling_rate_for_buying",
                "selling_rate_for_selling",
            ],
            as_dict=True,
        ) or {}
        self.batch_days = normalize_batch_days(rate_settings.get("batch_days"))
        self.rate_options = normalize_rate_options(
            rate_settings.get("fetch_buying_rate"),
            rate_settings.get("buying_rate_for_buying"),
            rate_settings.get("buying_rate_for_selling"),
            rate_settings.get("fetch_selling_rate"),
            rate_settings.get("selling_rate_for_buying"),
            rate_settings.get("selling_rate_for_selling"),
        )

    def get_exchange_rates_for_enabled_currencies(self, datagroup_code: str, incremental: bool = True):
        if datagroup_code != self.datagroup_code or self.enable != 1:
            return False

        currency_list = TCMBCurrency.get_list_of_enabled_currencies(company=self.company)
        if not currency_list:
            frappe.msgprint(_("No enabled currencies match TCMB EVDS series."))
            return False

        today = getdate(nowdate())
        tcmb_start_date = today

        if incremental and self.last_updated:
            tcmb_start_date = add_days(getdate(self.last_updated), 1)
        elif self.start_date:
            tcmb_start_date = getdate(self.start_date)

        if tcmb_start_date > today:
            return today

        last_known_rates: dict = {}
        imported_through = tcmb_start_date
        first_batch = True

        for chunk_start, chunk_end in iter_date_batches(tcmb_start_date, today, self.batch_days):
            if not first_batch:
                TCMBCurrency.pause(self.batch_pause_seconds)
            first_batch = False

            tcmb_exchange_rates = self.get_exchange_rates(
                currency_list=currency_list,
                from_date=chunk_start,
                to_date=chunk_end,
                last_known_rates=last_known_rates,
            )
            for tcmb_exchange_rate_data in tcmb_exchange_rates:
                TCMBCurrencyExchange.commit_single_currency_exchange_rate(
                    tcmb_exchange_rate_data, self.enable_update, self.rate_options
                )

            imported_through = chunk_end
            frappe.db.set_value(
                TCMBCurrency.company_setting_doctype,
                self.company,
                "last_updated",
                imported_through,
            )
            if not getattr(frappe.flags, "in_test", False):
                frappe.db.commit()

        return imported_through

    def connect(
        self,
        datagroup_code: str,
        series_list: list,
        for_start_date,
        for_end_date,
    ):
        if datagroup_code != self.datagroup_code or self.enable != 1:
            return False

        series = self.series_prefix + self.series_separator.join(series_list)
        tcmb_start_date = self.start_date_prefix + getdate(for_start_date).strftime(
            TCMBCurrencyExchange.tcmb_date_format
        )
        tcmb_end_date = self.end_date_prefix + getdate(for_end_date).strftime(
            TCMBCurrencyExchange.tcmb_date_format
        )
        return_type = TCMBCurrency.type_prefix + TCMBCurrency.response_type
        url = TCMBCurrency.get_service_path() + series + tcmb_start_date + tcmb_end_date + return_type
        return TCMBCurrency.request_json(url, str(self.key or ""))

    def get_single_exchange_rate(self, currency: str, for_date, purpose: str):
        currency_series_data = ""
        if purpose == "for_buying":
            currency_series_data = self.inner_separator.join(
                ["TP", "DK", currency, TCMBCurrencyExchange.buying_code]
            )
        elif purpose == "for_selling":
            currency_series_data = self.inner_separator.join(
                ["TP", "DK", currency, TCMBCurrencyExchange.selling_code]
            )
        series_as_list = [currency_series_data]

        response_dict = self.connect(
            datagroup_code=self.datagroup_code,
            series_list=series_as_list,
            for_start_date=for_date,
            for_end_date=for_date,
        )
        if not isinstance(response_dict, dict) or "totalCount" not in response_dict:
            frappe.throw(_("Unexpected JSON response from TCMB: {0}").format(str(response_dict)[:250]))

        if cint(response_dict.get("totalCount")) == 1:
            currency_response = currency_series_data.replace(
                self.inner_separator, TCMBCurrencyExchange.response_separator
            )
            items = response_dict.get("items") or []
            if items and items[0].get(currency_response) is None:
                exchange_rate_date = add_days(
                    TCMBCurrencyExchange.parse_tcmb_date(items[0].get("Tarih")),
                    -self.a_day,
                )
                new_dict = self.get_single_exchange_rate(currency, exchange_rate_date, purpose)
                response_dict["items"][0][currency_response] = new_dict["items"][0][currency_response]
        return response_dict

    def get_exchange_rates(
        self,
        currency_list: list,
        from_date,
        to_date,
        last_known_rates: dict | None = None,
    ) -> list:
        if not currency_list:
            return []

        currency_series_as_list: list[str] = []
        for currency in currency_list:
            buying_series = currency.get("buying_series") or self.inner_separator.join(
                ["TP", "DK", currency.get("name"), TCMBCurrencyExchange.buying_code]
            )
            selling_series = currency.get("selling_series") or self.inner_separator.join(
                ["TP", "DK", currency.get("name"), TCMBCurrencyExchange.selling_code]
            )
            if transaction_flags(TCMBCurrencyExchange.buying_code, self.rate_options):
                currency_series_as_list.append(buying_series)
            if transaction_flags(TCMBCurrencyExchange.selling_code, self.rate_options):
                currency_series_as_list.append(selling_series)

        if not currency_series_as_list:
            frappe.throw(_("Select a TCMB rate and a transaction type in the company settings."))

        response_dict = self.connect(
            datagroup_code=self.datagroup_code,
            series_list=currency_series_as_list,
            for_start_date=from_date,
            for_end_date=to_date,
        )
        return self._normalize_rate_items(response_dict, last_known_rates if last_known_rates is not None else {})

    def _normalize_rate_items(self, response_dict, last_known_rates: dict) -> list[dict]:
        if not isinstance(response_dict, dict) or "totalCount" not in response_dict:
            frappe.throw(_("Unexpected JSON response from TCMB: {0}").format(str(response_dict)[:250]))

        if cint(response_dict.get("totalCount")) < 1:
            return []

        currency_series_data = response_dict.get("items") or []
        return_list: list[dict] = []

        for currency_tuple in currency_series_data:
            if not isinstance(currency_tuple, dict):
                continue
            row = dict(currency_tuple)
            row.pop(TCMBCurrencyExchange.tcmb_strip_key, None)
            reference_date = row.pop("Tarih", None)
            if not reference_date:
                continue

            for tuple_key in list(row):
                current_rate = row.get(tuple_key)
                if current_rate in (None, ""):
                    row[tuple_key] = last_known_rates.get(tuple_key)
                else:
                    last_known_rates[tuple_key] = current_rate

            row[TCMBCurrencyExchange.tcmb_date_key] = reference_date
            return_list.append(row)

        return return_list


def iter_date_batches(from_date, to_date, batch_days: int = DEFAULT_BATCH_DAYS) -> list[tuple[date, date]]:
    """Yield inclusive date windows of `batch_days` covering from_date through to_date."""
    if batch_days < 1:
        frappe.throw(_("TCMB batch size must be at least 1 day."))

    chunk_start = getdate(from_date)
    final_date = getdate(to_date)
    batches: list[tuple[date, date]] = []

    while chunk_start <= final_date:
        chunk_end = getdate(add_days(chunk_start, batch_days - 1))
        if chunk_end > final_date:
            chunk_end = final_date
        batches.append((chunk_start, chunk_end))
        chunk_start = add_days(chunk_end, 1)

    return batches
