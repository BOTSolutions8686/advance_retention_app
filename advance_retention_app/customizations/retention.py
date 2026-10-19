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
cancelled) it is never recreated automatically. Concurrent triggers (a payment and the
scheduler, or two workers) are serialised on the invoice row and re-checked with locking
reads; a transfer that would duplicate another is refused at submission.

The transfer is dated when the invoice outstanding last changed (the settling payment's
posting date), so as-of reports move the retention on the day the amount due now was paid.

Only customer settlements collect the amount due now: Payment Entries (including allocated
prepayments) and Journal Entries through a Bank or Cash account. A credit note, write-off or
other non-cash adjustment changes what the customer owes, and whether the retention is still
owed is a commercial decision; such invoices are put On Hold and are never transferred
automatically. An Accounts Manager decides (retransfer_retention).
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


def _existing_transfer_locked(invoice, exclude=None, include_cancelled=True):
	"""An existing transfer, read with a lock so concurrent writers see each other."""
	rows = frappe.db.sql(
		"""select name from `tabJournal Entry` where custom_bot_retention_invoice = %s
		and docstatus in %s and name != %s limit 1 for update""",
		(invoice, (1, 2) if include_cancelled else (1,), exclude or ""),
	)
	return rows[0][0] if rows else None


def _settled_on(invoice, posting_date):
	"""The date the invoice outstanding last changed, from the Payment Ledger."""
	last = frappe.db.sql(
		"""select max(posting_date) from `tabPayment Ledger Entry`
		where delinked = 0 and against_voucher_type = 'Sales Invoice' and against_voucher_no = %s""",
		invoice,
	)[0][0]
	return max(getdate(posting_date), getdate(last or posting_date))


def non_cash_reductions(invoice, as_of=None):
	"""Vouchers other than customer settlements that reduced the invoice outstanding, with the amount."""
	conditions, values = "", [invoice, invoice]
	if as_of:
		conditions, values = " and posting_date <= %s", values + [getdate(as_of)]
	rows = frappe.db.sql(
		f"""select voucher_type, voucher_no, sum(amount) as amount from `tabPayment Ledger Entry`
		where delinked = 0 and against_voucher_type = 'Sales Invoice' and against_voucher_no = %s
		and voucher_no != %s{conditions} group by voucher_type, voucher_no""",
		values,
		as_dict=True,
	)
	found = []
	for row in rows:
		if row.voucher_type == "Payment Entry" or flt(row.amount) >= 0:
			continue
		if row.voucher_type == "Journal Entry" and (
			frappe.db.get_value("Journal Entry", row.voucher_no, TRANSFER_FIELD) or _through_bank_or_cash(row.voucher_no)
		):
			continue
		found.append(frappe._dict(voucher_type=row.voucher_type, voucher_no=row.voucher_no, amount=-flt(row.amount)))
	return found


def _through_bank_or_cash(journal_entry):
	return bool(
		frappe.db.sql(
			"""select 1 from `tabJournal Entry Account` jea join `tabAccount` a on a.name = jea.account
			where jea.parent = %s and a.account_type in ('Bank', 'Cash') limit 1""",
			journal_entry,
		)
	)


def transfer_retention(invoice, manual=False):
	"""Create the transfer when the invoice's outstanding has fallen to the retained amount.

	Automatic triggers never recreate a cancelled transfer and never transfer an invoice whose
	outstanding was reduced by a credit note or other non-cash adjustment; an Accounts Manager
	can (retransfer_retention).
	"""
	si = frappe.get_doc("Sales Invoice", invoice)
	retention = flt(si.get("custom_retention_amount"))
	if si.docstatus != 1 or si.is_return or not retention:
		return None

	# Serialise on the invoice row; the locking reads below see other committed transfers.
	locked = frappe.db.sql(
		"select outstanding_amount from `tabSales Invoice` where name = %s for update", invoice
	)
	if _existing_transfer_locked(invoice, include_cancelled=not manual):
		return None
	if not manual and non_cash_reductions(invoice):
		return None

	outstanding = flt(locked[0][0])
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
			"posting_date": _settled_on(invoice, si.posting_date),
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


