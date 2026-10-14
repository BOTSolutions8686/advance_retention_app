app_name = "advance_retention_app"
app_title = "Advance Retention App"
app_publisher = "khayam khan"
app_description = "A custom Frappe Application that introduces Advance Invoice payment and deduction in Sales Invoice (Frappe v16 compatible)"
app_email = "khayamkhan852@gmail.com"
app_license = "mit"

# Apps
# ------------------

# ERPNext supplies the Sales Invoice doctype this app customises, so it must be
# installed first. Frappe resolves this automatically for `bench install-app`.
required_apps = ["erpnext"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "advance_retention_app",
# 		"logo": "/assets/advance_retention_app/logo.png",
# 		"title": "Advance Retention App",
# 		"route": "/advance_retention_app",
# 		"has_permission": "advance_retention_app.api.permission.has_app_permission"
# 	}
# ]

fixtures = [
    {
        "dt": "Custom Field", "filters": [
            [
                "name", "in", [
                    "Sales Invoice-custom_invoice_type",
                    "Sales Invoice-custom_advance_invoices",
				    "Sales Invoice-custom_get_advace_sales_invoices",
                    "Sales Invoice-custom_advance_payment_invoices",
                    "Sales Invoice-custom_vat_exclusive",
                    "Sales Invoice-custom_vat_including",
                    "Sales Invoice-custom_vat_on_allocated",
                    "Sales Invoice-custom_net_amount_due",
                    "Sales Invoice-custom_net_invoice_for_the_period_total",
                    "Sales Invoice-custom_in_words_english",
                    "Sales Invoice-custom_in_words_arabic",
                    "deductions_and_retentions_tab_break",
                    "Sales Invoice-custom_retentions_and_retentions",
                    "Sales Invoice-custom_retentions_and_deductions_table",
                    "Sales Invoice-custom_total_deductions_and_retentions",
                    "Sales Invoice-custom_column_break_vnklc"
                ]
            ]
        ]
    },
    {
        "dt": "Property Setter", "filters": [
            [
                "name", "in", [
                    "Sales Invoice-discount_amount-Label",
                    "Sales Invoice-apply_discount_on-label",
                    "Sales Invoice-base_discount_amount-label",
                    "Sales Invoice-base_discount_amount-hidden",
                    "Sales Invoice-additional_discount_account-label",
                    "Sales Invoice-additional_discount_percentage-label",
                    "Sales Invoice-additional_discount_percentage-read_only",
                    "Sales Invoice-additional_discount_percentage-hidden",
                    "Sales Invoice-main-field_order",
                ]
            ]
        ]
    },
    {
        "dt": "Invoice Type", "filters": [
            [
                "name", "in", [
                    "Sales Invoice",
                    "Advance Invoice",
                ]
            ]
        ]
    }
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/advance_retention_app/css/advance_retention_app.css"
# app_include_js = "/assets/advance_retention_app/js/advance_retention_app.js"

# include js, css files in header of web template
# web_include_css = "/assets/advance_retention_app/css/advance_retention_app.css"
# web_include_js = "/assets/advance_retention_app/js/advance_retention_app.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "advance_retention_app/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
    "Sales Invoice" : "public/js/sales_invoice_custom.js"
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "advance_retention_app/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "advance_retention_app.utils.jinja_methods",
# 	"filters": "advance_retention_app.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "advance_retention_app.install.before_install"
after_install = "advance_retention_app.setup.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "advance_retention_app.uninstall.before_uninstall"
# after_uninstall = "advance_retention_app.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "advance_retention_app.utils.before_app_install"
# after_app_install = "advance_retention_app.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "advance_retention_app.utils.before_app_uninstall"
# after_app_uninstall = "advance_retention_app.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "advance_retention_app.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"advance_retention_app.tasks.all"
# 	],
# 	"daily": [
# 		"advance_retention_app.tasks.daily"
# 	],
# 	"hourly": [
# 		"advance_retention_app.tasks.hourly"
# 	],
# 	"weekly": [
# 		"advance_retention_app.tasks.weekly"
# 	],
# 	"monthly": [
# 		"advance_retention_app.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "advance_retention_app.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "advance_retention_app.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "advance_retention_app.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["advance_retention_app.utils.before_request"]
# after_request = ["advance_retention_app.utils.after_request"]

# Job Events
# ----------
# before_job = ["advance_retention_app.utils.before_job"]
# after_job = ["advance_retention_app.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"filter_by": "{filter_by}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"advance_retention_app.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
