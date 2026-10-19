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

> **Status: draft — awaiting accounting review. Not for live invoicing until approved.**
> Retentions (16.0.2) and advances (16.1.0) follow the decisions and lab results recorded in the review PR.
> Refunds and cancellation of advance (prepayment) invoices have **no automated compliant path**. See
> "Advance refunds and cancellation" below.

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

## Advances (16.1.0)

Advances follow ZATCA's prepayment model (E-Invoicing Detailed Guideline §8; XML Implementation Standard §9.5)
using `ksa_compliance`:

1. Record the advance as a **Payment Entry** (Receive) with **Prepayment Invoice** ticked, a Sales Taxes and
   Charges Template, and one VAT row (`Actual`, `Deduct`, as `ksa_compliance` requires) booked to the company's
   **Advance VAT Clearing Account**. `ksa_compliance` reports it as a **386** prepayment invoice.
2. On the final Sales Invoice, allocate the advance in the standard **Advances** table. `ksa_compliance` reports
   a **388** with the full value and VAT, `PrepaidAmount` (VAT-inclusive) and a zero-value reference line per
   prepayment (ID, UUID, issue date/time, type 386).

Partial allocation, several advances on one invoice, an advance larger than the invoice, and advances combined
with a retention are supported.

### Ledger correction

ERPNext posts a Receive + Deduct tax row as Dr tax account / Cr bank. On its own that understates cash and
reduces output VAT. The app books the row to **VAT on Advances Clearing** and adds two automatic Journal
Entries. Each is identified by *Advance VAT Source* and created once:

| When | Journal Entry |
|---|---|
| Prepayment Payment Entry submitted | Dr bank / Cr output VAT: the VAT due on the 386 |
| Sales Invoice submitted with prepayment advances | Dr output VAT / Cr VAT on Advances Clearing: the advance VAT now carried by the 388 (`allocated − allocated / (1 + rate)`) |

Example: an 11,500 advance (10,000 + 1,500 VAT) settled by a 50,000 + 7,500 VAT invoice leaves bank 11,500,
output VAT 7,500, the receivable 46,000 and the clearing account at 0. Both entries are cancelled with their source document.

`after_install` and the `setup_advance_vat_clearing` patch create *VAT on Advances Clearing* under *Duties
and Taxes* and set it on each Company. Prepayments recorded before 16.1.0 keep their original postings, and the
app creates no settlement entry for them. The accountant must review and correct those separately.

### Retired Advance Invoice

The app's own *Advance Invoice* type and *Advance Payment Invoices* allocation table never produced ZATCA
prepayment invoices. New or draft invoices may no longer use them. Submitted history is unchanged, and the old section
is shown only on invoices that contain rows.

### Tested scope and guards

Verified on Frappe 16.51.1 / ERPNext 16.50.0 / HRMS 16.50.0 with `ksa_compliance` 0.61.11 and
`bot_saudilization` 0.0.1, using synthetic data, through the Desk and in server tests. Only that tested
combination is accepted:

- the company currency must be **SAR**, and prepayments, invoices allocating them, and invoices holding a
  retention must use it;
- a prepayment invoice's Sales Taxes and Charges Template must hold a single **15%** VAT row (`ksa_compliance` takes
  the prepayment rate from the template). The Payment Entry must have one VAT row equal to the VAT included in the
  amount received.

Anything else is refused with a message until it has been tested.

### Using it in the Desk

- On a Payment Entry with *Prepayment Invoice* ticked, choosing the Sales Taxes and Charges Template (or
  changing the amount received) replaces the template's default row with the required single row: *Actual*,
  *Deduct*, account *VAT on Advances Clearing*, VAT included in the amount received.
- On the Sales Invoice, **Get Advances Received** lists every unallocated advance. That includes prepayments
  recorded before 16.1.0, which have no VAT correction, and the invoice shows a warning when one is allocated.
- Printed invoices: the generic *BOT Sales Invoice* and *ZATCA Phase 2 Print Format* show the full taxable amount,
  VAT and gross total only. They omit the prepaid amount, the retention and the net amount due, and their printed
  due date is the retention date, because ERPNext uses the last payment-schedule date. Customer-specific print formats that
  show these (a 388 invoice format and a 386 advance tax invoice for Payment Entry) are delivered separately
  with each deployment, under new names, so the customer's existing formats are not changed.

### Upgrading from 16.0.0 (`080e6e4`)

`bench migrate` runs `remove_legacy_layout`, `remove_discount_relabels` and `setup_advance_vat_clearing`. Together they
remove the whole-form Sales Invoice layout override and its tab, the discount relabels and the module-less hidden setter,
and they create and set the clearing account. Submitted invoices, ledger entries and legacy allocation rows are unchanged.
The `Deductions And Retentions` account and anything already booked to it are kept for the accountant. **Draft** invoices
using the retired Advance Invoice type cannot be saved afterwards, so list them before upgrading. Restart web and worker
processes after `migrate`.

### Advance refunds and cancellation (not automated)

- `ksa_compliance` blocks cancelling a 386 prepayment Payment Entry and a 388 Sales Invoice. Corrections go
  through credit/debit notes.
- A refund of an unused advance has no compliant system path. A refund Payment Entry produces no ZATCA document,
  and `ksa_compliance` credit notes (381) can only reference a Sales Invoice, not a 386 prepayment.

Proposed manual control until an automated path exists:

1. Do not refund an advance with a Payment Entry while ZATCA integration is enabled. Keep the unused advance as
   customer credit and apply it to later invoices.
2. If a refund is unavoidable, it needs written owner and accountant approval recorded on the support ticket. That approval sets out the
   ZATCA correction for the 386 and the Journal Entries that reverse the VAT on the refunded portion
   (Dr output VAT / Cr VAT on Advances Clearing), alongside the refund itself and Payment Reconciliation against the advance.
3. Each month, reconcile *VAT on Advances Clearing* to the VAT inside unallocated prepayments:
   `Σ unallocated_amount × rate / (100 + rate)` over submitted prepayment Payment Entries. Investigate any difference.

## Retentions (16.0.2)

Add rows to the **Retentions** table on the Sales Invoice and set **Retention Due Date**. On save the app:

- totals the rows into **Retention Held (due later)**;
- keeps the full taxable value, VAT and receivable (no discount, ZATCA allowance or expense);
- reduces the existing payment-schedule installments by the retained amount and adds a later-dated
  installment for it, then re-runs ERPNext's own schedule validations;
- sets **Net Amount Due** (invoice total less allocated advances less retention) and its English words.

The retention due date must be after the last installment. The invoice **due date stays on the first
installment**. ERPNext would otherwise move it to the retention date, and the Payment Ledger and receivables report
by invoice due date would then show the whole invoice as not yet due, hiding the overdue amount. ERPNext's invoice
status and the receivables report *based on payment terms* use the schedule, and show the current installment and
the retention separately. Retentions are not supported on returns, POS or opening invoices.

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
