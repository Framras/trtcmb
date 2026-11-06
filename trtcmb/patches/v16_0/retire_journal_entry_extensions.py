import frappe

OLD_REPORT = "Gayrımenkul Kıymet Bakiyesi"
NEW_REPORT = "Menkul Kıymet Bakiyesi"

# Shipped with the app. Other Journal Entry property setters on a site are left in place.
PROPERTY_SETTERS = (
    "Journal Entry-bill_no-in_global_search",
    "Journal Entry-bill_no-in_standard_filter",
    "Journal Entry-remark-in_standard_filter",
    "Journal Entry-naming_series-options",
    "Journal Entry-title-in_standard_filter",
    "Journal Entry-search_fields",
    "Journal Entry-total_credit-in_list_view",
    "Journal Entry-cheque_no-in_list_view",
    "Journal Entry-cheque_date-in_list_view",
    "Journal Entry-posting_date-in_list_view",
)

CUSTOM_PERMS = (
    "8614764eb4",
    "22b84bc8af",
    "b955887805",
    "bf6c88d873",
)


def execute() -> None:
    """Drop Journal Entry form customizations and keep the legacy balance columns.

    The kıymet and brand columns stay as read-only custom fields so a later
    trim of unused columns does not drop the historic values the balance report reads.
    """
    _rename_report()
    _delete_if_present("Property Setter", PROPERTY_SETTERS + _search_field_setters())
    _delete_if_present("Custom DocPerm", CUSTOM_PERMS)


def clear_meta_cache() -> None:
    frappe.clear_cache(doctype="Journal Entry")
    frappe.clear_cache(doctype="Journal Entry Account")


def _rename_report() -> None:
    if frappe.db.exists("Report", OLD_REPORT) and not frappe.db.exists("Report", NEW_REPORT):
        frappe.rename_doc("Report", OLD_REPORT, NEW_REPORT, force=True)
    if frappe.db.exists("Report", NEW_REPORT):
        frappe.db.set_value("Report", NEW_REPORT, "report_name", NEW_REPORT, update_modified=False)


def _search_field_setters() -> tuple[str, ...]:
    # Property Setter autoname stores an empty field as "main", so the exported name does not match.
    return tuple(
        frappe.get_all(
            "Property Setter",
            filters={"doc_type": "Journal Entry", "property": "search_fields"},
            pluck="name",
        )
    )


def _delete_if_present(doctype: str, names: tuple[str, ...]) -> None:
    for name in names:
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
