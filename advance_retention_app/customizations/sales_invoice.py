# Copyright (c) 2025, khayam khan and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, money_in_words


@frappe.whitelist()
def get_advance_sales_invoices(customer, invoice_type):
	"""Return advance invoices for a customer that still have unallocated advance.

	Frappe v15/v16 removed aggregate expressions (for example ``SUM(tax_amount)``)
	from ``frappe.db.get_value``/``frappe.get_all``. The tax totals are therefore
	computed with an explicit ``frappe.get_all`` query followed by a Python sum,
	which behaves identically on v14, v15 and v16.
	"""
	if not customer:
		frappe.throw(_("Customer is required to fetch invoices"))

	if not invoice_type:
		frappe.throw(_("Invoice Type is required to fetch invoices"))

	sales_invoices = frappe.get_all(
		"Sales Invoice",
		filters={
			"customer": customer,
			"invoice_type": invoice_type,
			"docstatus": 1,
			"outstanding_amount": [">", 0],
		},
		fields=["name", "grand_total", "total"],
	)

	filtered_invoices = []
	for invoice in sales_invoices:
		allocated_sum = 0
		advance_money = 0

		advance_payments = frappe.get_all(
			"Advance Payments",
			filters={
				"reference_name": invoice.name,
				"which_invoice": "sales_invoice",
			},
			fields=["reference_name", "advance_amount", "allocated"],
		)

		for advance_payment in advance_payments:
			allocated_sum += flt(advance_payment.allocated)
			advance_money = flt(advance_payment.advance_amount)

		if advance_money == 0:
			advance_money = flt(invoice.grand_total)

		remaining_advance = advance_money - allocated_sum
		invoice["remaining_advance"] = remaining_advance

		if remaining_advance > 0:
			tax_rows = frappe.get_all(
				"Sales Taxes and Charges",
				filters={"parent": invoice.name, "parenttype": "Sales Invoice"},
				fields=["tax_amount", "rate"],
				order_by="idx asc",
			)
			invoice["tax_amount"] = sum(flt(row.tax_amount) for row in tax_rows)
			# Use the first tax row (by row order) deterministically; the original
			# aggregate query returned an arbitrary row's rate.
			invoice["rate"] = flt(tax_rows[0].rate) if tax_rows else 0

			filtered_invoices.append(invoice)

	return filtered_invoices


@frappe.whitelist()
def get_amount_in_english(amount_to_be_in_words, currency):
	if not amount_to_be_in_words:
		frappe.throw(_("Net Amount Due is Required"))

	amount = abs(flt(amount_to_be_in_words))
	in_words = money_in_words(amount, currency or "USD")

	currency_abbr = f"{currency} " if currency else ""
	return in_words.replace(currency_abbr, "", 1).strip()


RETENTION_ROW_DESCRIPTION = "Retention held - due later"


def apply_retention_holdback(doc, method=None):
	"""Retention is a payment-timing holdback, not a discount (owner decision D2).

	The invoice keeps its full taxable value, VAT and Payment Schedule. Once the amount
	due now is collected, ``retention.transfer_retention`` moves the retained amount from
	the invoice to the Retention Receivable account, so the invoice becomes Paid while the
	retention stays a separate, collectable customer receivable due on
	``custom_retention_due_date`` (owner decision, 2026-10-19).
	"""
	if doc.is_return and (doc.get("deductions") or doc.get("custom_retention_amount")):
		# A credit note does not carry the original invoice's retention (copied by make_sales_return).
		doc.set("deductions", [])
		doc.custom_retention_amount = 0
		doc.custom_retention_due_date = None

	rows = doc.get("deductions") or []
	if any(flt(row.deduction_amount) < 0 for row in rows):
		frappe.throw(_("Retention amounts cannot be negative."))
	retention = flt(sum(flt(row.deduction_amount) for row in rows), doc.precision("grand_total"))
	doc.custom_retention_amount = retention

	_set_net_amount_due(doc, retention)

	# Earlier versions added a retention row to the Payment Schedule; never keep one.
	if any(row.description == RETENTION_ROW_DESCRIPTION for row in doc.get("payment_schedule") or []):
		doc.set("payment_schedule", [])
		doc.set_payment_schedule()
		doc.set_due_date()

	if not retention:
		return
	if doc.is_return or doc.is_pos or doc.get("is_opening") == "Yes":
		frappe.throw(_("Retention holdback is not supported on returns, POS or opening invoices."))
	if not doc.custom_retention_due_date:
		frappe.throw(_("Retention Due Date is required when a retention is held."))

	payable = _expected_schedule_total(doc)
	if retention > payable:
		# Equal is allowed: advances may already cover the whole amount due now.
		frappe.throw(
			_("Retention {0} cannot exceed the amount payable on this invoice ({1}).").format(
				frappe.format(retention, {"fieldtype": "Currency"}), frappe.format(payable, {"fieldtype": "Currency"})
			)
		)
	if doc.due_date and getdate(doc.custom_retention_due_date) <= getdate(doc.due_date):
		frappe.throw(
			_("Retention Due Date must be after the invoice due date ({0}).").format(
				frappe.format(getdate(doc.due_date), {"fieldtype": "Date"})
			)
		)


def _expected_schedule_total(doc):
	"""The total ERPNext requires the payment schedule to equal (mirrors validate_payment_schedule_amount)."""
	grand_total = flt(doc.get("rounded_total") or doc.grand_total) - flt(doc.write_off_amount)
	if doc.get("total_advance"):
		if doc.get("party_account_currency", doc.company_currency) == doc.company_currency:
			base_grand_total = flt(doc.get("base_rounded_total") or doc.base_grand_total) - flt(doc.base_write_off_amount)
			grand_total = (base_grand_total - flt(doc.total_advance)) / (flt(doc.conversion_rate) or 1)
		else:
			grand_total -= flt(doc.total_advance)
	return flt(grand_total, doc.precision("grand_total"))


def _set_net_amount_due(doc, retention):
	"""Server-side values for the app's print fields; VAT and taxable totals are untouched."""
	invoice_total = flt(doc.get("rounded_total") or doc.grand_total)
	# ERPNext advances (prepayment Payment Entries allocated on this invoice) are what
	# actually settle the receivable; the app's own allocation table is display-only
	# and is used only when no ERPNext advance is allocated.
	advances = flt(doc.get("total_advance")) or flt(doc.get("vat_including_allocated_total"))
	net_for_period = flt(invoice_total - advances, doc.precision("grand_total"))
	doc.net_invoice_for_the_period_total = net_for_period
	doc.amount_to_be_in_words = flt(net_for_period - retention, doc.precision("grand_total"))
	doc.in_words_english = get_amount_in_english(doc.amount_to_be_in_words, doc.currency) if doc.amount_to_be_in_words else ""
