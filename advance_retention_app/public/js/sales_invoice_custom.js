frappe.ui.form.on("Sales Invoice", {
	refresh: function(frm) {
		// refresh
	},
	onload: function(frm) {
		if (frm.doc.invoice_type === 'Advance Invoice') {
			frm.set_df_property('advance_invoices_section', 'hidden', 1);
		} else {
			frm.set_df_property('advance_invoices_section', 'hidden', 0);
		}

		if (frm.doc.apply_discount_on === "Grand Total") {
            frm.set_value('is_cash_or_non_trade_discount', 1);
        } else {
            frm.set_value('is_cash_or_non_trade_discount', 0);
        }
	},
	invoice_type: function (frm) {
		if (frm.doc.invoice_type === 'Advance Invoice') {
			frm.set_df_property('advance_invoices_section', 'hidden', 1);
		} else {
			frm.set_df_property('advance_invoices_section', 'hidden', 0);
		}
	},
	get_advance_sales_payment: function (frm) {
		frm.clear_table('payment_invoices');

		if (!frm.doc.invoice_type) {
			frappe.msgprint(__('Please Select Invoice Type as Sales Invoice'));
			return;
		}

		if (!frm.doc.customer) {
			frappe.msgprint(__('Please Select The Customer'));
			return;
		}

		if (frm.doc.invoice_type !== "Advance Invoice" && frm.doc.customer) {
			frappe.call({
				method: "advance_retention_app.customizations.sales_invoice.get_advance_sales_invoices",
				args: {
					customer: frm.doc.customer,
					invoice_type: 'Advance Invoice'
				},
				callback: function (response) {
					if (response.message && response.message.length > 0) {
						response.message.forEach(function (invoice) {
							var row = frappe.model.add_child(frm.doc, 'Advance Payments', 'payment_invoices');
							row.reference_name = invoice.name;
							row.advance_amount = invoice.grand_total;
							row.amount_exclusive_of_vat = invoice.total;
							row.vat_total = invoice.tax_amount;
							row.vat_percentage = invoice.rate;
							row.remaining_advance = invoice.remaining_advance;
							row.remaining_advace_reference = invoice.remaining_advance;
							row.which_invoice = 'sales_invoice';
						});
						frm.refresh_field('payment_invoices');
					} else {
						frappe.msgprint(__('No invoices found with remaining advance for {0}', [frm.doc.customer]));
					}
				}
			});
		}
	},
	is_cash_or_non_trade_discount: function(frm) {
		if (frm.doc.is_cash_or_non_trade_discount) {
            setAdditionalDeductionAccount(frm);
        } else {
            frm.set_value('additional_discount_account', null);
        }
	},
	apply_discount_on: function(frm) {
		if (frm.doc.apply_discount_on === "Grand Total") {
            frm.set_value('is_cash_or_non_trade_discount', 1);
        } else {
            frm.set_value('is_cash_or_non_trade_discount', 0);
        }
	},
	validate: function(frm) {
		calculating_total(frm);

		if (frm.doc.amount_to_be_in_words) {
			frappe.call({
				method: "advance_retention_app.customizations.sales_invoice.get_amount_in_english",
				args: {
					"amount_to_be_in_words": parseFloat(frm.doc.amount_to_be_in_words),
					"currency": frm.doc.currency
				},
				callback: function (response) {
					if (response.message) {
						frm.set_value("in_words_english", response.message)
					}
				},
				error: function (error) {
					frappe.msgprint(__('An error occurred while Generating In Words in English'));
				}
			});
		}
	},
});

frappe.ui.form.on("Sales Deduction", {
	deduction_amount: function (frm, cdt, cdn) {
		var doc = locals[cdt][cdn];

		frappe.model.set_value(cdt, cdn, "total", doc.deduction_amount);

		var total_amount = 0;

		frm.doc.deductions.forEach(function (row) {
			total_amount += row.deduction_amount;
			frappe.model.set_value(row.doctype, row.name, "total", total_amount);
		});

		frm.set_value("discount_amount", total_amount);
	},
	deductions_remove: function (frm) {
		total_amount = 0;

		frm.doc.deductions.forEach(function (row) {
			total_amount += row.deduction_amount;
		});

		frm.set_value("discount_amount", total_amount);
	},	
});

