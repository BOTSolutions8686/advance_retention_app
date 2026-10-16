# Copyright (c) 2026, BOT Solutions and contributors
# For license information, please see license.txt

"""ZATCA advance payments: ksa_compliance prepayment invoices (386) settled on 388 Sales Invoices.

The advance itself is a ksa_compliance "Prepayment Invoice" Payment Entry, and the final
invoice settles it through ERPNext's standard Advances table, so ksa_compliance emits the
386 and the 388 with PrepaidAmount and prepayment references.

ksa_compliance requires the Payment Entry VAT row to be "Deduct", which ERPNext posts as
Dr tax account / Cr bank. That understates cash and books the advance VAT as a reduction
of output VAT. This module books that row to a "VAT on Advances Clearing" account and adds
two Journal Entries, keyed by their source document so they are created once:

- Prepayment Payment Entry submitted: Dr bank / Cr output VAT (VAT due on the 386).
- Sales Invoice submitted with prepayment advances: Dr output VAT / Cr clearing for the
  advance VAT now carried by the 388 (the KSA-32 amount of each allocation).

Both Journal Entries are cancelled with their source document.
"""

import frappe
from frappe import _
from frappe.utils import flt

CLEARING_ACCOUNT_NAME = "VAT on Advances Clearing"

# Combinations verified in the BOT-0143 target-version lab with ksa_compliance 0.61.11:
# company currency SAR, a single standard-rated VAT row at 15%. Anything else is refused
# until it has been tested.
SUPPORTED_CURRENCY = "SAR"
SUPPORTED_VAT_RATES = (15.0,)
SOURCE_FIELD = "custom_bot_advance_vat_source"


def get_clearing_account(company):
	return frappe.get_cached_value("Company", company, "custom_advance_vat_clearing_account")


def is_prepayment(pe):
	return pe.payment_type == "Receive" and pe.get("custom_prepayment_invoice")


# Payment Entry (386)


def validate_prepayment_entry(doc, method=None):
	if not is_prepayment(doc):
		return

	clearing = get_clearing_account(doc.company)
	if not clearing:
		frappe.throw(
			_("Set the 'Advance VAT Clearing Account' on Company {0} before recording a prepayment invoice.").format(
				doc.company
			)
		)
	if not doc.get("sales_taxes_and_charges_template"):
		frappe.throw(_("A Sales Taxes and Charges Template is required on a prepayment invoice."))

	_require_supported_currency(doc.company, doc.paid_from_account_currency, doc.paid_to_account_currency)

	# ksa_compliance takes the prepayment VAT rate from the template (ERPNext clears the
	# rate on "Actual" rows), so the template must hold one supported rate and the row's
	# amount must be the VAT inside the VAT-inclusive amount received.
	rate = template_vat_rate(doc.sales_taxes_and_charges_template)
	taxes = doc.get("taxes") or []
	supported = ", ".join(f"{r:g}%" for r in SUPPORTED_VAT_RATES)
	if rate not in SUPPORTED_VAT_RATES or len(taxes) != 1:
		frappe.throw(
			_(
				"A prepayment invoice must use a template with a single VAT rate of {0} and exactly one VAT row; "
				"other rates are not yet supported."
			).format(supported)
		)
	gross = flt(doc.paid_amount)
	expected_vat = flt(gross - gross / (1 + rate / 100), 2)
	if abs(abs(flt(taxes[0].tax_amount)) - expected_vat) > 0.01:
		frappe.throw(
			_("The VAT row on a prepayment of {0} must be {1} ({2}% included in the amount received).").format(
				frappe.format(gross, {"fieldtype": "Currency"}), frappe.format(expected_vat, {"fieldtype": "Currency"}), f"{rate:g}"
			)
		)

	for row in taxes:
		if row.account_head != clearing:
			frappe.throw(
				_("Row {0}: a prepayment invoice must book its VAT to {1}, not {2}.").format(
					row.idx, clearing, row.account_head
				)
			)


def on_submit_prepayment_entry(doc, method=None):
	if not is_prepayment(doc):
		return

	vat = flt(abs(flt(doc.total_taxes_and_charges)), 2)
	if not vat:
		return

	_make_journal_entry(
		doc.company,
		f"Payment Entry:{doc.name}",
		[
			{"account": doc.paid_to, "debit_in_account_currency": vat},
			{"account": _output_vat_account(doc), "credit_in_account_currency": vat},
		],
		doc.posting_date,
		_("Output VAT on prepayment invoice {0}").format(doc.name),
		doc.reference_no,
		doc.reference_date,
	)


def on_cancel_prepayment_entry(doc, method=None):
	_cancel_journal_entries(f"Payment Entry:{doc.name}")


# Sales Invoice (388)


def on_submit_sales_invoice(doc, method=None):
	if doc.is_return:
		return

	settled_by_account = {}
	for advance in doc.get("advances") or []:
		if advance.reference_type != "Payment Entry" or not flt(advance.allocated_amount):
			continue
		pe = frappe.get_cached_doc("Payment Entry", advance.reference_name)
		if not is_prepayment(pe) or not _uses_clearing(pe):
			# Prepayments recorded before this correction carry their VAT on the output
			# account and have no recognition entry, so there is nothing to reverse here.
			continue
		vat = advance_vat(pe, advance.allocated_amount)
		output_vat = _output_vat_account(pe)
		settled_by_account[output_vat] = flt(settled_by_account.get(output_vat, 0) + vat, 2)

	lines = []
	clearing = get_clearing_account(doc.company)
	for output_vat, vat in settled_by_account.items():
		if vat:
			lines.append({"account": output_vat, "debit_in_account_currency": vat})
			lines.append({"account": clearing, "credit_in_account_currency": vat})

	if lines:
		_make_journal_entry(
			doc.company,
			f"Sales Invoice:{doc.name}",
			lines,
			doc.posting_date,
			_("Advance VAT settled by {0}").format(doc.name),
		)


