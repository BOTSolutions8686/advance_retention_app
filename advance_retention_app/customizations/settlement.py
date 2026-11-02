"""Settlement-aware corrections. The tax invoice retains its full taxable value.

No cash refund is implicit: reversing a recovered advance restores customer credit.
Amounts/references are calculated from the source invoice, never accepted from a caller.
"""

import json
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.utils import flt


def money(value):
    return float(
        Decimal(str(value or 0)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    )


def _loads(value):
    return json.loads(value) if value else {}


def source_allocations(doc, use_snapshot=True):
    stored = _loads(doc.get("custom_bot_advance_snapshot"))
    if stored and use_snapshot:
        return stored
    out = {}
    for row in doc.get("advances") or []:
        if row.reference_type == "Payment Entry" and frappe.db.get_value(
            "Payment Entry", row.reference_name, "custom_prepayment_invoice"
        ):
            out[row.reference_name] = money(
                out.get(row.reference_name, 0) + flt(row.allocated_amount)
            )
    return out


def _previous_returns(original, exclude=None):
    return frappe.get_all(
        "Sales Invoice",
        filters={
            "return_against": original,
            "is_return": 1,
            "docstatus": 1,
            "name": ["!=", exclude or ""],
        },
        fields=["name", "net_total", "custom_bot_credit_adjustments"],
    )


def before_validate(doc, method=None):
    if not doc.is_return:
        if doc.docstatus == 0:
            doc.custom_bot_advance_snapshot = json.dumps(
                source_allocations(doc, use_snapshot=False), sort_keys=True
            )
        return
    doc.custom_bot_advance_snapshot = None
    if not doc.get("custom_bot_reverse_settlement"):
        doc.custom_bot_credit_adjustments = None
        return
    if not doc.return_against:
        frappe.throw(
            _("An original invoice is required to reverse settlement allocations.")
        )
    original = frappe.get_doc("Sales Invoice", doc.return_against)
    if (
        original.company != doc.company
        or original.customer != doc.customer
        or original.currency != doc.currency
    ):
        frappe.throw(
            _(
                "The credit note must have the same company, customer and currency as its original invoice."
            )
        )
    if original.docstatus != 1 or original.is_return:
        frappe.throw(
            _("Settlement reversal requires a submitted original sales invoice.")
        )
    # ERPNext cannot allocate Payment Entries on a return. References are carried
    # separately, and restored through its supported unreconciliation operation.
    doc.set("advances", [])
    doc.update_outstanding_for_self = 0


def validate(doc, method=None, *, require_reason=True):
    if not doc.is_return or not doc.get("custom_bot_reverse_settlement"):
        return
    if require_reason and not doc.get("custom_return_reason"):
        frappe.throw(_("A credit note reason is required for settlement reversal."))
    original = frappe.get_doc("Sales Invoice", doc.return_against)
    from advance_retention_app.customizations.retention import get_transfer

    if get_transfer(original.name):
        frappe.throw(
            _(
                "Cancel the original invoice retention transfer before reversing its settlement. Collected retention must be reconciled first."
            )
        )
    base = abs(flt(original.net_total))
    if not base:
        frappe.throw(_("A zero-value original invoice has no settlement to reverse."))
    from advance_retention_app.customizations.prepayment import (
        _require_supported_currency,
    )

    _require_supported_currency(doc.company, doc.currency)
    if (
        len(original.taxes) != 1
        or len(doc.taxes) != 1
        or flt(original.taxes[0].rate) != 15
        or flt(doc.taxes[0].rate) != 15
    ):
        frappe.throw(
            _("Settlement credits require the original single 15% VAT treatment.")
        )
    if flt(original.discount_amount) or flt(doc.discount_amount):
        frappe.throw(_("Reconcile invoice discounts before using settlement reversal."))
    previous = _previous_returns(original.name, doc.name)
    # Mixing ordinary and settlement-aware credits makes the source allocation
    # balance ambiguous. Refuse rather than guess what a previous credit reversed.
    if any(not row.custom_bot_credit_adjustments for row in previous):
        frappe.throw(
            _(
                "Earlier credit notes need settlement reconciliation before using this reversal."
            )
        )
    prior_net = sum(abs(flt(r.net_total)) for r in previous)
    credit_net = abs(flt(doc.net_total))
    if prior_net + credit_net > base + 0.005:
        frappe.throw(_("Cumulative credit exceeds the original invoice value."))
    ratio = min((prior_net + credit_net) / base, 1)
    prior = [_loads(r.custom_bot_credit_adjustments) for r in previous]
    allocations = source_allocations(original)
    restored = {
        pe: money(
            money(amount * ratio) - sum(p.get("advances", {}).get(pe, 0) for p in prior)
        )
        for pe, amount in allocations.items()
    }
    principal = money(
        original.get("custom_bot_retention_principal")
        or original.get("custom_retention_amount")
    )
    vat = money(original.get("custom_bot_retention_vat"))
    ret_principal = money(
        money(principal * ratio) - sum(p.get("retention_principal", 0) for p in prior)
    )
    ret_vat = money(money(vat * ratio) - sum(p.get("retention_vat", 0) for p in prior))
    from advance_retention_app.customizations.prepayment import advance_vat

    vat_restored = {}
    for pe, amount in restored.items():
        from advance_retention_app.customizations.prepayment import (
            _uses_clearing,
            template_vat_rate,
        )

        payment = frappe.get_doc("Payment Entry", pe)
        if (
            not _uses_clearing(payment)
            or template_vat_rate(payment.sales_taxes_and_charges_template) != 15
        ):
            frappe.throw(
                _(
                    "Legacy prepayments require VAT reconciliation before settlement reversal."
                )
            )
        cumulative = amount + sum(p.get("advances", {}).get(pe, 0) for p in prior)
        vat_restored[pe] = money(
            advance_vat(frappe.get_doc("Payment Entry", pe), cumulative)
            - sum(p.get("advance_vat", {}).get(pe, 0) for p in prior)
        )
    adjustments = {
        "original": original.name,
        "advances": restored,
        "advance_vat": vat_restored,
        "retention_principal": ret_principal,
        "retention_vat": ret_vat,
    }
    if (
        any(a < -0.005 for a in restored.values())
        or ret_principal < -0.005
        or ret_vat < -0.005
    ):
        frappe.throw(
            _(
                "Settlement reversal balance is inconsistent; reconcile earlier credits first."
            )
        )
    doc.update_outstanding_for_self = 0
    doc.custom_bot_credit_adjustments = json.dumps(adjustments, sort_keys=True)
    doc.net_invoice_for_the_period_total = money(
        flt(doc.get("rounded_total") or doc.grand_total) + sum(restored.values())
    )
    doc.amount_to_be_in_words = money(
        doc.net_invoice_for_the_period_total + ret_principal + ret_vat
    )
    from advance_retention_app.customizations.sales_invoice import get_amount_in_english

    doc.in_words_english = (
        get_amount_in_english(doc.amount_to_be_in_words, doc.currency)
        if doc.amount_to_be_in_words
        else ""
    )
    doc.in_words_arabic = ""


def before_submit(doc, method=None):
    if not doc.is_return or not doc.get("custom_bot_reverse_settlement"):
        return
    frappe.db.sql(
        "select name from `tabSales Invoice` where name=%s for update",
        doc.return_against,
    )
    # Recompute under lock to make concurrent/partial credits safe.
    validate(doc)
    original = frappe.get_doc("Sales Invoice", doc.return_against)
    if not original.get("custom_bot_advance_snapshot"):
        original.db_set(
            "custom_bot_advance_snapshot",
            json.dumps(source_allocations(original), sort_keys=True),
        )
    adj = _loads(doc.custom_bot_credit_adjustments)
    from erpnext.accounts.utils import reconcile_against_document

    for pe_name, release in sorted(adj["advances"].items()):
        if release <= 0:
            continue
        frappe.db.sql(
            "select name from `tabPayment Entry` where name=%s for update", pe_name
        )
        pe = frappe.get_doc("Payment Entry", pe_name)
        if pe.company != doc.company or pe.party != doc.customer or pe.docstatus != 1:
            frappe.throw(
                _("The original prepayment is no longer valid for this customer.")
            )
        allocated = money(
            sum(
                flt(r.allocated_amount)
                for r in pe.references
                if r.reference_doctype == "Sales Invoice"
                and r.reference_name == original.name
            )
        )
        if release > allocated + 0.005:
            frappe.throw(
                _(
                    "Prepayment allocation changed; reload the original invoice before reversing."
                )
            )
        unrecon = frappe.get_doc(
            {
                "doctype": "Unreconcile Payment",
                "company": doc.company,
                "voucher_type": "Payment Entry",
                "voucher_no": pe_name,
            }
        )
        unrecon.add_references()
        unrecon.set(
            "allocations",
            [
                r
                for r in unrecon.allocations
                if r.reference_doctype == "Sales Invoice"
                and r.reference_name == original.name
            ],
        )
        if not unrecon.allocations:
            frappe.throw(_("The original prepayment allocation could not be found."))
        unrecon.insert()
        unrecon.submit()
        remaining = money(allocated - release)
        if remaining:
            pe.reload()
            original.reload()
            reconcile_against_document(
                [
                    frappe._dict(
                        voucher_type="Payment Entry",
                        voucher_no=pe_name,
                        voucher_detail_no=None,
                        against_voucher_type="Sales Invoice",
                        against_voucher=original.name,
                        account=original.debit_to,
                        party_type="Customer",
                        party=doc.customer,
                        is_advance="Yes",
                        dr_or_cr="credit_in_account_currency",
                        unadjusted_amount=pe.unallocated_amount,
                        unreconciled_amount=pe.unallocated_amount,
                        allocated_amount=remaining,
                        exchange_rate=1,
                        difference_amount=0,
                        outstanding_amount=original.outstanding_amount,
                    )
                ]
            )


def on_submit(doc, method=None):
    if not doc.is_return or not doc.get("custom_bot_reverse_settlement"):
        return
    from advance_retention_app.customizations import prepayment as pp

    adj = _loads(doc.custom_bot_credit_adjustments)
    lines = []
    for pe_name, amount in adj["advances"].items():
        pe = frappe.get_doc("Payment Entry", pe_name)
        if pp._uses_clearing(pe):
            vat = adj["advance_vat"][pe_name]
            lines.extend(
                [
                    {
                        "account": pp.get_clearing_account(doc.company),
                        "debit_in_account_currency": vat,
                    },
                    {
                        "account": pp._output_vat_account(pe),
                        "credit_in_account_currency": vat,
                    },
                ]
            )
    if lines:
        pp._make_journal_entry(
            doc.company,
            "Sales Invoice:" + doc.name,
            lines,
            doc.posting_date,
            _("Advance VAT restored to customer credit by {0}").format(doc.name),
        )
    # ERPNext may leave a copied negative outstanding on a fully applied return.
    # Recalculate from the Payment Ledger rather than editing a balance directly.
    from erpnext.accounts.utils import update_voucher_outstanding

    update_voucher_outstanding(
        "Sales Invoice", doc.name, doc.debit_to, "Customer", doc.customer
    )


def before_cancel(doc, method=None):
    if (
        doc.is_return
        and doc.get("custom_bot_reverse_settlement")
        and doc.docstatus == 1
    ):
        frappe.throw(
            _(
                "Reverse a submitted settlement credit with a reviewed debit note; do not cancel restored advances."
            )
        )


def effective_retention(invoice, as_of=None):
    original = (
        frappe.db.get_value("Sales Invoice", invoice, "custom_retention_amount") or 0
    )
    filters = {"return_against": invoice, "docstatus": 1, "is_return": 1}
    if as_of:
        filters["posting_date"] = ["<=", as_of]
    credited = 0
    for row in frappe.get_all(
        "Sales Invoice", filters=filters, pluck="custom_bot_credit_adjustments"
    ):
        adj = _loads(row)
        credited += adj.get("retention_principal", 0) + adj.get("retention_vat", 0)
    return max(money(original - credited), 0)


@frappe.whitelist()
def make_settlement_credit(invoice):
    frappe.has_permission("Sales Invoice", "read", invoice, throw=True)
    frappe.has_permission("Sales Invoice", "create", throw=True)
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

    doc = make_sales_return(invoice)
    doc.custom_bot_reverse_settlement = 1
    before_validate(doc)
    from advance_retention_app.customizations.sales_invoice import (
        apply_retention_holdback,
    )

    apply_retention_holdback(doc)
    validate(doc, require_reason=False)
    return doc


def summary(invoice):
    """Read-only print and reconciliation view of source, settlement and signed data."""
    import base64
    from lxml import etree

    doc = frappe.get_doc("Sales Invoice", invoice)
    adj = _loads(doc.get("custom_bot_credit_adjustments"))
    advances = adj.get("advances", {}) if adj else source_allocations(doc)
    principal = adj.get(
        "retention_principal",
        doc.get("custom_bot_retention_principal")
        or doc.get("custom_retention_amount")
        or 0,
    )
    vat = adj.get("retention_vat", doc.get("custom_bot_retention_vat") or 0)
    siaf_name = frappe.db.get_value(
        "Sales Invoice Additional Fields",
        {"invoice_doctype": "Sales Invoice", "sales_invoice": invoice, "is_latest": 1},
        "name",
    )
    result = frappe._dict(
        currency=doc.currency,
        source=doc.return_against,
        is_return=doc.is_return,
        taxable=abs(money(doc.net_total)),
        invoice_vat=abs(money(doc.total_taxes_and_charges)),
        gross=abs(money(doc.grand_total)),
        advances=advances,
        prepaid=money(sum(advances.values())),
        principal=principal,
        retention_vat=vat,
        due_now=abs(money(doc.amount_to_be_in_words)),
        xml={},
        qr={},
        validation=None,
        qr_image=None,
        seller={},
        buyer={},
        lines=[],
    )
    if siaf_name:
        siaf = frappe.get_doc("Sales Invoice Additional Fields", siaf_name)
        result.integration_status = siaf.integration_status
        result.clearance_verified = bool(siaf.get("custom_bot_clearance_verified"))
        result.zatca_environment = frappe.db.get_value(
            "ZATCA Business Settings",
            {"company": doc.company, "status": "Active"},
            "fatoora_server",
        )
        result.validation = siaf.validation_messages
        if siaf.invoice_xml:
            ns = {
                "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
                "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            }
            root = etree.fromstring(siaf.invoice_xml.encode())
            result.xml = {
                x.tag.split("}")[1]: x.text
                for x in root.find("cac:LegalMonetaryTotal", ns)
            }
            result.xml_vat = root.findtext("cac:TaxTotal/cbc:TaxAmount", namespaces=ns)
            for key, party in [
                ("seller", "AccountingSupplierParty"),
                ("buyer", "AccountingCustomerParty"),
            ]:
                prefix = "cac:" + party + "/cac:Party/"
                result[key] = {
                    "name": root.findtext(
                        prefix + "cac:PartyLegalEntity/cbc:RegistrationName",
                        namespaces=ns,
                    )
                    or "",
                    "vat": root.findtext(
                        prefix + "cac:PartyTaxScheme/cbc:CompanyID", namespaces=ns
                    )
                    or "",
                    "address": " ".join(
                        root.findtext(
                            prefix + "cac:PostalAddress/cbc:" + f, namespaces=ns
                        )
                        or ""
                        for f in [
                            "BuildingNumber",
                            "StreetName",
                            "CitySubdivisionName",
                            "CityName",
                            "PostalZone",
                        ]
                    ),
                }
            for item in doc.items:
                result.lines.append(
                    {
                        "description": item.item_name or item.description,
                        "quantity": abs(flt(item.qty)),
                        "rate": abs(flt(item.rate)),
                        "net": abs(flt(item.net_amount)),
                    }
                )
        if siaf.qr_code:
            data = base64.b64decode(siaf.qr_code)
            i = 0
            while i < len(data):
                if i + 2 > len(data):
                    raise ValueError("Truncated QR TLV")
                tag, length = data[i], data[i + 1]
                i += 2
                value = data[i : i + length]
                i += length
                if len(value) != length:
                    raise ValueError("Truncated QR value")
                if tag in (4, 5):
                    result.qr[str(tag)] = value.decode()
            result.qr_image = siaf.qr_image_src
    from advance_retention_app.customizations.prepayment import advance_vat

    result.advance_vat = (
        money(sum(adj.get("advance_vat", {}).values()))
        if adj
        else money(
            sum(
                advance_vat(frappe.get_doc("Payment Entry", pe), amount)
                for pe, amount in advances.items()
            )
        )
    )
    result.advance_net = money(result.prepaid - result.advance_vat)
    result.net_after_advance = money(result.taxable - result.advance_net)
    result.vat_after_advance = money(result.invoice_vat - result.advance_vat)
    return result


@frappe.whitelist()
def get_settlement_summary(invoice):
    frappe.has_permission("Sales Invoice", "read", invoice, throw=True)
    return summary(invoice)
