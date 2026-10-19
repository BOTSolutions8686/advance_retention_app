# Copyright (c) 2026, BOT Solutions and contributors
# For license information, please see license.txt

"""Retentions transferred from Sales Invoices, aged on the retention due date.

The standard Accounts Receivable report does not age Journal Entry rows by their due
date, so retention balances are reported here: one row per transfer Journal Entry.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	report_date = getdate(filters.report_date)
	account = frappe.db.get_value("Company", filters.company, "custom_retention_receivable_account")
	if not account:
		return columns(), []

	conditions, values = "", {"account": account, "company": filters.company, "report_date": report_date}
	if filters.customer:
		conditions = " and ret.party = %(customer)s"
		values["customer"] = filters.customer

	rows = frappe.db.sql(
		f"""
		select je.name as transfer, je.custom_bot_retention_invoice as invoice, ret.party as customer,
			je.posting_date, je.due_date as retention_due_date, ret.debit_in_account_currency as retained,
			(select ifnull(sum(ple.amount), 0) from `tabPayment Ledger Entry` ple
				where ple.delinked = 0 and ple.account = %(account)s and ple.posting_date <= %(report_date)s
				and ple.against_voucher_type = 'Journal Entry' and ple.against_voucher_no = je.name) as outstanding
		from `tabJournal Entry` je
		join `tabJournal Entry Account` ret on ret.parent = je.name and ret.account = %(account)s
			and ret.debit_in_account_currency > 0
		where je.docstatus = 1 and je.company = %(company)s and je.posting_date <= %(report_date)s
			and ifnull(je.custom_bot_retention_invoice, '') != '' {conditions}
		order by je.due_date, je.name""",
		values,
		as_dict=True,
	)

	data = []
	for r in rows:
		r.outstanding = flt(r.outstanding)
		r.collected = flt(r.retained) - r.outstanding
		if not r.outstanding and not filters.show_collected:
			continue
		age = date_diff(report_date, r.retention_due_date) if r.retention_due_date else 0
		r.days_overdue = max(age, 0) if r.outstanding else 0
		r.not_due = r.outstanding if age <= 0 else 0
		r.range_0_30 = r.outstanding if 0 < age <= 30 else 0
		r.range_31_90 = r.outstanding if 30 < age <= 90 else 0
		r.range_91_180 = r.outstanding if 90 < age <= 180 else 0
		r.range_181_above = r.outstanding if age > 180 else 0
		data.append(r)
	return columns(), data


def columns():
	return [
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
		{"label": _("Sales Invoice"), "fieldname": "invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 170},
		{"label": _("Transfer"), "fieldname": "transfer", "fieldtype": "Link", "options": "Journal Entry", "width": 160},
		{"label": _("Retention Due"), "fieldname": "retention_due_date", "fieldtype": "Date", "width": 110},
		{"label": _("Retained"), "fieldname": "retained", "fieldtype": "Currency", "width": 120},
		{"label": _("Collected"), "fieldname": "collected", "fieldtype": "Currency", "width": 120},
		{"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Currency", "width": 120},
		{"label": _("Days Overdue"), "fieldname": "days_overdue", "fieldtype": "Int", "width": 100},
		{"label": _("Not Due"), "fieldname": "not_due", "fieldtype": "Currency", "width": 110},
		{"label": _("0-30"), "fieldname": "range_0_30", "fieldtype": "Currency", "width": 110},
		{"label": _("31-90"), "fieldname": "range_31_90", "fieldtype": "Currency", "width": 110},
		{"label": _("91-180"), "fieldname": "range_91_180", "fieldtype": "Currency", "width": 110},
		{"label": _("181+"), "fieldname": "range_181_above", "fieldtype": "Currency", "width": 110},
	]
