# MBL settlement candidate — local only

This extends the simplified `advance_retention_app` deployed to CCND at 16.2.2 / 3ab7a73. It does not introduce the contract-led `contracting_invoicing` application. Candidate: 16.3.0, branch `codex/bot0222-mbl-operations`.

## Operations

- Record a 386 prepayment using the existing Payment Entry flow. Allocate it on a normal 388 invoice.
- Enter retention principal in the Retentions table. If the customer withholds its VAT portion too, enter that separately in **VAT Portion Withheld**. Both amounts remain receivable; neither is a sales discount or reduction of invoice VAT.
- Use **Create → Credit with Settlement Reversal** for a full or partial correction. Set the returned quantities and the reason. The app calculates proportional advance/retention corrections from the original invoice, checks previous credits, restores prepayment allocation through ERPNext's Unreconcile Payment operation and re-allocates only the remaining amount. The reverse VAT journal restores the advance VAT clearing balance. Restored money is customer credit, not an automatic cash refund.
- The original retention transfer must be cancelled before crediting its settlement. Retention already collected must be reconciled first. Normal Accounts permissions remain in force.
- Collect the current amount through Payment Entry. Existing retention transfer, separate receivable, partial collection and final collection continue to operate. Collection of already-invoiced retention does not charge VAT again.
- **Settlement Breakdown**, the **Advance Retention Settlement** print format and **Advance Retention Reconciliation** report distinguish invoice totals, VAT, advance, retention principal, VAT portion withheld, current amount due and signed QR figures.

## MBL fixtures

| Source example | Works excluding VAT | Advance including VAT | Retention principal | VAT portion withheld | Current amount due |
|---|---:|---:|---:|---:|---:|
| 26000098 | 23,000,000.00 | 2,645,000.00 | 2,300,000.00 | 345,000.00 | 21,160,000.00 |
| 26000099 | 150,027,179.01 | 52,736,835.19 | 7,501,358.98 | 0.00 | 112,293,061.69 |
| 26000065 → full credit 260056 | 150,027,179.01 | 52,736,835.19 | 0.00 | 0.00 | 119,794,420.67 |

Use the fixture's **Disable Rounded Total** setting to reproduce MBL's two-decimal totals. Rounding is preserved in the XML when enabled; it is not silently discarded.

## XML, tax and QR

- The original invoice remains a full-value invoice. Advance references and their taxable/VAT breakdown use the prepayment representation in XML Implementation Standard v1.2 §9.5.
- Settlement credits include the original invoice BillingReference, return reason and original 386 references for the reversed advance proportion. The signed XML includes an ordinary `cbc:Note` containing the retention principal, VAT portion withheld and current settlement amount. No invented retention tax tags or fake tax allowances are used.
- In the tested CLI, QR tag 4 equals XML PayableAmount, and tag 5 equals XML TaxAmount. The printed current amount due is shown separately after retention. The QR is always taken from the signed XML; it is not replaced with a locally edited code to match a requested cash balance.
- The report exports separate retention/VAT fields locally. This does **not** prove that ZATCA's own reporting screen will populate equivalent columns from a Note.
- Government tax-point deferral is not implemented by this holdback option. Withholding VAT cash does not, by itself, reduce invoice VAT or establish a deferred tax point.

## Evidence and limits

Tests use synthetic data in an isolated Docker instance. Backend/DB/Redis have no external network route; the loopback-only web proxy exposes the UI at http://127.0.0.1:18222. Scheduler and outbound workers are not running. Nothing is sent to ZATCA, MBL or a production site.

Tested baseline: Frappe 16.51.1, ERPNext 16.50.0, `ksa_compliance` 0.61.11 and CLI 2.10.0. Local XSD, EN, KSA and PIH validation is not production clearance. CCND's deployed `ksa_compliance` revision differs and needs a compatibility rehearsal before a release is proposed.

The app overrides the SIAF controller only to adapt its output model before signing. Its prepare/sign/validate/counter method is based on the tested upstream version; a `ksa_compliance` upgrade requires review of that adapter. The third-party checkout is not patched.

A production release, live refunds, government deferred-tax accounting, historical document correction and customer transmission require separate reviewed scope. This candidate is not deployed.

## Sources

- ZATCA XML Implementation Standard v1.2 (19 May 2023), §9.5 and credit-note requirements: https://www.zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf
- ZATCA Detailed E-Invoicing Guidelines v2 (May 2023), §8 advances: https://www.zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-Invoicing_Detailed__Guideline.pdf
- ZATCA Real Estate VAT Guideline, §6.3 retention: https://zatca.gov.sa/en/RulesRegulations/VAT/Documents/VAT%20%20Real%20Guidelines%20English%20Web.pdf
- ZATCA government-contract VAT timing guidance: https://zatca.gov.sa/en/MediaCenter/News/Pages/New-VAT-Mechanism-for-Gov.aspx
