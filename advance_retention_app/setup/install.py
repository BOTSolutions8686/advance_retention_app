# Copyright (c) 2025, BOT Solutions and Contributors

import frappe


def after_install():
	create_retentions_and_deductions_account()


def create_retentions_and_deductions_account():
	"""Create a 'Deductions And Retentions' expense account for every company.

	Idempotent and safe to re-run: skips companies that already have the account
	or that do not have the expected parent account. Works on Frappe v14/v15/v16.
	"""
	print("Creating 'Deductions And Retentions' account...")

	companies = frappe.get_all("Company", fields=["name", "abbr", "default_currency"])

	if not companies:
		print("No company exists to create the account.")
		return

	account_name = "Deductions And Retentions"

	for company in companies:
		parent_account = f"Indirect Expenses - {company.abbr}"

		if frappe.db.exists("Account", {"account_name": account_name, "company": company.name}):
			print(f"Account '{account_name}' already exists for company: {company.name}")
			continue

		if not frappe.db.exists("Account", parent_account):
			print(f"Parent account '{parent_account}' was not found for company: {company.name}; skipping.")
			continue

		try:
			account_doc = frappe.get_doc({
				"doctype": "Account",
				"root_type": "Expense",
				"account_name": account_name,
				"parent_account": parent_account,
				"account_currency": company.default_currency,
				"freeze_account": "No",
				"is_group": 0,
				"company": company.name,
			})

			account_doc.insert(ignore_permissions=True)
			print(f"Account '{account_name}' created successfully for company: {company.name}")
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"advance_retention_app: failed to create '{account_name}' for {company.name}",
			)
			print(f"Failed to create account for company {company.name}")

	frappe.db.commit()
