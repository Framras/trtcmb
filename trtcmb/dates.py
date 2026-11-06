from datetime import date

import frappe
from frappe import _
from frappe.utils import add_days, get_year_start, getdate

from trtcmb.TCMBCurrencyExchange import DEFAULT_BATCH_DAYS


def resolve_import_start(
    start_date,
    today,
    *,
    last_updated=None,
    incremental: bool = False,
) -> date:
    """Return the first date to save.

    An incremental run that already has a last update continues from the next day.
    A supplied start date is used as entered. 1 January of the current year is used
    only when that date is empty.
    """
    if incremental and last_updated:
        return getdate(add_days(getdate(last_updated), 1))
    if start_date:
        return getdate(start_date)
    return getdate(get_year_start(today))


def calendar_days(start, end) -> list[date]:
    current = getdate(start)
    final_date = getdate(end)
    days: list[date] = []
    while current <= final_date:
        days.append(current)
        current = getdate(add_days(current, 1))
    return days


def iter_date_batches(from_date, to_date, batch_days: int = DEFAULT_BATCH_DAYS) -> list[tuple[date, date]]:
    """Return inclusive date windows of `batch_days` covering from_date through to_date."""
    if batch_days < 1:
        frappe.throw(_("TCMB batch size must be at least 1 day."))

    days = calendar_days(from_date, to_date)
    if not days:
        return []

    batches: list[tuple[date, date]] = []
    index = 0
    while index < len(days):
        chunk = days[index : index + batch_days]
        batches.append((chunk[0], chunk[-1]))
        index += batch_days
    return batches
