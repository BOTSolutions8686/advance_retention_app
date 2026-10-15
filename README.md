<div align="center" markdown="1">
	<h2>Advance Retention App</h2>
	<p align="center">
	    <p></p>
	</p>

[botsolutions.tech](https://botsolutions.tech/)

</div>

---

A custom Frappe/ERPNext application that introduces **Advance Invoice** payment and
**deduction/retention** handling on the Sales Invoice. It adds Sales Invoice custom
fields, property setters and the `Invoice Type` / `Deduction Type` master doctypes,
plus child tables for advance-payment allocation and deductions.

This is a **Frappe v16–compatible** port of
[`khayamkhan852/advance_retention_app`](https://github.com/khayamkhan852/advance_retention_app)
(upstream `main` at `43b6b39`), originally written by khayam khan and released under the MIT licence.

> **Status: draft — not for live invoicing in Saudi Arabia (ZATCA Phase 2).**
>
> - **Advances (open blocker):** allocating an Advance Invoice on the final invoice only changes the app's
>   display fields. ERPNext and the ZATCA XML still carry the full final amount with no prepaid amount, so VAT
>   on the advanced portion is declared twice and receivables are overstated until settled separately. The
>   settlement method is not yet decided.
> - **Retentions (resolved in 16.0.2):** a retention is a payment-timing holdback. The invoice keeps its full
>   taxable value and VAT, the full amount stays in the customer receivable, and the retained amount is
>   scheduled as a later "Retention held - due later" payment-schedule installment. No discount, allowance or
>   expense is booked.

## Compatibility

| Item | Value |
| --- | --- |
| Frappe / ERPNext | v16 (also runs on v14/v15) |
| Python | >= 3.10 |
| Required apps | `erpnext` (declared in `hooks.py` as `required_apps`) |

### Changes made for v16

- **Removed aggregate query.** `frappe.db.get_value(..., ["SUM(tax_amount)", "rate"])`
  was removed in Frappe v15+. Tax totals are now computed with an explicit
  `frappe.get_all("Sales Taxes and Charges", ...)` query and a Python sum
  (`advance_retention_app/customizations/sales_invoice.py`).
- **Desk API.** `frappe.client.get_list` in the Sales Invoice client script was
  replaced by `frappe.db.get_list` (Promise-based) with an explicit `limit: 0`.
- **`required_apps = ["erpnext"]`** added so bench installs the correct dependency order.
- **Idempotent install.** `after_install` now skips companies that already have the
  account, checks the parent account exists, sets `account_currency`, and logs errors
  instead of silently swallowing them.
- **Packaging.** `pyproject.toml` declares `requires-python = ">=3.10"`; app version
  bumped to `16.0.0`.

### Changes in 16.0.1

- **No whole-form layout override.** The `Sales Invoice-main-field_order` Property Setter
  fixture (a snapshot of an older Sales Invoice layout that omitted v16 fields and was
  re-applied on every `bench migrate`) and the tab break that depended on it were removed.
  Custom fields are now anchored to fields that exist in ERPNext v16:
  the Advance Invoices section after `has_subcontracted`, the net-amount fields after
  `rounded_total`, and the Retentions and Deductions section before Additional Discount.
- **Upgrade patch.** `remove_legacy_layout` deletes the app-shipped field_order snapshot
  (only when it contains this app's fields), the module-less `base_discount_amount` hidden
  setter and the old tab break on sites that installed an earlier revision.
- **Field-conflict guard.** `before_install` refuses to install when any of the app's
  Sales Invoice fieldnames (for example `invoice_type`, `deductions`) already exists as a
  standard field or another owner's Custom Field.
- **Uninstall archive.** `before_uninstall` exports the Advance Payments and Sales
  Deduction rows to `sites/<site>/private/backups/advance_retention_app_uninstall_*.json`
  before `uninstall-app` drops those tables.
- All Property Setter fixtures now belong to the app module so uninstall removes them.
- Advance lookup reads the tax rate from the first tax row by row order.

## Retentions (16.0.2)

Add rows to the **Retentions** table on the Sales Invoice and set **Retention Due Date**. On save the app:

- totals the rows into **Retention Held (due later)**;
- keeps the full taxable value, VAT and receivable (no discount, ZATCA allowance or expense);
- reduces the existing payment-schedule installments by the retained amount and adds a later-dated
  installment for it, then re-runs ERPNext's own schedule validations;
- sets **Net Amount Due** (invoice total less allocated advances less retention) and its English words.

The retention due date must be after the last installment. With a Payment Terms Template the invoice due
date moves to the retention date, so ERPNext's credit-days check applies: only users with the
Accounts Settings *Credit Controller* role can save such an invoice. Retentions are not supported on returns,
POS or opening invoices.

## Installation

1. Install and set up a bench (Frappe/ERPNext) by following the
   [Frappe installation guide](https://frappeframework.com/docs/user/en/installation).
2. From the bench directory:

	```
	bench get-app advance_retention_app https://github.com/BOTSolutions8686/advance_retention_app.git
	bench --site <your-site> install-app advance_retention_app
	```

3. Run any pending migrations and clear cache:

	```
	bench --site <your-site> migrate
	bench --site <your-site> clear-cache
	```

## Uninstall / rollback

```
bench --site <your-site> uninstall-app advance_retention_app
bench --site <your-site> clear-cache
```

`uninstall-app` removes the app's doctypes, custom fields and property setters and
drops the Advance Payments and Sales Deduction tables (their rows are archived to a JSON
file first). It does **not** restore the site to its pre-install state:

- the database columns of the removed Sales Invoice custom fields keep their values;
- a `Deductions And Retentions` account created by versions up to 16.0.1 is kept because it
  may carry GL entries.

Versions up to 16.0.1 relabelled the Additional Discount fields and created an expense account named
`Deductions And Retentions`. 16.0.2 removes those labels on upgrade; the account is left in place because it
may carry GL entries, and it is no longer used.

The only full rollback is restoring the database backup taken immediately before
installation, which also discards every transaction recorded after that backup. Agree
the rollback window before installing on a production site.

## Contributions and Community

1. You can start by giving a star to this repository!
2. If you find any issues, even if it is a typo, please raise an issue.

## License

[MIT License](/license.md)
