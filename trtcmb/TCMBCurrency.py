import frappe


class TCMBCurrency:
    doctype = "Currency"

    @classmethod
    def get_list_of_enabled_currencies(cls):
        currency_list = frappe.get_all(cls.doctype, filters={"enabled": 1}, fields=["currency_name"])
        return currency_list
