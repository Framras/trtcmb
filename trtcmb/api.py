import frappe
from frappe import _

from trtcmb.TCMBConnection import TCMBConnection


@frappe.whitelist()
def initiate_currency_exchange_rates(company: str | None = None):
    frappe.has_permission("Currency Exchange", ptype="write", throw=True)
    company = company or frappe.defaults.get_user_default("Company")
    if not company:
        frappe.throw(_("Select a company before initiating TCMB EVDS integration."))

    enqueue_currency_exchange_import(
        company,
        incremental=False,
        job_id=f"trtcmb-import-{frappe.scrub(company)}",
        after_commit=True,
    )
    frappe.msgprint(
        _("TCMB exchange rates are being imported in 5-day batches in the background."),
        alert=True,
        indicator="blue",
    )
    return "queued"


def enqueue_currency_exchange_import(
    company: str, *, incremental: bool, job_id: str, after_commit: bool
) -> None:
    frappe.enqueue(
        run_currency_exchange_import,
        queue="long",
        timeout=3600,
        company=company,
        incremental=incremental,
        enqueue_after_commit=after_commit,
        job_id=job_id,
        deduplicate=True,
    )


def run_currency_exchange_import(company: str, incremental: bool = False):
    TCMBConnection(company=company).get_exchange_rates_for_enabled_currencies(incremental=incremental)
