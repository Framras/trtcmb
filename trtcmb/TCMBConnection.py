import frappe
import requests
import datetime

from trtcmb.TCMBCurrency import TCMBCurrency
from trtcmb.TCMBCurrencyExchange import TCMBCurrencyExchange


class TCMBConnection:
    def __init__(self):
        self._s = requests.Session()
        self.a_day = datetime.timedelta(days=1)
        self.service_method = "GET"
        self.try_code = "YTL"
        self.tcmb_date_format = TCMBCurrencyExchange.tcmb_date_format
        self.type = TCMBCurrency.type
        self.doctype = TCMBCurrency.doctype
        self.series_separator = "-"
        self.inner_separator = "."
        self.response_separator = TCMBCurrencyExchange.response_separator
        self.buying_code = TCMBCurrencyExchange.buying_code
        self.selling_code = TCMBCurrencyExchange.selling_code
        self.series_prefix = "/series="
        self.start_date_prefix = "&startDate="
        self.end_date_prefix = "&endDate="
        self.type_prefix = TCMBCurrency.type_prefix
        self.key_prefix = TCMBCurrency.key_prefix
        self.company_doctype = TCMBCurrency.company_doctype
        self.integration_setting_doctype = TCMBCurrency.integration_setting_doctype
        self.company_setting_doctype = TCMBCurrency.company_setting_doctype
        # global settings
        self.service_path = TCMBCurrency.service_path
        self.company = frappe.defaults.get_user_default(self.company_doctype)
        # company settings
        self.enable = frappe.db.get_value(self.company_setting_doctype, self.company, "enable")
        self.key = frappe.db.get_value(self.company_setting_doctype, self.company, "key")
        self.start_date = frappe.db.get_value(self.company_setting_doctype, self.company, "start_date")
        self.last_updated = frappe.db.get_value(self.company_setting_doctype, self.company, "last_updated")
        self.date_of_establishment = frappe.db.get_value(self.company_doctype, self.company,
                                                         "date_of_establishment")

    def get_exchange_rates_for_enabled_currencies(self, datagroup_code: str):
        if datagroup_code != "bie_dkdovizgn" or self.enable != 1:
            # should be error
            return False
        else:
            pass
        currency_list = TCMBCurrency.get_list_of_enabled_currencies()
        if self.start_date is not None and \
                self.start_date > datetime.date(1950, 1, 2):
            tcmb_start_date = self.start_date

        delta = datetime.date.today() - tcmb_start_date
        for i in range(delta.days + 1):
            exchange_rate_day = tcmb_start_date + datetime.timedelta(days=i)
            for currency in currency_list:
                if currency.get("currency_name") != "TRY" and \
                        not frappe.db.exists({
                            "doctype": TCMBCurrencyExchange.doctype,
                            "date": exchange_rate_day,
                            "from_currency": currency.get("currency_name"),
                            "to_currency": TCMBCurrencyExchange.to_currency,
                            "for_buying": 1
                        }):
                    TCMBCurrencyExchange.commit_single_currency_exchange_rate(
                        self.get_single_exchange_rate(currency=currency.get("currency_name"),
                                                      for_date=exchange_rate_day,
                                                      purpose="for_buying"))
                if currency.get("currency_name") != "TRY" and \
                        not frappe.db.exists({
                            "doctype": TCMBCurrencyExchange.doctype,
                            "date": exchange_rate_day,
                            "from_currency": currency.get("currency_name"),
                            "to_currency": TCMBCurrencyExchange.to_currency,
                            "for_selling": 1
                        }):
                    TCMBCurrencyExchange.commit_single_currency_exchange_rate(
                        self.get_single_exchange_rate(currency=currency.get("currency_name"),
                                                      for_date=exchange_rate_day,
                                                      purpose="for_selling"))

        return datetime.datetime.today().date()

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

        # try:
        # r = self._s.request(method=self.service_method, url=url)
        # return json.loads(r.content)
        return requests.get(url).json()
        # except requests.exceptions.HTTPError as e:
        #     return r.raise_for_status()

    def get_single_exchange_rate(self, currency: str, for_date: datetime.date, purpose: str):
        if purpose == "for_buying":
            currency_serie = self.inner_separator.join(
                ["TP", "DK", currency, self.buying_code])
        elif purpose == "for_selling":
            currency_serie = self.inner_separator.join(
                ["TP", "DK", currency, self.selling_code])
        serie_as_list = [currency_serie]
        # Exchange, rates, Daily, (Converted, to, TRY)
        response_dict = self.connect(datagroup_code="bie_dkdovizgn", series_list=serie_as_list,
                                     for_start_date=for_date, for_end_date=for_date)
        if response_dict.get("totalCount") == 1:
            currency_response = currency_serie.replace(self.inner_separator, self.response_separator)
            if response_dict.get("items")[0].get(currency_response) is None:
                exchange_rate_date = datetime.datetime.strptime(response_dict.get("items")[0].get("Tarih"),
                                                                self.tcmb_date_format).date() - self.a_day
                new_dict = self.get_single_exchange_rate(currency, exchange_rate_date, purpose)
                response_dict["items"][0][currency_response] = new_dict["items"][0][currency_response]
            else:
                pass

        return response_dict
