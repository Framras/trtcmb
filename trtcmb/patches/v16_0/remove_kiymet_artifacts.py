import frappe

KIYMET_REPORTS = (
    "Gayrımenkul Kıymet Bakiyesi",
    "Menkul Kıymet Bakiyesi",
)

KIYMET_CUSTOM_FIELDS = (
    "Journal Entry-kiymet",
    "Journal Entry-kiymet_adet",
    "Journal Entry-kiymet_fiyat",
)


def execute() -> None:
    """Remove kıymet Custom Fields and Menkul/Gayrımenkul Kıymet Bakiyesi reports.

    Does not DROP columns on tabJournal Entry; historic cell values may remain until
    a separate schema trim. Does not touch Journal Entry Account brand.
    """
    for name in KIYMET_REPORTS:
        if frappe.db.exists("Report", name):
            frappe.delete_doc("Report", name, force=True, ignore_permissions=True)

    for name in KIYMET_CUSTOM_FIELDS:
        if frappe.db.exists("Custom Field", name):
            frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)

    frappe.clear_cache(doctype="Journal Entry")
