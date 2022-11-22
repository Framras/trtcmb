import frappe
import datetime
import trtcmb.CustomHTTPAdapter

from trtcmb.TCMBCurrency import TCMBCurrency
from trtcmb.TCMBCurrencyExchange import TCMBCurrencyExchange


class TCMBConnection:
    def __init__(self):
        #        self._s = requests.Session()
        self._s = trtcmb.CustomHTTPAdapter.get_legacy_session()
        self.a_day = datetime.timedelta(days=1)
        self.series_separator = "-"
        self.inner_separator = "."
        self.series_prefix = "/series="
        self.start_date_prefix = "&startDate="
        self.end_date_prefix = "&endDate="
        # global settings
        self.company = frappe.defaults.get_user_default(TCMBCurrency.company_doctype)
        # company settings
        self.enable = frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "enable")
        self.key = frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "key")
        self.start_date = frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "start_date")
        self.last_updated = frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "last_updated")
        self.enable_update = frappe.db.get_value(TCMBCurrency.company_setting_doctype, self.company, "enable_update")

    def get_exchange_rates_for_enabled_currencies(self, datagroup_code: str):
        if datagroup_code != "bie_dkdovizgn" or self.enable != 1:
            # should be error
            return False
        currency_list = TCMBCurrency.get_list_of_enabled_currencies()
        if self.start_date is not None and self.start_date > datetime.date(1950, 1, 2):
            tcmb_start_date = self.start_date
        delta = datetime.date.today() - tcmb_start_date
        for i in range(delta.days + 1):
            exchange_rate_day = tcmb_start_date + datetime.timedelta(days=i)
            for currency in currency_list:
                if self.enable_update == 0:
                    if currency.get("currency_name") != "TRY" and \
                            frappe.db.exists({
                                "doctype": TCMBCurrencyExchange.doctype,
                                "date": exchange_rate_day,
                                "from_currency": currency.get("currency_name"),
                                "to_currency": TCMBCurrencyExchange.to_currency,
                                "for_buying": 1
                            }):
                        continue
                    else:
                        TCMBCurrencyExchange.commit_single_currency_exchange_rate(
                            self.get_single_exchange_rate(currency=currency.get("currency_name"),
                                                          for_date=exchange_rate_day,
                                                          purpose="for_buying"))
                    if currency.get("currency_name") != "TRY" and \
                            frappe.db.exists({
                                "doctype": TCMBCurrencyExchange.doctype,
                                "date": exchange_rate_day,
                                "from_currency": currency.get("currency_name"),
                                "to_currency": TCMBCurrencyExchange.to_currency,
                                "for_selling": 1
                            }):
                        continue
                    else:
                        TCMBCurrencyExchange.commit_single_currency_exchange_rate(
                            self.get_single_exchange_rate(currency=currency.get("currency_name"),
                                                          for_date=exchange_rate_day,
                                                          purpose="for_selling"))
                elif self.enable_update == 1:
                    TCMBCurrencyExchange.commit_single_currency_exchange_rate(
                        self.get_single_exchange_rate(currency=currency.get("currency_name"),
                                                      for_date=exchange_rate_day,
                                                      purpose="for_buying"))
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
        url = ""
        # Exchange, rates, Daily, (Converted, to, TRY)
        series = self.series_prefix + self.series_separator.join(series_list)
        tcmb_start_date = self.start_date_prefix + for_start_date.strftime(TCMBCurrencyExchange.tcmb_date_format)
        tcmb_end_date = self.end_date_prefix + for_end_date.strftime(TCMBCurrencyExchange.tcmb_date_format)
        return_type = TCMBCurrency.type_prefix + TCMBCurrency.response_type
        key = TCMBCurrency.key_prefix + self.key
        url = TCMBCurrency.service_path + series + tcmb_start_date + tcmb_end_date + return_type + key
        #        return requests.get(url).json()
        return trtcmb.CustomHTTPAdapter.get_legacy_session().get(url).json()

    def get_single_exchange_rate(self, currency: str, for_date: datetime.date, purpose: str):
        if purpose == "for_buying":
            currency_series_data = self.inner_separator.join(
                ["TP", "DK", currency, TCMBCurrencyExchange.buying_code])
        elif purpose == "for_selling":
            currency_series_data = self.inner_separator.join(
                ["TP", "DK", currency, TCMBCurrencyExchange.selling_code])
        serie_as_list = [currency_series_data]
        # Exchange, rates, Daily, (Converted, to, TRY)
        response_dict = self.connect(datagroup_code="bie_dkdovizgn", series_list=serie_as_list,
                                     for_start_date=for_date, for_end_date=for_date)
        if response_dict.get("totalCount") == 1:
            currency_response = currency_series_data.replace(self.inner_separator,
                                                             TCMBCurrencyExchange.response_separator)
            if response_dict.get("items")[0].get(currency_response) is None:
                exchange_rate_date = datetime.datetime.strptime(response_dict.get("items")[0].get("Tarih"),
                                                                TCMBCurrencyExchange.tcmb_date_format).date() - \
                                     self.a_day
                new_dict = self.get_single_exchange_rate(currency, exchange_rate_date, purpose)
                response_dict["items"][0][currency_response] = new_dict["items"][0][currency_response]
        return response_dict
