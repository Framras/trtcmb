import frappe
from trtcmb.TCMBConnection import TCMBConnection


@frappe.whitelist()
def initiate_currency_exchange_rates():
    cercon = TCMBConnection()
    return cercon.connect("bie_dkdovizgn")