frappe.ui.form.on("Advance Payments", {
	allocated: function (frm, cdt, cdn) {
		var doc = locals[cdt][cdn];
		var row_with_out_vat = ((doc.allocated / (1 + doc.vat_percentage / 100))).toFixed(2);
		var vat_on_allocated = (doc.allocated - row_with_out_vat);

		frappe.model.set_value(cdt, cdn, "allocated_excluding_vat", row_with_out_vat);
		frappe.model.set_value(cdt, cdn, "vat_on_allocated", vat_on_allocated);

		var vat_amount = 0;
		var vat_excluding_amount = 0;
		var vat_including_amount = 0;

		frm.doc.payment_invoices.forEach(function (row) {
			vat_excluding_amount += row.allocated_excluding_vat;
			vat_amount += row.vat_on_allocated;
			vat_including_amount += row.allocated;
		});

		frm.set_value("vat_exclusive_allocated_total", vat_excluding_amount);
		frm.set_value("vat_including_allocated_total", vat_including_amount);
		frm.set_value("vat_on_allocated", vat_amount);

		var calculated_remaining_advance = doc.remaining_advace_reference - doc.allocated;

		frappe.model.set_value(cdt, cdn, "remaining_advance", calculated_remaining_advance);

	},
	allocated_excluding_vat: function (frm, cdt, cdn) {
		var doc = locals[cdt][cdn];

		var allocated = (((doc.vat_percentage / 100) * doc.allocated_excluding_vat) + doc.allocated_excluding_vat).toFixed(2);

		if (allocated > doc.remaining_advace_reference) {
			frappe.msgprint(__('The allocated amount cannot exceed the remaining advance.'));
			frappe.model.set_value(cdt, cdn, "allocated_excluding_vat", 0);
			frappe.model.set_value(cdt, cdn, "allocated", 0);
			return;
		}

		var vat_on_allocated = ((doc.vat_percentage / 100) * doc.allocated_excluding_vat).toFixed(2);

		var vat_percentage_value = (1 + (doc.vat_percentage / 100)).toFixed(2);
		var percentage = (doc.allocated_excluding_vat * vat_percentage_value).toFixed(2);
		var allocated_percentage = ((percentage / doc.remaining_advace_reference) * 100).toFixed(2);

		frappe.model.set_value(cdt, cdn, "allocated", allocated);
		frappe.model.set_value(cdt, cdn, "vat_on_allocated", vat_on_allocated);
		frappe.model.set_value(cdt, cdn, "allocated_percentage", allocated_percentage);
	},

	allocated_percentage: function (frm, cdt, cdn) {
		var doc = locals[cdt][cdn];

		if (doc.allocated_percentage > 100) {
			frappe.msgprint(__('You cannot Enter Percentage more than 100'));
			frappe.model.set_value(cdt, cdn, "allocated_percentage", 0);
			frappe.model.set_value(cdt, cdn, "allocated_excluding_vat", 0);
			return;
		}

		var percentage = (doc.remaining_advace_reference * doc.allocated_percentage / 100).toFixed(2);
		var vat_percentage_value = 1 + (doc.vat_percentage / 100);
		var allocated_excluding_vat = (percentage / vat_percentage_value).toFixed(2);

		var allocated = (allocated_excluding_vat * vat_percentage_value).toFixed(2);

		if (allocated > doc.remaining_advace_reference) {
			frappe.msgprint(__('The allocated amount cannot exceed the remaining advance.'));
			frappe.model.set_value(cdt, cdn, "allocated_percentage", 0);
			frappe.model.set_value(cdt, cdn, "allocated_excluding_vat", 0);
			return;
		}

		frappe.model.set_value(cdt, cdn, "allocated_excluding_vat", allocated_excluding_vat);
		frappe.model.set_value(cdt, cdn, "allocated", allocated);
	}
});

function calculating_total(frm) {
	var discount_amount = frm.doc.discount_amount || 0;
	var grand_total = frm.doc.grand_total || 0;
	var vat_including_allocated_total = frm.doc.vat_including_allocated_total || 0;

	if (frm.doc.apply_discount_on == "Net Total") {
		discount_amount = 0;
	}

	grand_total = grand_total + discount_amount;

	var net_invoice_for_the_period_total = grand_total - vat_including_allocated_total;
	var amount_to_be_in_words = net_invoice_for_the_period_total - discount_amount;

	frm.set_value("net_invoice_for_the_period_total", net_invoice_for_the_period_total);
	frm.set_value("amount_to_be_in_words", amount_to_be_in_words);

	frm.refresh_field("net_invoice_for_the_period_total");
	frm.refresh_field("amount_to_be_in_words");
}

function setAdditionalDeductionAccount(frm) {
	if (frm.doc.apply_discount_on != "Net Total") {
		// frappe.db.get_list is the v15/v16 desk API; it respects permissions and
		// returns a Promise. frappe.client.get_list is deprecated for this use.
		frappe.db.get_list("Account", {
			filters: [
				["account_name", "like", "%Deductions And Retentions%"],
				["company", "=", frm.doc.company]
			],
			fields: ["name", "account_name"],
			limit: 0
		}).then(function (accounts) {
			if (accounts && accounts.length) {
				accounts.forEach(function (account) {
					frm.set_value("additional_discount_account", account.name);
				});
			} else {
				console.log("No accounts found containing 'Deductions And Retentions'.");
			}
		});
	}
}