@frappe.whitelist()
def retransfer_retention(invoice):
	"""Accountant's decision for a held retention (after a cancelled transfer or a credit note)."""
	frappe.only_for("Accounts Manager")
	frappe.has_permission("Sales Invoice", "read", invoice, throw=True)
	name = transfer_retention(invoice, manual=True)
	if not name:
		frappe.throw(_("Nothing to transfer: the invoice has an active transfer, or its amount due now is not yet collected."))
	return name


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


def before_submit_journal_entry(doc, method=None):
	invoice = doc.get(TRANSFER_FIELD)
	if not invoice:
		return
	frappe.db.sql("select name from `tabSales Invoice` where name = %s for update", invoice)
	other = _existing_transfer_locked(invoice, exclude=doc.name, include_cancelled=False)
	if other:
		frappe.throw(_("Invoice {0} already has a retention transfer ({1}).").format(invoice, other))


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


def _ledger_outstanding(voucher_type, voucher_no, account, as_of=None):
	conditions, values = "", [account, voucher_type, voucher_no]
	if as_of:
		conditions, values = " and posting_date <= %s", values + [getdate(as_of)]
	return flt(
		frappe.db.sql(
			f"""select ifnull(sum(amount), 0) from `tabPayment Ledger Entry`
			where delinked = 0 and account = %s and against_voucher_type = %s and against_voucher_no = %s{conditions}""",
			values,
		)[0][0]
	)


def retention_status(invoice, as_of=None):
	"""Retention state of a submitted invoice, derived from the Payment Ledger.

	Before transfer the retention is the part of the invoice outstanding up to the retained
	amount; after transfer it is the outstanding of the transfer Journal Entry. The native
	invoice status is not touched.
	"""
	si = frappe.db.get_value(
		"Sales Invoice",
		invoice,
		["docstatus", "debit_to", "custom_retention_amount", "custom_retention_due_date", "currency"],
		as_dict=True,
	)
	retention = flt(si and si.custom_retention_amount)
	if not si or si.docstatus != 1 or not retention:
		return None

	transfer = get_transfer(invoice)
	if transfer and as_of and getdate(frappe.db.get_value("Journal Entry", transfer, "posting_date")) > getdate(as_of):
		transfer = None
	if transfer:
		row = frappe.db.get_value(
			"Journal Entry Account",
			{"parent": transfer, "debit_in_account_currency": [">", 0]},
			["account", "debit_in_account_currency"],
			as_dict=True,
		)
		outstanding = _ledger_outstanding("Journal Entry", transfer, row.account, as_of)
	else:
		outstanding = min(retention, max(_ledger_outstanding("Sales Invoice", invoice, si.debit_to, as_of), 0))

	adjustments = [] if transfer else non_cash_reductions(invoice, as_of)
	if adjustments:
		# Not collected: an accountant decides whether the retention is still owed.
		status = "On Hold" if outstanding > TOLERANCE else "Credited"
	elif outstanding <= TOLERANCE:
		status = "Paid"
	elif outstanding >= retention - TOLERANCE:
		status = "Unpaid"
	else:
		status = "Partly Paid"
	due = si.custom_retention_due_date
	return frappe._dict(
		status=status,
		retention=retention,
		outstanding=outstanding,
		collected=0 if adjustments else retention - outstanding,
		adjustments=adjustments,
		credited=sum(a.amount for a in adjustments),
		due_date=due,
		overdue=bool(not adjustments and outstanding > TOLERANCE and due and getdate(due) < getdate(as_of or nowdate())),
		transfer=transfer,
		currency=si.currency,
		can_retransfer=bool(
			not as_of
			and not transfer
			and outstanding > TOLERANCE
			and flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount")) <= retention + TOLERANCE
			and (adjustments or get_transfer(invoice, include_cancelled=True))
		),
	)


@frappe.whitelist()
def get_retention_status(invoice):
	frappe.has_permission("Sales Invoice", "read", invoice, throw=True)
	return retention_status(invoice)


def retention_outstanding(invoice):
	"""Retention not yet collected, for print formats."""
	state = retention_status(invoice)
	return state.outstanding if state else flt(frappe.db.get_value("Sales Invoice", invoice, "custom_retention_amount"))
