import frappe
from trtcmb.TCMBConnection import TCMBConnection


@frappe.whitelist()
def initiate_currency_exchange_rates():
    tcmb_connection = TCMBConnection()
    return tcmb_connection.get_exchange_rates_for_enabled_currencies(datagroup_code="bie_dkdovizgn")
