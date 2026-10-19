# Copyright (c) 2026, BOT Solutions and contributors
# For license information, please see license.txt

"""Retention transfer: the invoice becomes Paid once the amount due now is collected.

Owner decision (2026-10-19): the Sales Invoice itself must show Paid after the current
amount is collected, while unpaid retention stays a separate, collectable customer
receivable. The invoice keeps its full value and VAT (ZATCA unchanged). When its
outstanding falls to the retained amount, a Journal Entry moves that amount from the
invoice's receivable account to the company's Retention Receivable account:

    Dr Retention Receivable (customer)   retention, due on the retention due date
    Cr Debtors (customer, against the invoice)   retention

The retention is later collected with a Payment Entry against that Journal Entry.
Each invoice gets at most one automatic transfer: once a transfer exists (submitted or
cancelled) it is never recreated automatically.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

TRANSFER_FIELD = "custom_bot_retention_invoice"
TOLERANCE = 0.005


def get_retention_account(company):
	return frappe.db.get_value("Company", company, "custom_retention_receivable_account")


def get_transfer(invoice, include_cancelled=False):
	statuses = [1, 2] if include_cancelled else [1]
	return frappe.db.get_value(
		"Journal Entry", {TRANSFER_FIELD: invoice, "docstatus": ["in", statuses]}, "name", order_by="creation desc"
	)


def transfer_retention(invoice):
	"""Create the transfer when the invoice's outstanding has fallen to the retained amount."""
	si = frappe.get_doc("Sales Invoice", invoice)
	retention = flt(si.get("custom_retention_amount"))
	if si.docstatus != 1 or si.is_return or not retention:
		return None
	if get_transfer(invoice, include_cancelled=True):
		return None

	outstanding = flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount"))
	if outstanding > retention + TOLERANCE or outstanding <= TOLERANCE:
		# The amount due now is not yet collected, or the invoice is already settled.
		return None

	account = get_retention_account(si.company)
	if not account:
		frappe.throw(_("Set the 'Retention Receivable Account' on Company {0}.").format(si.company))

	amount = flt(min(retention, outstanding), si.precision("grand_total"))
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": si.company,
			"posting_date": max(getdate(si.posting_date), getdate(nowdate())),
			"due_date": si.custom_retention_due_date,
			"user_remark": _("Retention held on {0}, due {1}, transferred to Retention Receivable").format(
				si.name, frappe.format(si.custom_retention_due_date, {"fieldtype": "Date"})
			),
			TRANSFER_FIELD: si.name,
			"accounts": [
				{
					"account": account,
					"party_type": "Customer",
					"party": si.customer,
					"debit_in_account_currency": amount,
				},
				{
					"account": si.debit_to,
					"party_type": "Customer",
					"party": si.customer,
					"credit_in_account_currency": amount,
					"reference_type": "Sales Invoice",
					"reference_name": si.name,
				},
			],
		}
	)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je.name


# Triggers


def on_submit_sales_invoice(doc, method=None):
	# Advances that cover the amount due now settle it at submission.
	transfer_retention(doc.name)


def on_submit_payment_entry(doc, method=None):
	for ref in doc.get("references") or []:
		if ref.reference_doctype == "Sales Invoice" and flt(ref.allocated_amount):
			transfer_retention(ref.reference_name)


def on_submit_journal_entry(doc, method=None):
	if doc.get(TRANSFER_FIELD):
		return
	for row in doc.get("accounts") or []:
		if row.reference_type == "Sales Invoice" and row.reference_name:
			transfer_retention(row.reference_name)


def transfer_due_retentions():
	"""Hourly: catches settlements made through Payment Reconciliation or other routes."""
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={"docstatus": 1, "is_return": 0, "custom_retention_amount": [">", 0], "outstanding_amount": [">", 0]},
		fields=["name", "outstanding_amount", "custom_retention_amount"],
	)
	for inv in invoices:
		if flt(inv.outstanding_amount) <= flt(inv.custom_retention_amount) + TOLERANCE:
			try:
				transfer_retention(inv.name)
				frappe.db.commit()
			except Exception:
				frappe.db.rollback()
				frappe.log_error(title=f"advance_retention_app: retention transfer failed for {inv.name}")


# Guards


def before_cancel_journal_entry(doc, method=None):
	if not doc.get(TRANSFER_FIELD):
		return
	collected = frappe.db.sql(
		"""select voucher_type, voucher_no from `tabPayment Ledger Entry`
		where delinked = 0 and against_voucher_type = 'Journal Entry' and against_voucher_no = %s
		and voucher_no != %s limit 1""",
		(doc.name, doc.name),
		as_dict=True,
	)
	if collected:
		frappe.throw(
			_("Retention on this transfer has been collected by {0} {1}. Cancel that collection first.").format(
				collected[0].voucher_type, collected[0].voucher_no
			)
		)


def validate_sales_invoice(doc, method=None):
	if doc.is_return and doc.return_against and get_transfer(doc.return_against):
		frappe.throw(
			_(
				"Invoice {0} has its retention transferred to Retention Receivable ({1}). "
				"Have the accountant cancel that transfer before issuing a credit note."
			).format(doc.return_against, get_transfer(doc.return_against))
		)


def before_cancel_sales_invoice(doc, method=None):
	transfer = get_transfer(doc.name)
	if transfer:
		frappe.throw(_("Cancel the retention transfer {0} before cancelling this invoice.").format(transfer))


def retention_outstanding(invoice):
	"""Retention not yet collected, for print formats: transferred balance, or the held amount before transfer."""
	retention = flt(frappe.db.get_value("Sales Invoice", invoice, "custom_retention_amount"))
	transfer = get_transfer(invoice)
	if not transfer:
		return retention
	account = frappe.db.get_value("Journal Entry Account", {"parent": transfer, "debit_in_account_currency": [">", 0]}, "account")
	return flt(
		frappe.db.sql(
			"""select ifnull(sum(amount), 0) from `tabPayment Ledger Entry`
			where delinked = 0 and account = %s and against_voucher_type = 'Journal Entry' and against_voucher_no = %s""",
			(account, transfer),
		)[0][0]
	)
