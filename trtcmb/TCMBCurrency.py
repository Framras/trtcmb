import frappe


class TCMBCurrency:
    @classmethod
    def get_list_of_enabled_currencies(self):
        currency_list = list()
        currency_list = frappe.get_all(self.doctype, filters={"enabled": 1}, fields=["currency_name"])
        return currency_list
