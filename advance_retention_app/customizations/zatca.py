from __future__ import annotations
import html
from dataclasses import asdict
from lxml import etree
import frappe
from frappe.utils import flt
from ksa_compliance.ksa_compliance.doctype.sales_invoice_additional_fields.sales_invoice_additional_fields import (
    SalesInvoiceAdditionalFields as Base,
)
from ksa_compliance import logger, zatca_cli as cli
from ksa_compliance.generate_xml import generate_xml_file
from ksa_compliance.throw import fthrow
from ksa_compliance.translation import ft
from ksa_compliance.output_models.e_invoice_output_model import Einvoice
from ksa_compliance.output_models.prepayment_invoice.invoice_line_factory import (
    _create_invoice_line,
)
from advance_retention_app.customizations.settlement import _loads, money


class SettlementEinvoice(Einvoice):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        doc = self.sales_invoice_doc
        if (
            doc.doctype != "Sales Invoice"
            or not doc.is_return
            or not doc.get("custom_bot_reverse_settlement")
        ):
            return
        adj = _loads(doc.custom_bot_credit_adjustments)
        lines = []
        for pe, gross in adj.get("advances", {}).items():
            if gross > 0:
                line = _create_invoice_line(
                    frappe._dict(
                        reference_type="Payment Entry",
                        reference_name=pe,
                        allocated_amount=gross,
                        idx=len(lines) + 1,
                    ),
                    doc,
                )
                if pe in adj.get("advance_vat", {}):
                    vat = adj["advance_vat"][pe]
                    line.tax_total.tax_subtotal.tax_amount = vat
                    line.tax_total.tax_subtotal.taxable_amount = money(gross - vat)
                lines.append(asdict(line))
        prepaid = money(sum(adj.get("advances", {}).values()))
        self.result["prepayment_invoice"] = {
            "currency": doc.currency,
            "prepaid_amount": prepaid,
            "invoice_lines": lines,
        }
        invoice_total = abs(flt(doc.get("rounded_total") or doc.grand_total))
        self.result["invoice"]["rounding_adjustment"] = money(
            invoice_total - abs(flt(doc.grand_total))
        )
        self.result["invoice"]["payable_amount"] = money(invoice_total - prepaid)


def settlement_xml(result, siaf):
    xml = generate_xml_file(result)
    if siaf.invoice_doctype != "Sales Invoice":
        return xml
    doc = frappe.get_doc("Sales Invoice", siaf.sales_invoice)
    adj = _loads(doc.get("custom_bot_credit_adjustments"))
    if not (doc.get("custom_retention_amount") or adj):
        return xml
    principal = adj.get(
        "retention_principal",
        doc.get("custom_bot_retention_principal")
        or doc.get("custom_retention_amount")
        or 0,
    )
    vat = adj.get("retention_vat", doc.get("custom_bot_retention_vat") or 0)
    prepaid = sum(adj.get("advances", {}).values()) if adj else flt(doc.total_advance)
    note = (
        f"Settlement breakdown (SAR): prepayment adjustment {prepaid:.2f}; retention principal {principal:.2f}; "
        f"retention VAT portion withheld {vat:.2f}; amount due now {abs(flt(doc.amount_to_be_in_words)):.2f}. "
        "Retention is a payment holdback and does not reduce invoice VAT."
    )
    if adj:
        note += (
            " Credit reverses allocations on "
            + adj["original"]
            + "; restored advance remains customer credit, not a cash refund."
        )
    ns = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
    root = etree.fromstring(xml.encode())
    node = etree.Element("{" + ns + "}Note")
    node.text = note
    type_node = root.find("{" + ns + "}InvoiceTypeCode")
    root.insert(list(root).index(type_node) + 1, node)
    return etree.tostring(root, encoding="unicode")


