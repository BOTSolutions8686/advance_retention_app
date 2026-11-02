import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    fields = [
        dict(
            fieldname="custom_bot_retention_principal",
            label="Retention Principal Held",
            fieldtype="Currency",
            read_only=1,
            insert_after="custom_retention_amount",
        ),
        dict(
            fieldname="custom_bot_retention_vat",
            label="Retention VAT Portion Held",
            fieldtype="Currency",
            read_only=1,
            insert_after="custom_bot_retention_principal",
            description="Payment holdback only. Full invoice VAT remains reported.",
        ),
        dict(
            fieldname="custom_bot_advance_snapshot",
            label="Advance Allocation Audit",
            no_copy=1,
            fieldtype="Long Text",
            read_only=1,
            hidden=1,
        ),
        dict(
            fieldname="custom_bot_credit_adjustments",
            label="Credit Settlement Adjustments",
            no_copy=1,
            fieldtype="Long Text",
            read_only=1,
            hidden=1,
        ),
        dict(
            fieldname="custom_bot_reverse_settlement",
            label="Reverse Advance and Retention Allocations",
            fieldtype="Check",
            default="0",
            insert_after="return_against",
            depends_on="eval:doc.is_return",
            description="Restore the credited proportion of prepayments to customer credit; carry the references in the credit-note XML.",
        ),
    ]
    for field in fields:
        field["module"] = "Advance Retention App"
    create_custom_fields({"Sales Invoice": fields}, update=True)
    create_custom_fields(
        {
            "Sales Invoice Additional Fields": [
                dict(
                    fieldname="custom_bot_submitted_xml",
                    label="Original Submitted XML",
                    fieldtype="Long Text",
                    ignore_xss_filter=1,
                    read_only=1,
                    hidden=1,
                    no_copy=1,
                    module="Advance Retention App",
                ),
                dict(
                    fieldname="custom_bot_clearance_verified",
                    label="Returned Clearance Verified",
                    fieldtype="Check",
                    read_only=1,
                    no_copy=1,
                    module="Advance Retention App",
                ),
            ]
        },
        update=True,
    )
    frappe.clear_cache()
