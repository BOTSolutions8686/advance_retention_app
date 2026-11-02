import frappe
from frappe.utils import flt
from advance_retention_app.customizations.settlement import summary


def execute(filters=None):
    filters = frappe._dict(filters or {})
    query = {"docstatus": 1}
    if filters.company:
        query["company"] = filters.company
    if filters.invoice:
        query["name"] = filters.invoice
    columns = [
        dict(
            label="Invoice",
            fieldname="invoice",
            fieldtype="Link",
            options="Sales Invoice",
            width=190,
        ),
        dict(
            label="Original Invoice",
            fieldname="source",
            fieldtype="Link",
            options="Sales Invoice",
            width=190,
        ),
    ]
    for name, label in [
        ("gross", "Invoice Total"),
        ("invoice_vat", "Full VAT"),
        ("prepaid", "Advance Adjustment"),
        ("principal", "Retention Principal"),
        ("retention_vat", "Retention VAT Held"),
        ("due_now", "Due Now / Settlement Credit"),
        ("xml_payable", "XML Payable"),
        ("qr_amount", "QR Amount"),
        ("qr_vat", "QR VAT"),
    ]:
        columns.append(
            dict(
                label=label,
                fieldname=name,
                fieldtype="Currency",
                options="currency",
                width=150,
            )
        )
    columns.extend(
        [
            dict(
                label="Currency",
                fieldname="currency",
                fieldtype="Link",
                options="Currency",
                hidden=1,
            ),
            dict(label="QR Check", fieldname="check", fieldtype="Data", width=160),
        ]
    )
    data = []
    # get_list preserves user/role/company permissions. This is not an unrestricted export.
    for row in frappe.get_list(
        "Sales Invoice",
        filters=query,
        fields=[
            "name",
            "is_return",
            "custom_retention_amount",
            "custom_bot_advance_snapshot",
            "custom_bot_credit_adjustments",
        ],
        limit_page_length=0,
        order_by="posting_date desc, name desc",
    ):
        if not (
            row.custom_retention_amount
            or row.custom_bot_advance_snapshot not in (None, "", "{}")
            or row.custom_bot_credit_adjustments
        ):
            continue
        s = summary(row.name)
        s.invoice = row.name
        s.xml_payable = flt(s.xml.get("PayableAmount"))
        s.qr_amount = flt(s.qr.get("4"))
        s.qr_vat = flt(s.qr.get("5"))
        s.check = (
            "Matches signed XML"
            if s.qr
            and abs(s.qr_amount - s.xml_payable) < 0.005
            and abs(s.qr_vat - flt(s.get("xml_vat"))) < 0.005
            else "Review QR / XML"
        )
        if row.is_return:
            for key in (
                "gross",
                "invoice_vat",
                "prepaid",
                "principal",
                "retention_vat",
                "due_now",
                "xml_payable",
                "qr_amount",
                "qr_vat",
            ):
                s[key] = -s[key]
        data.append(s)
    return columns, data
