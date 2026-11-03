from datetime import datetime, time

import frappe
from frappe.utils import get_time, getdate, now_datetime

from trtcmb.api import run_currency_exchange_import

DEFAULT_RUN_TIME = time(0, 58)


def import_due_companies():
    now = now_datetime()
    today = getdate(now)
    companies = frappe.get_all(
        "TR TCMB EVDS Integration Company Setting",
        filters={"enable": 1},
        fields=["name", "daily_run_time", "last_updated"],
    )
    for company in companies:
        if not company_import_is_due(now, company.daily_run_time, company.last_updated, today):
            continue
        frappe.enqueue(
            run_currency_exchange_import,
            queue="long",
            timeout=3600,
            company=company.name,
            incremental=True,
            enqueue_after_commit=False,
            job_id=f"trtcmb-daily-{frappe.scrub(company.name)}-{today}",
            deduplicate=True,
        )


def every_day_at_00_58():
    """Kept so an older Scheduled Job Type can still call this method."""
    import_due_companies()


def company_import_is_due(now: datetime, daily_run_time, last_updated, today=None) -> bool:
    today = today or getdate(now)
    scheduled = get_time(daily_run_time) if daily_run_time else DEFAULT_RUN_TIME
    if now.time() < scheduled:
        return False
    if last_updated and getdate(last_updated) >= today:
        return False
    return True
