frappe.ui.form.on("Sales Invoice", {
	// The app's Advance Invoice / allocation table is retired: advances are ZATCA
	// prepayment invoices (Payment Entry, 386) allocated in the standard Advances
	// table. The old section is only shown on historical invoices that used it.
	refresh: function (frm) {
		toggle_legacy_advance_section(frm);
		show_retention_status(frm);
		show_settlement_actions(frm);
        if (frm.doc.is_return && frm.doc.custom_bot_reverse_settlement) {
            frm.set_df_property("update_outstanding_for_self", "read_only", 1);
            if (frm.doc.docstatus === 0) frm.set_value("update_outstanding_for_self", 0);
        }
	},
	onload: function (frm) {
		toggle_legacy_advance_section(frm);
	},

	// Retention is a payment-timing holdback: VAT stays on the full value and the
	// server applies the cash holdback without changing invoice VAT or the payment
	// schedule. Net Amount Due and its words are also set server-side.
});

frappe.ui.form.on("Sales Deduction", {
	deduction_amount: function (frm, cdt, cdn) {
		var doc = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "total", flt(doc.deduction_amount) + flt(doc.vat_holdback_amount));
		update_retention_total(frm);
	},
	deductions_remove: function (frm) {
		update_retention_total(frm);
	},
});

function update_retention_total(frm) {
	// Display only; the authoritative value and payment schedule are set on save.
	var total = 0;
	(frm.doc.deductions || []).forEach(function (row) {
		total += flt(row.deduction_amount) + flt(row.vat_holdback_amount);
	});
	frm.set_value("custom_retention_amount", total);
}

function toggle_legacy_advance_section(frm) {
    const historical = frm.doc.docstatus !== 0;
    const allocations = historical && (frm.doc.payment_invoices || []).length > 0;
    const legacyType = historical && (frm.doc.invoice_type === "Advance Invoice" || allocations);
    frm.toggle_display("invoice_type", legacyType);
    frm.set_df_property("invoice_type", "read_only", 1);
    frm.toggle_display("advance_invoices_section", allocations);
    frm.toggle_display("get_advance_sales_payment", false);
    frm.set_df_property("payment_invoices", "read_only", 1);
}

// Retention has its own state, shown beside ERPNext's invoice status (which is never
// changed): Unpaid / Partly Paid / Paid, derived on the server from the Payment Ledger.
const RETENTION_COLORS = { Unpaid: "orange", "Partly Paid": "yellow", Paid: "green", "On Hold": "blue", Credited: "gray" };

function show_retention_status(frm) {
	if (frm.doc.docstatus !== 1 || !flt(frm.doc.custom_retention_amount)) return;
	const invoice = frm.doc.name;
	frappe.call({
		method: "advance_retention_app.customizations.retention.get_retention_status",
		args: { invoice: invoice },
		callback: function (r) {
			const s = r.message;
			if (!s || frm.doc.name !== invoice) return;
			const money = (v) => format_currency(v, s.currency);
			const color = s.overdue ? "red" : RETENTION_COLORS[s.status];
			let text = `<span class="indicator-pill ${color}">${__("Retention")}: ${__(s.status)}${s.overdue ? " · " + __("Overdue") : ""}</span>
				&nbsp; ${__("Outstanding {0} of {1}", [money(s.outstanding), money(s.retention)])}
				&nbsp;·&nbsp; ${__("Due {0}", [frappe.datetime.str_to_user(s.due_date)])}`;
			if (s.transfer) {
				text += `&nbsp;·&nbsp; ${__("Collect against")} <a href="/desk/journal-entry/${encodeURIComponent(s.transfer)}">${s.transfer}</a>`;
			} else if (s.adjustments && s.adjustments.length) {
				const refs = s.adjustments.map((a) => `${a.voucher_no} (${money(a.amount)})`).join(", ");
				text += `&nbsp;·&nbsp; ${__("Reduced by credit note or adjustment {0}, not by payment: an accountant decides whether the retention is still owed", [refs])}`;
			} else if (s.outstanding) {
				text += `&nbsp;·&nbsp; ${__("Held on this invoice")}`;
			}
			frm.dashboard.set_headline_alert(text, color);
			// After an accountant cancelled a transfer, only they can transfer the retention again.
			if (s.can_retransfer && frappe.user.has_role("Accounts Manager")) {
				frm.add_custom_button(__("Transfer Retention"), () =>
					frappe.confirm(__("Transfer the held retention to Retention Receivable again?"), () =>
						frappe.call({
							method: "advance_retention_app.customizations.retention.retransfer_retention",
							args: { invoice: invoice },
							freeze: true,
							callback: () => frm.reload_doc(),
						})
					)
				);
			}
		},
	});
}

frappe.ui.form.on("Sales Deduction", {
    vat_holdback_amount(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        frappe.model.set_value(cdt, cdn, "total", flt(row.deduction_amount) + flt(row.vat_holdback_amount));
        update_retention_total(frm);
    }
});

function show_settlement_actions(frm) {
    if (frm.doc.docstatus !== 1) return;
    if (!frm.doc.is_return && frappe.model.can_create("Sales Invoice")) {
        frm.add_custom_button(__("Credit with Settlement Reversal"), () => {
            frappe.call({method: "advance_retention_app.customizations.settlement.make_settlement_credit", args: {invoice: frm.doc.name}, callback(r) {
                if (r.message) { frappe.model.sync(r.message); frappe.set_route("Form", "Sales Invoice", r.message.name); }
            }});
        }, __("Create"));
    }
    frm.add_custom_button(__("Settlement Breakdown"), () => {
        frappe.call({method: "advance_retention_app.customizations.settlement.get_settlement_summary", args: {invoice: frm.doc.name},
            callback(r) {
                if (!r.message) return;
                const s = r.message;
                const rows = [[__("Invoice Total Including VAT"), s.gross], [__("Full Invoice VAT"), s.invoice_vat],
                    [__("Advance Adjustment"), s.prepaid], [__("Retention Principal"), s.principal],
                    [__("Retention VAT Portion Held"), s.retention_vat], [__("Amount Due Now"), s.due_now],
                    [__("QR Amount"), s.qr["4"]], [__("QR VAT"), s.qr["5"]]];
                const body = '<table class="table table-bordered">' + rows.map(([label, value]) =>
                    '<tr><td>' + frappe.utils.escape_html(label) + '</td><td>' + format_currency(value || 0, s.currency) + '</td></tr>').join('') + '</table>';
                frappe.msgprint({title: __("Settlement Breakdown"), message: body + '<p>' +
                    __("Retention is a payment holdback. Full invoice VAT remains reported. QR values come from the signed invoice.") + '</p>'});
            }
        });
    });
}
