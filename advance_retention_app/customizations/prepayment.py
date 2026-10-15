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

	for row in doc.get("taxes") or []:
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


def advance_vat(pe, allocated_amount):
	"""VAT inside a VAT-inclusive allocation, computed as ksa_compliance does for KSA-32."""
	rate = flt(pe.taxes[0].rate) if pe.get("taxes") else 0
	if not rate:
		gross, vat = flt(pe.paid_amount), abs(flt(pe.total_taxes_and_charges))
		rate = vat * 100 / (gross - vat) if gross > vat else 0
	allocated = abs(flt(allocated_amount))
	return flt(allocated - allocated / (1 + rate / 100), 2)


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
