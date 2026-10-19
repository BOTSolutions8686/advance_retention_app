# Copyright (c) 2025, BOT Solutions and Contributors

import json
import os

import frappe
from frappe.utils import now_datetime

APP_MODULE = "Advance Retention App"

# Sales Invoice fieldnames created by this app's Custom Field fixtures. They are
# not "custom_"-prefixed (kept for compatibility with existing print formats and
# data), so they must not already exist on the target site.
APP_FIELDNAMES = (
	"invoice_type",
	"advance_invoices_section",
	"get_advance_sales_payment",
	"payment_invoices",
	"vat_exclusive_allocated_total",
	"vat_including_allocated_total",
	"vat_on_allocated",
	"amount_to_be_in_words",
	"net_invoice_for_the_period_total",
	"in_words_english",
	"in_words_arabic",
	"custom_retentions_and_retentions",
	"deductions",
	"custom_total_deductions_and_retentions",
	"custom_column_break_vnklc",
	"custom_retention_amount",
	"custom_retention_due_date",
)

# Property Setters shipped up to 16.0.1 that relabelled the standard Additional
# Discount fields as "Deductions". Retention is no longer booked as a discount.
DISCOUNT_RELABEL_PROPERTY_SETTERS = (
	"Sales Invoice-discount_amount-Label",
	"Sales Invoice-apply_discount_on-label",
	"Sales Invoice-base_discount_amount-label",
	"Sales Invoice-base_discount_amount-hidden",
	"Sales Invoice-additional_discount_account-label",
	"Sales Invoice-additional_discount_percentage-label",
	"Sales Invoice-additional_discount_percentage-read_only",
	"Sales Invoice-additional_discount_percentage-hidden",
)

# Records written by earlier revisions with module=None, so `uninstall-app` and
# fixture sync never removed them. The field_order snapshot replaced the whole
# Sales Invoice layout; the tab break depended on it.
LEGACY_PROPERTY_SETTERS = ("Sales Invoice-main-field_order", "Sales Invoice-base_discount_amount-hidden")
LEGACY_CUSTOM_FIELDS = ("deductions_and_retentions_tab_break",)


def before_install():
	"""Refuse to install over Sales Invoice fields owned by ERPNext, another app or the site."""
	meta = frappe.get_meta("Sales Invoice")
	conflicts = []
	for fieldname in APP_FIELDNAMES:
		if not meta.has_field(fieldname):
			continue
		owner = frappe.db.get_value(
			"Custom Field", {"dt": "Sales Invoice", "fieldname": fieldname}, ["name", "module"], as_dict=True
		)
		if owner and owner.module == APP_MODULE:
			continue
		conflicts.append(f"{fieldname} ({'Custom Field ' + owner.name if owner else 'standard field'})")

	if conflicts:
		frappe.throw(
			"advance_retention_app cannot be installed: these Sales Invoice fieldnames already exist: "
			+ ", ".join(conflicts),
			title="Sales Invoice field conflict",
		)


def remove_legacy_layout():
	"""Remove the whole-form field_order override and related records left by earlier revisions.

	The field_order Property Setter is only removed when it is the snapshot shipped
	by earlier revisions, identified by the tab break that only existed there. A
	layout the site saves after installing 16.0.1+ also lists this app's fields, so
	that alone must not be treated as app-owned.
	"""
	field_order = frappe.db.get_value(
		"Property Setter", "Sales Invoice-main-field_order", ["value", "module"], as_dict=True
	)
	if field_order:
		try:
			order = json.loads(field_order.value or "[]")
		except ValueError:
			order = []
		if field_order.module == APP_MODULE or "deductions_and_retentions_tab_break" in order:
			frappe.delete_doc("Property Setter", "Sales Invoice-main-field_order", ignore_permissions=True, force=True)

	hidden = frappe.db.get_value(
		"Property Setter", "Sales Invoice-base_discount_amount-hidden", ["value", "module"], as_dict=True
	)
	if hidden and not hidden.module and hidden.value == "1":
		frappe.delete_doc("Property Setter", "Sales Invoice-base_discount_amount-hidden", ignore_permissions=True, force=True)

	for name in LEGACY_CUSTOM_FIELDS:
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)

	frappe.clear_cache(doctype="Sales Invoice")


