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

This is a **Frappe v16–compatible** port of `khayamkhan852/advance_retention_app`.

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

## Installation

1. Install and set up a bench (Frappe/ERPNext) by following the
   [Frappe installation guide](https://frappeframework.com/docs/user/en/installation).
2. From the bench directory:

	```
	bench get-app advance_retention_app https://github.com/ArslanMalyieck/advance_retention_app.git
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

`uninstall-app` removes the app's doctypes, custom fields and property setters. The
`Deductions And Retentions` account created by `after_install` is a normal Account
record and, if you do not want to keep it, must be removed manually after the app is
uninstalled. Always take a database backup before installing or uninstalling on a
production site.

## Contributions and Community

1. You can start by giving a star to this repository!
2. If you find any issues, even if it is a typo, please raise an issue.

## License

[MIT License](/license.md)