class SettlementAdditionalFields(Base):
    def _prepare_for_zatca(self, settings, invoice_type):
        source = frappe.get_doc(self.invoice_doctype, self.sales_invoice)
        if self.invoice_doctype != "Sales Invoice" or not (
            source.get("custom_bot_reverse_settlement")
            or source.get("custom_retention_amount")
        ):
            return super()._prepare_for_zatca(settings, invoice_type)
        import ksa_compliance

        if ksa_compliance.__version__ != "0.61.11":
            fthrow(
                "Settlement XML adapter is verified with ksa_compliance 0.61.11 only; review compatibility before enabling it on this version."
            )
        counting_settings_id, pre_invoice_counter, pre_invoice_hash = (
            frappe.db.get_values(
                "ZATCA Invoice Counting Settings",
                {"business_settings_reference": settings.name},
                ["name", "invoice_counter", "previous_invoice_hash"],
                for_update=True,
            )[0]
        )

        self.invoice_counter = pre_invoice_counter + 1
        self.previous_invoice_hash = pre_invoice_hash

        einvoice = SettlementEinvoice(
            sales_invoice_additional_fields_doc=self, invoice_type=invoice_type
        )

        cert_path = (
            settings.compliance_cert_path
            if self.is_compliance_mode
            else settings.cert_path
        )
        invoice_xml = settlement_xml(einvoice.result, self)
        result = cli.sign_invoice(
            settings.zatca_cli_path,
            settings.java_home,
            invoice_xml,
            cert_path,
            settings.private_key_path,
        )

        if settings.validate_generated_xml and not self.is_compliance_mode:
            validation_result = cli.validate_invoice(
                settings.zatca_cli_path,
                settings.java_home,
                result.signed_invoice_path,
                settings.cert_path,
                self.previous_invoice_hash,
            )
            self.validation_messages = "\n".join(validation_result.messages)
            self.validation_errors = "\n".join(validation_result.errors_and_warnings)
            if validation_result.details:
                logger.info(f"Validation Errors: {validation_result.details.errors}")
                logger.info(
                    f"Validation Warnings: {validation_result.details.warnings}"
                )

                # In theory, we shouldn't have an invalid result without errors/warnings, but just in case an unknown
                # error occurs that isn't captured
                is_invalid = (
                    (not validation_result.details.is_valid)
                    or validation_result.details.errors
                    or validation_result.details.warnings
                )
                if settings.block_invoice_on_invalid_xml and is_invalid:
                    html_message = ""
                    text_message = ""
                    if validation_result.details.errors:
                        text_message += ft("Errors") + "\n"
                        html_message += f"<h4>{ft('Errors')}</h4>"
                        html_message += "<ul>"
                        for code, error in validation_result.details.errors.items():
                            html_message += f"<li><b>{html.escape(code)}</b>: {html.escape(error)}</li>"
                            text_message += f"{code}: {error}\n"
                        html_message += "</ul>"

                    if validation_result.details.warnings:
                        text_message += ft("Warnings") + "\n"
                        html_message += f"<h4>{ft('Warnings')}</h4>"
                        html_message += "<ul>"
                        for code, warning in validation_result.details.warnings.items():
                            html_message += f"<li><b>{html.escape(code)}</b>: {html.escape(warning)}</li>"
                            text_message += f"{code}: {warning}\n"
                        html_message += "</ul>"

                    frappe.log_error(
                        title=ft("ZATCA Validation Error"),
                        message=text_message + "\n\n" + invoice_xml,
                        reference_doctype=self.invoice_doctype,
                        reference_name=self.sales_invoice,
                    )
                    fthrow(title=ft("ZATCA Validation Error"), msg=html_message)

        self.invoice_hash = result.invoice_hash
        self.qr_code = result.qr_code
        self.invoice_xml = result.signed_invoice_xml

        # To update counting settings data
        logger.info(
            f"Changing invoice counter, hash from: {pre_invoice_counter}, {pre_invoice_hash} -> "
            f"{self.invoice_counter}, {self.invoice_hash}"
        )
        frappe.db.set_value(
            "ZATCA Invoice Counting Settings",
            counting_settings_id,
            {
                "invoice_counter": self.invoice_counter,
                "previous_invoice_hash": self.invoice_hash,
            },
        )

        source = frappe.get_doc(self.invoice_doctype, self.sales_invoice)
        if source.get("custom_bot_reverse_settlement") or source.get(
            "custom_bot_retention_vat"
        ):
            if (
                self.validation_errors
                or not self.validation_messages
                or self.validation_messages.count("PASSED") != 4
            ):
                fthrow(
                    "Settlement XML must pass all four local validation checks before this document can be submitted."
                )
