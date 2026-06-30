import datetime
import frappe
import requests

from trtcmb.TCMBCurrency import TCMBCurrency
from trtcmb.TCMBCurrencyExchange import TCMBCurrencyExchange


class TCMBConnection:

    def __init__(self):
        self.a_day = datetime.timedelta(days=1)
        self.series_separator = "-"
        self.inner_separator = "."
        self.series_prefix = "/series="
        self.start_date_prefix = "&startDate="
        self.end_date_prefix = "&endDate="
        self.datagroup_code = "bie_dkdovizgn"

        # global settings
        self.company = frappe.defaults.get_user_default(TCMBCurrency.company_doctype)
        # company settings
        self.enable = frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "enable")
        self.key = frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "key")
        self.start_date = frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "start_date")
        self.last_updated = frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "last_updated")
        self.enable_update = frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "enable_update")

    def get_exchange_rates_for_enabled_currencies(self, datagroup_code: str):
        if datagroup_code != self.datagroup_code or self.enable != 1:
            return False

        currency_list = TCMBCurrency.get_list_of_enabled_currencies()
        tcmb_start_date = datetime.date.today()

        if self.start_date is not None and self.start_date > datetime.date(1950, 1, 2):
            tcmb_start_date = self.start_date

        tcmb_exchange_rates = self.get_exchange_rates(
            currency_list=currency_list,
            from_date=tcmb_start_date,
            to_date=datetime.date.today()
        )

        for tcmb_exchange_rate_data in tcmb_exchange_rates:
            TCMBCurrencyExchange.commit_single_currency_exchange_rate(tcmb_exchange_rate_data, self.enable_update)

        return datetime.datetime.today().date()

    def connect(self, datagroup_code: str, series_list: list, for_start_date: datetime.date,
                for_end_date: datetime.date):
        if datagroup_code != self.datagroup_code or self.enable != 1:
            return False

        series = self.series_prefix + self.series_separator.join(series_list)
        tcmb_start_date = self.start_date_prefix + for_start_date.strftime(TCMBCurrencyExchange.tcmb_date_format)
        tcmb_end_date = self.end_date_prefix + for_end_date.strftime(TCMBCurrencyExchange.tcmb_date_format)
        return_type = TCMBCurrency.type_prefix + TCMBCurrency.response_type

        # Add .strip() here to sanitize user input from the settings doctype
        url = TCMBCurrency.service_path.strip().rstrip('/') + series + tcmb_start_date + tcmb_end_date + return_type

        headers = {
            'key': self.key,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            frappe.throw(f"TCMB API Error {response.status_code}: {response.text[:250]}")

        return response.json()

    def get_single_exchange_rate(self, currency: str, for_date: datetime.date, purpose: str):
        currency_series_data = ""
        if purpose == "for_buying":
            currency_series_data = self.inner_separator.join(
                ["TP", "DK", currency, TCMBCurrencyExchange.buying_code])
        elif purpose == "for_selling":
            currency_series_data = self.inner_separator.join(
                ["TP", "DK", currency, TCMBCurrencyExchange.selling_code])
        series_as_list = [currency_series_data]

        response_dict = self.connect(datagroup_code=self.datagroup_code, series_list=series_as_list,
                                     for_start_date=for_date, for_end_date=for_date)

        # Defensive Check: Surface the actual API error if the structure is unexpected
        if not isinstance(response_dict, dict) or "totalCount" not in response_dict:
            frappe.throw(f"Unexpected JSON response from TCMB: {response_dict}")

        if (response_dict.get("totalCount") or 0) == 1:
            currency_response = currency_series_data.replace(self.inner_separator,
                                                             TCMBCurrencyExchange.response_separator)
            if response_dict.get("items")[0].get(currency_response) is None:
                exchange_rate_date = datetime.datetime.strptime(response_dict.get("items")[0].get("Tarih"),
                                                                TCMBCurrencyExchange.tcmb_date_format).date() - \
                                     self.a_day
                new_dict = self.get_single_exchange_rate(currency, exchange_rate_date, purpose)
                response_dict["items"][0][currency_response] = new_dict["items"][0][currency_response]
        return response_dict

    def get_exchange_rates(self, currency_list: list, from_date: datetime.date, to_date: datetime.date):
        if not currency_list:
            return []

        currency_series_as_list = list()
        for currency in currency_list:
            currency_series_as_list.append(self.inner_separator.join(
                ["TP", "DK", currency.get("name"), TCMBCurrencyExchange.buying_code]))
            currency_series_as_list.append(self.inner_separator.join(
                ["TP", "DK", currency.get("name"), TCMBCurrencyExchange.selling_code]))

        response_dict = self.connect(datagroup_code=self.datagroup_code, series_list=currency_series_as_list,
                                     for_start_date=from_date, for_end_date=to_date)

        return_list = list()

        if not isinstance(response_dict, dict) or "totalCount" not in response_dict:
            frappe.throw(f"Unexpected JSON response from TCMB: {response_dict}")

        if (response_dict.get("totalCount") or 0) >= 1:
            currency_series_data = response_dict.pop("items")

            # Dictionary to remember the last valid rate we saw for each currency type
            last_known_rates = dict()

            for currency_tuple in currency_series_data:
                currency_tuple.pop(TCMBCurrencyExchange.tcmb_strip_key, None)
                reference_date = currency_tuple.pop("Tarih")

                for tuple_key in list(currency_tuple):
                    current_rate = currency_tuple.get(tuple_key)

                    if current_rate is None:
                        # If the rate is blank (e.g. a weekend), use the last known rate from memory
                        currency_tuple[tuple_key] = last_known_rates.get(tuple_key)
                    else:
                        # If the rate is valid, save it to memory for future weekends
                        last_known_rates[tuple_key] = current_rate

                currency_tuple[TCMBCurrencyExchange.tcmb_date_key] = reference_date
                return_list.append(currency_tuple)

        return return_list