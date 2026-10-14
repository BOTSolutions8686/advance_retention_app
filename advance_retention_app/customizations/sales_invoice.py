# Copyright (c) 2025, BOT Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, money_in_words


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
				filters={"parent": invoice.name},
				fields=["tax_amount", "rate"],
			)
			invoice["tax_amount"] = sum(flt(row.tax_amount) for row in tax_rows)
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
