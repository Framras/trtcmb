import frappe
from frappe import _

from trtcmb.TCMBConnection import TCMBConnection


@frappe.whitelist()
def initiate_currency_exchange_rates(company: str | None = None):
    frappe.has_permission("Currency Exchange", ptype="write", throw=True)
    company = company or frappe.defaults.get_user_default("Company")
    if not company:
        frappe.throw(_("Select a company before initiating TCMB EVDS integration."))

    frappe.enqueue(
        run_currency_exchange_import,
        queue="long",
        timeout=3600,
        company=company,
        incremental=False,
        enqueue_after_commit=True,
        job_id=f"trtcmb-import-{frappe.scrub(company)}",
        deduplicate=True,
    )
    frappe.msgprint(
        _("TCMB exchange rates are being imported in 5-day batches in the background."),
        alert=True,
        indicator="blue",
    )
    return "queued"


def run_currency_exchange_import(company: str, incremental: bool = False):
    TCMBConnection(company=company).get_exchange_rates_for_enabled_currencies(
        datagroup_code="bie_dkdovizgn",
        incremental=incremental,
    )
