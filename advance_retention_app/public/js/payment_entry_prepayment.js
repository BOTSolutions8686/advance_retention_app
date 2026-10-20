// ZATCA prepayment invoice (386): replace the template's default tax row with the single
// VAT row ksa_compliance requires (Actual / Deduct / VAT on Advances Clearing), computed
// from the amount received. The server validates the same rule on save.
frappe.ui.form.on("Payment Entry", {
	custom_prepayment_invoice: set_prepayment_vat_row,
	sales_taxes_and_charges_template: function (frm) {
		// ERPNext fills the template rows asynchronously; replace them afterwards.
		frappe.after_ajax(() => set_prepayment_vat_row(frm));
	},
	paid_amount: set_prepayment_vat_row,
	received_amount: set_prepayment_vat_row,
});

function set_prepayment_vat_row(frm) {
	const doc = frm.doc;
	if (doc.docstatus !== 0 || doc.payment_type !== "Receive" || !doc.custom_prepayment_invoice) return;
	if (!doc.sales_taxes_and_charges_template || !flt(doc.paid_amount)) return;
	frappe.call({
		method: "advance_retention_app.customizations.prepayment.get_prepayment_vat_row",
		args: { company: doc.company, template: doc.sales_taxes_and_charges_template, paid_amount: doc.paid_amount },
		callback: async (r) => {
			if (!r.message) return;
			const want = r.message;
			const rows = doc.taxes || [];
			if (rows.length === 1 && rows[0].account_head === want.account_head && rows[0].add_deduct_tax === "Deduct"
				&& rows[0].charge_type === "Actual" && flt(rows[0].tax_amount) === flt(want.tax_amount)) return;
			frm.clear_table("taxes");
			const row = frm.add_child("taxes");
			for (const f of ["charge_type", "add_deduct_tax", "included_in_paid_amount", "account_head", "description", "rate", "tax_amount"]) {
				await frappe.model.set_value(row.doctype, row.name, f, want[f]);
			}
			frm.refresh_field("taxes");
		},
	});
}
