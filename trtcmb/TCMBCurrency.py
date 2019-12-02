import frappe
import requests
import json


class TCMBCurrency:
    doctype = "Currency"
    company_doctype = "Company"
    type = "json"
    serielist_path = "/serieList"
    code_prefix = "/code="
    key_prefix = "&key="
    type_prefix = "&type="
    datagroup_code = "bie_dkdovizgn"

    company_setting_doctype = "TR TCMB EVDS Integration Company Setting"
    integration_setting_doctype = "TR TCMB EVDS Integration Setting"

    service_path = frappe.db.get_single_value(integration_setting_doctype, "service_path")

    @classmethod
    def get_list_of_enabled_currencies(cls):
        # ERPNext enabled currencies
        currency_list = frappe.get_all(cls.doctype, filters={"enabled": 1}, fields=["currency_name"])
        # TCMB enabled currencies
        key = frappe.db.get_value(cls.company_setting_doctype, frappe.defaults.get_user_default(cls.company_doctype),
                                  "key")
        url = ""
        # Exchange, rates, Daily, (Converted, to, TRY)
        code = cls.code_prefix + cls.datagroup_code
        return_type = cls.type_prefix + cls.type
        key = cls.key_prefix + key

        url = cls.service_path + cls.serielist_path + code + return_type + key

        tcmb_data_series = requests.get(url).json()
        tcmb_currency_list = []
        for tcmb_data_serie in tcmb_data_series:
            tcmb_currency_serie = tcmb_data_serie.get("SERIE_CODE").split(".")
            if tcmb_currency_serie[3] in ["A", "S"]:
                if tcmb_currency_serie[2] not in tcmb_currency_list:
                    tcmb_currency_list.append(tcmb_currency_serie[2])

        for currency in currency_list:
            if not currency.get("currency_name") in tcmb_currency_list:
                currency_list.remove(currency)

        return currency_list
