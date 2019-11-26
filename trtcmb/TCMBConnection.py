import frappe
import requests
from requests import HTTPError
from requests.auth import HTTPBasicAuth
import json
from trtcmb.TCMBCurrency import TCMBCurrency
import datetime


class TCMBConnection:
    def __init__(self):
        self._s = requests.Session()
        self.a_day = datetime.timedelta(days=1)
        self.doctype = "Currency"
        self.integration_setting_doctype = "TR TCMB EVDS Integration Setting"
        self.company_setting_doctype = "TR TCMB EVDS Integration Company Setting"
        # global settings
        self.service_path = frappe.db.get_single_value(self.integration_setting_doctype, "service_path")
        self.try_code = frappe.db.get_single_value(self.integration_setting_doctype, "try_code")
        self.buying_code = frappe.db.get_single_value(self.integration_setting_doctype, "buying_code")
        self.selling_code = frappe.db.get_single_value(self.integration_setting_doctype, "selling_code")
        self.type = frappe.db.get_single_value(self.integration_setting_doctype, "type")
        self.company = frappe.defaults.get_user_default("Company")
        # company settings
        self.enable = frappe.db.get_value(self.company_setting_doctype, self.company, "enable")
        self.key = frappe.db.get_value(self.company_setting_doctype, self.company, "key")
        self.last_updated = frappe.db.get_value(self.company_setting_doctype, self.company, "last_updated")
        self.date_of_establishment = frappe.db.get_value(self.company_setting_doctype, self.company,
                                                         "date_of_establishment")

    def connect(self, integration: str):
        # Exchange, rates, Daily, (Converted, to, TRY)
        if integration == "bie_dkdovizgn" and self.enable == 1:
            series = ""
            series_prefix = "TP.DK."
            for currency in TCMBCurrency.get_list_of_enabled_currencies():
                if not series == "":
                    series = series + "-" + series_prefix + currency.get("currency_name")
                else:
                    series = "/series=" + series_prefix + currency.get("currency_name")

            start_date = "&startDate="
            if self.last_updated is None or \
                    self.last_updated < datetime.date(1950, 1, 2) or \
                    self.date_of_establishment in None or \
                    self.date_of_establishment < datetime.date(1950, 1, 2):
                start_date = self.date_of_establishment

            end_date = "&endDate=" + datetime.date.today() - self.a_day
            return_type = "&type=" + self.type
            key = "&key=" + self.key

            url = self.service_path + series + start_date + end_date + return_type + key

            try:
                r = self._s.request(method=servicemethod, url=url, headers=self.headers, params=params,
                                    data=servicedata, auth=HTTPBasicAuth(username, password))
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