def before_uninstall():
	"""Archive data that `uninstall-app` would drop, then remove legacy layout records.

	`uninstall-app` drops the Advance Payments and Sales Deduction tables, so the
	allocation and deduction history of submitted invoices is exported to a JSON
	file in the site's private backups folder first. Sales Invoice columns of the
	removed custom fields and the 'Deductions And Retentions' account (which may
	carry GL entries) are intentionally kept.
	"""
	archive = {"app": "advance_retention_app", "created": str(now_datetime()), "tables": {}}
	for doctype in ("Advance Payments", "Sales Deduction"):
		if frappe.db.table_exists(doctype):
			archive["tables"][doctype] = frappe.db.sql(f"select * from `tab{doctype}`", as_dict=True)

	backup_dir = frappe.get_site_path("private", "backups")
	os.makedirs(backup_dir, exist_ok=True)
	path = os.path.join(backup_dir, f"advance_retention_app_uninstall_{now_datetime():%Y%m%d_%H%M%S}.json")
	with open(path, "w") as f:
		json.dump(archive, f, default=str, indent=1)
	print(f"Archived advance_retention_app child-table data to {path}")

	remove_legacy_layout()


def remove_discount_relabels():
	"""Restore the standard Additional Discount fields on sites upgraded from <= 16.0.1.

	Only this app's own records (module "Advance Retention App") are removed. The
	'Deductions And Retentions' expense account created by earlier versions is left in
	place because it may carry GL entries; it is no longer used for retentions.
	"""
	for name in DISCOUNT_RELABEL_PROPERTY_SETTERS:
		if frappe.db.get_value("Property Setter", name, "module") == APP_MODULE:
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype="Sales Invoice")


def after_install():
	setup_advance_vat_clearing_accounts()


def setup_advance_vat_clearing_accounts():
	"""Create 'VAT on Advances Clearing' under Duties and Taxes for each company and set it on the Company.

	Idempotent: an existing account or an already configured company is left as it is.
	"""
	from advance_retention_app.customizations.prepayment import CLEARING_ACCOUNT_NAME

	# after_install hooks and post-model-sync patches run before fixtures are synced,
	# so make sure the Company and Journal Entry custom fields exist first.
	if not frappe.get_meta("Company").has_field("custom_advance_vat_clearing_account"):
		from frappe.utils.fixtures import sync_fixtures

		sync_fixtures("advance_retention_app")
		frappe.clear_cache(doctype="Company")

	for company in frappe.get_all("Company", fields=["name", "abbr"]):
		if frappe.db.get_value("Company", company.name, "custom_advance_vat_clearing_account"):
			continue

		account = frappe.db.get_value("Account", {"company": company.name, "account_name": CLEARING_ACCOUNT_NAME})
		if not account:
			parent = frappe.db.get_value(
				"Account", {"company": company.name, "account_name": "Duties and Taxes", "is_group": 1}
			)
			if not parent:
				print(f"No 'Duties and Taxes' group for {company.name}; set the Advance VAT Clearing Account manually.")
				continue
			account = (
				frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": CLEARING_ACCOUNT_NAME,
						"parent_account": parent,
						"company": company.name,
						"account_type": "Tax",
						"is_group": 0,
					}
				)
				.insert(ignore_permissions=True)
				.name
			)

		frappe.db.set_value("Company", company.name, "custom_advance_vat_clearing_account", account)
		frappe.clear_document_cache("Company", company.name)
		print(f"Advance VAT clearing account for {company.name}: {account}")
