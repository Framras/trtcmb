import frappe
import requests


class TCMBCurrency:
    doctype = "Currency"
    company_doctype = "Company"
    response_type = "json"
    serielist_path = "/serieList"
    code_prefix = "/code="
    type_prefix = "&type="
    datagroup_code = "bie_dkdovizgn"
    company_setting_doctype = "TR TCMB EVDS Integration Company Setting"
    integration_setting_doctype = "TR TCMB EVDS Integration Setting"
    service_path = frappe.db.get_single_value(integration_setting_doctype, "service_path")

    @classmethod
    def get_list_of_enabled_currencies(cls):
        # Fetch the 'name' field (which holds ISO codes like USD, EUR), not 'currency_name'
        currency_list = frappe.get_all(cls.doctype, filters={"enabled": 1, "name": ['not in', ['TRY', 'XAU']]},
                                       fields=["name"])

        key = frappe.db.get_value(cls.company_setting_doctype, frappe.defaults.get_user_default(cls.company_doctype),
                                  "key")
        code = cls.code_prefix + cls.datagroup_code
        return_type = cls.type_prefix + cls.response_type

        # Use .strip() to clean any accidental whitespace from the user settings
        url = cls.service_path.strip().rstrip('/') + cls.serielist_path + code + return_type

        headers = {
            'key': key,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            frappe.throw(f"TCMB API Error {response.status_code}: {response.text[:250]}")

        tcmb_data_series = response.json()

        tcmb_currency_list = []
        for tcmb_data_item in tcmb_data_series:
            tcmb_currency_data = tcmb_data_item.get("SERIE_CODE").split(".")
            if tcmb_currency_data[3] in ["A", "S"]:
                if tcmb_currency_data[2] not in tcmb_currency_list:
                    tcmb_currency_list.append(tcmb_currency_data[2])

        # Safely filter out ERPNext currencies not supported by TCMB
        valid_currency_list = [c for c in currency_list if c.get("name") in tcmb_currency_list]

        return valid_currency_list