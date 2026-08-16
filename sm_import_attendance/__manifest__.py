{
    "name": "Import Employee Attendances from Excel or CSV",
    "version": "19.0.1.0.0",
    "category": "Human Resources",
    "summary": "Import employee check in and check out logs from CSV or Excel into Odoo Attendances",
    "description": """
Import Employee Attendances from Excel or CSV
=============================================

Import Employee Attendances from Excel or CSV helps HR teams create Odoo attendance
records from the files exported by fingerprint machines, face readers, RFID gates,
or other attendance devices.

The module adds an Import Attendances wizard under Attendances. Users upload a CSV,
xlsx, or xls file with three columns: Employee Name, Sign In, and Sign Out. A sample
CSV or Excel template can be downloaded from the same wizard.

Dates are parsed from common device export formats, including 2026-07-27 08:00:00
and 27/07/2026 08:00. Excel date cells are also supported. Times are interpreted in
the employee or importing user's timezone before being stored in Odoo.

The whole file is validated before the import is committed. Unknown employees,
duplicate employee matches, missing check in or check out values, invalid dates,
sign out times before sign in times, and overlapping attendances stop the import
with a clear row-level message. Nothing is saved until the complete file is valid.
    """,
    "author": "Steven Marp",
    "website": "https://apps.odoo.com/apps/modules/browse?author=Steven Marp",
    "license": "OPL-1",
    "depends": ["hr_attendance"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/import_attendance_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "images": [
        "static/description/banner.gif",
        "static/description/icon.png",
        "static/description/s1_menu.png",
        "static/description/s1_sample.png",
        "static/description/s2_upload.png",
        "static/description/s3_template.png",
        "static/description/s4_result.png",
    ],
    "price": 19.00,
    "currency": "USD",
}
