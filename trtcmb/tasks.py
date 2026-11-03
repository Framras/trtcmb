import frappe

from trtcmb.api import run_currency_exchange_import


def every_day_at_00_58():
    companies = frappe.get_all(
        "TR TCMB EVDS Integration Company Setting",
        filters={"enable": 1},
        fields=["name"],
    )
    for company in companies:
        run_currency_exchange_import(company=company.name, incremental=True)
