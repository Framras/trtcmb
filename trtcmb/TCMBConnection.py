import frappe
import requests
import datetime
import json

from requests import HTTPError
from trtcmb.TCMBCurrency import TCMBCurrency
from trtcmb.TCMBCurrencyExchange import TCMBCurrencyExchange


class TCMBConnection:
    def __init__(self):
        self._s = requests.Session()
        self.a_day = datetime.timedelta(days=1)
        self.service_method = "GET"
        self.try_code = "YTL"
        self.tcmb_date_format = "%d-%m-%Y"
        self.buying_code = "A"
        self.selling_code = "S"
        self.type = "json"
        self.doctype = "Currency"
        self.inner_separator = "."
        self.series_separator = "-"
        self.series_prefix = "/series="
        self.start_date_prefix = "&startDate="
        self.end_date_prefix = "&endDate="
        self.type_prefix = "&type="
        self.key_prefix = "&key="
        self.company_doctype = "Company"
        self.integration_setting_doctype = "TR TCMB EVDS Integration Setting"
        self.company_setting_doctype = "TR TCMB EVDS Integration Company Setting"
        # global settings
        self.service_path = frappe.db.get_single_value(self.integration_setting_doctype, "service_path")
        self.company = frappe.defaults.get_user_default(self.company_doctype)
        # company settings
        self.enable = frappe.db.get_value(self.company_setting_doctype, self.company, "enable")
        self.key = frappe.db.get_value(self.company_setting_doctype, self.company, "key")
        self.start_date = frappe.db.get_value(self.company_setting_doctype, self.company, "start_date")
        self.last_updated = frappe.db.get_value(self.company_setting_doctype, self.company, "last_updated")
        self.date_of_establishment = frappe.db.get_value(self.company_doctype, self.company,
                                                         "date_of_establishment")

    def get_exchange_rates(self):
        exchange_rates = self.get_exchange_rates_for_enabled_currencies("bie_dkdovizgn")
        exchange_rates_list = exchange_rates.get("items")
        for exchange_rates_of_date in exchange_rates_list:
            for key in exchange_rates_of_date.keys():
                if key not in ["Tarih", "UNIXTIME"]:
                    if exchange_rates_of_date.get(key) is None:
                        exchange_rate_date = datetime.datetime.strptime(exchange_rates_of_date.get("Tarih"),
                                                                        self.tcmb_date_format).date() - self.a_day
                        exchange_rates_of_date[key] = self.get_exchange_rate_for_single_date_and_currency(
                            "bie_dkdovizgn", key, exchange_rate_date)
                    else:
                        pass
            TCMBCurrencyExchange.commit_single_exchange_rate(exchange_rates_of_date)
        return datetime.date.today()

    def get_exchange_rates_for_enabled_currencies(self, datagroup_code: str):
        if datagroup_code != "bie_dkdovizgn" or self.enable != 1:
            # should be error
            return False
        else:
            pass
        series_list = []
        currency_list = TCMBCurrency.get_list_of_enabled_currencies()
        for currency in currency_list:
            if currency.get("currency_name") != "TRY":
                buying_series = ["TP", "DK", currency.get("currency_name"), self.buying_code]
                selling_series = ["TP", "DK", currency.get("currency_name"), self.selling_code]
                series_list.append(self.inner_separator.join(buying_series))
                series_list.append(self.inner_separator.join(selling_series))

        if self.start_date is not None and \
                self.start_date > datetime.date(1950, 1, 2):
            tcmb_start_date = self.start_date

        return self.connect("bie_dkdovizgn", series_list=series_list, for_start_date=tcmb_start_date,
                            for_end_date=datetime.date.today())

    def connect(self, datagroup_code: str, series_list: list, for_start_date: datetime.date,
                for_end_date: datetime.date):
        if datagroup_code != "bie_dkdovizgn" or self.enable != 1:
            # should be error
            return False
        else:
            pass
        url = ""
        # Exchange, rates, Daily, (Converted, to, TRY)
        series = self.series_prefix + self.series_separator.join(series_list)
        tcmb_start_date = self.start_date_prefix + for_start_date.strftime(self.tcmb_date_format)
        tcmb_end_date = self.end_date_prefix + for_end_date.strftime(self.tcmb_date_format)
        return_type = self.type_prefix + self.type
        key = self.key_prefix + self.key

        url = self.service_path + series + tcmb_start_date + tcmb_end_date + return_type + key
        null = None

        try:
            r = self._s.request(method=self.service_method, url=url)
            # For successful API call, response code will be 200 (OK)
            with r:
                # Loading the response data into a dict variable json.loads takes in only binary or string
                # variables so using content to fetch binary content Loads (Load String) takes a Json file and
                # converts into python data structure (dict or list, depending on JSON)
                return json.loads(r.content)
        except HTTPError as e:
            return r.raise_for_status()
        finally:
            pass

    def get_exchange_rate_for_single_date_and_currency(self, datagroup_code: str, for_serie: str,
                                                       for_date: datetime.date):
        if datagroup_code != "bie_dkdovizgn" or self.enable != 1:
            # should be error
            return False
        else:
            pass
        serie_as_list = [for_serie]
        # Exchange, rates, Daily, (Converted, to, TRY)

        response = self.connect(datagroup_code, serie_as_list, for_date, for_date)
        if response.get("totalCount") == 1:
            response_list = response.get("items")
            for item in response_list:
                for key in item.keys():
                    if key not in ["Tarih", "UNIXTIME"]:
                        if item.get(key) is None:
                            exchange_rate_date = datetime.strptime(item.get("Tarih"),
                                                                   self.tcmb_date_format).date() - self.a_day
                            self.get_exchange_rate_for_single_date_and_currency("bie_dkdovizgn", key,
                                                                                exchange_rate_date)
                        else:
                            exchange_rate = item.get(key)

        return exchange_rate
