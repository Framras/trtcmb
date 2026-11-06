import frappe

LEGACY_COLUMNS = ("kiymet", "kiymet_adet", "kiymet_fiyat")


def execute() -> None:
    """Store Kıymet as text and leave the Journal Entry balance columns in place.

    Link and Data use the same varchar column, so existing names stay. Fonlar can
    be removed later without changing the rows Menkul Kıymet Bakiyesi reads.
    """
    if frappe.db.exists("Custom Field", "Journal Entry-kiymet"):
        frappe.db.set_value(
            "Custom Field",
            "Journal Entry-kiymet",
            {"fieldtype": "Data", "options": None, "read_only": 1},
            update_modified=False,
        )

    columns = set(frappe.db.get_table_columns("Journal Entry"))
    missing = [column for column in LEGACY_COLUMNS if column not in columns]
    if missing:
        frappe.throw(
            frappe._("Journal Entry is missing legacy balance columns: {0}").format(", ".join(missing))
        )