def on_cancel_sales_invoice(doc, method=None):
	_cancel_journal_entries(f"Sales Invoice:{doc.name}")


def template_vat_rate(template):
	rates = frappe.get_all(
		"Sales Taxes and Charges",
		filters={"parent": template, "parenttype": "Sales Taxes and Charges Template"},
		pluck="rate",
	)
	return flt(rates[0]) if len(rates) == 1 else None


def advance_vat(pe, allocated_amount):
	"""VAT inside a VAT-inclusive allocation, computed as ksa_compliance does for KSA-32
	(using the rate of the prepayment's Sales Taxes and Charges Template)."""
	rate = template_vat_rate(pe.sales_taxes_and_charges_template)
	if not rate:
		gross, vat = flt(pe.paid_amount), abs(flt(pe.total_taxes_and_charges))
		rate = vat * 100 / (gross - vat) if gross > vat else 0
	allocated = abs(flt(allocated_amount))
	return flt(allocated - allocated / (1 + rate / 100), 2)


def validate_sales_invoice_scope(doc, method=None):
	"""Allocating prepayments or holding a retention is supported only in the tested currency."""
	uses_prepayment = any(
		a.reference_type == "Payment Entry"
		and flt(a.allocated_amount)
		and frappe.db.get_value("Payment Entry", a.reference_name, "custom_prepayment_invoice")
		for a in doc.get("advances") or []
	)
	if uses_prepayment or doc.get("deductions"):
		_require_supported_currency(doc.company, doc.currency)

	# "Get Advances Received" also offers prepayments recorded before 16.1.0. Their VAT
	# was booked without the clearing correction, so no settlement entry is made for them.
	legacy = [
		a.reference_name
		for a in doc.get("advances") or []
		if a.reference_type == "Payment Entry"
		and flt(a.allocated_amount)
		and frappe.db.get_value("Payment Entry", a.reference_name, "custom_prepayment_invoice")
		and not _uses_clearing(frappe.get_cached_doc("Payment Entry", a.reference_name))
	]
	if legacy:
		frappe.msgprint(
			_(
				"Prepayment {0} was recorded before the advance VAT correction; no automatic VAT settlement "
				"entry will be made for it. Ask the accountant to review its VAT before submitting."
			).format(", ".join(legacy)),
			indicator="orange",
			alert=True,
		)


def _require_supported_currency(company, *currencies):
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	if company_currency != SUPPORTED_CURRENCY or any(c and c != company_currency for c in currencies):
		frappe.throw(
			_(
				"Advances and retentions are supported only in {0} (company currency); this document uses {1}."
			).format(SUPPORTED_CURRENCY, ", ".join(sorted({c for c in (company_currency, *currencies) if c})))
		)


# Retire the display-only Advance Invoice mechanism


def block_legacy_advance_invoice(doc, method=None):
	"""New or draft invoices may not use the app's Advance Invoice / allocation table.

	Those records were never ZATCA prepayment invoices. Submitted history is untouched.
	"""
	if doc.docstatus != 0:
		return
	if doc.get("invoice_type") == "Advance Invoice":
		frappe.throw(
			_(
				"Advance Invoice is retired. Record the advance as a Payment Entry with "
				"'Prepayment Invoice' ticked, then allocate it in this invoice's Advances table."
			)
		)
	if doc.get("payment_invoices"):
		frappe.throw(
			_(
				"The Advance Payment Invoices table is retired. Allocate prepayment Payment Entries "
				"in the standard Advances table instead."
			)
		)


# Helpers


def _uses_clearing(pe):
	clearing = get_clearing_account(pe.company)
	return bool(clearing) and all(row.account_head == clearing for row in pe.get("taxes") or [])


def _output_vat_account(pe):
	account = frappe.db.get_value(
		"Sales Taxes and Charges",
		{
			"parent": pe.sales_taxes_and_charges_template,
			"parenttype": "Sales Taxes and Charges Template",
		},
		"account_head",
		order_by="idx asc",
	)
	if not account:
		frappe.throw(
			_("Sales Taxes and Charges Template {0} has no tax account.").format(pe.sales_taxes_and_charges_template)
		)
	return account


def _make_journal_entry(company, source, lines, posting_date, remark, reference_no=None, reference_date=None):
	if frappe.db.exists("Journal Entry", {SOURCE_FIELD: source, "docstatus": 1}):
		return None

	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": company,
			"posting_date": posting_date,
			"cheque_no": reference_no,
			"cheque_date": reference_date if reference_no else None,
			"user_remark": remark,
			SOURCE_FIELD: source,
			"accounts": lines,
		}
	)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je.name


def _cancel_journal_entries(source):
	for name in frappe.get_all("Journal Entry", filters={SOURCE_FIELD: source, "docstatus": 1}, pluck="name"):
		je = frappe.get_doc("Journal Entry", name)
		je.flags.ignore_permissions = True
		je.cancel()
