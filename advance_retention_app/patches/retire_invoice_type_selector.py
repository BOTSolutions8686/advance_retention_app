"""Apply retired workflow metadata without deleting historical fields or values."""
import json
from pathlib import Path
import frappe


def execute():
    names = {
        "invoice_type", "advance_invoices_section", "get_advance_sales_payment",
        "payment_invoices", "vat_exclusive_allocated_total",
        "vat_including_allocated_total", "vat_on_allocated",
    }
    fixture = Path(frappe.get_app_path("advance_retention_app", "fixtures", "custom_field.json"))
    for definition in json.loads(fixture.read_text()):
        if definition.get("dt") != "Sales Invoice" or definition.get("fieldname") not in names:
            continue
        name = frappe.db.get_value("Custom Field", {"dt": "Sales Invoice", "fieldname": definition["fieldname"]}, "name")
        if name:
            field = frappe.get_doc("Custom Field", name)
            for key in ("hidden", "read_only", "reqd", "default", "no_copy", "in_list_view", "in_standard_filter", "depends_on", "description", "label"):
                if key in definition:
                    field.set(key, definition[key])
            field.save(ignore_permissions=True)
    frappe.clear_cache(doctype="Sales Invoice")
