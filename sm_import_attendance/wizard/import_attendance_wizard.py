import base64
import csv
import io
from datetime import date, datetime

import pytz

from odoo import _, fields, models
from odoo.exceptions import UserError

COLUMNS = ["Employee Name", "Sign In", "Sign Out"]
NAME, SIGN_IN, SIGN_OUT = range(3)

# The formats a timesheet exported from a fingerprint or face reader tends to use.
DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y",
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
)

SAMPLE_ROWS = [
    ["Marc Demo", "2026-07-27 08:00:00", "2026-07-27 17:00:00"],
    ["Marc Demo", "2026-07-28 08:05:00", "2026-07-28 17:10:00"],
    ["Mitchell Admin", "2026-07-27 09:00:00", "2026-07-27 18:00:00"],
]


def cell(row, index):
    """A column as a stripped string, empty when the column is not there."""
    if len(row) <= index:
        return ""
    value = row[index]
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


class ImportAttendanceWizard(models.TransientModel):
    _name = "sm.import.attendance.wizard"
    _description = "Import Employee Attendances"

    import_file = fields.Binary(string="File")
    file_name = fields.Char(string="File Name")
    file_type = fields.Selection(
        [("csv", "CSV"), ("xls", "Excel")],
        string="File Type",
        default="csv",
        required=True,
    )
    has_header = fields.Boolean(
        string="File Has Header Row",
        default=True,
        help="Enable this if the first row contains column titles.",
    )
    download_sample = fields.Boolean(
        string="Download Sample File",
        help="Get a CSV or Excel template with the required columns.",
    )
    sample_type = fields.Selection(
        [("csv", "CSV"), ("xls", "Excel")], string="Sample Type", default="csv"
    )
    sample_file = fields.Binary(string="Sample", readonly=True)
    sample_file_name = fields.Char(string="Sample File Name", readonly=True)

    # ------------------------------------------------------------------ reading
    def _read_rows(self):
        """Return the rows of the file, whichever of the two formats it is in."""
        self.ensure_one()
        if not self.import_file:
            raise UserError(_("Choose a file to import first."))
        content = base64.b64decode(self.import_file)
        name = (self.file_name or "").lower()

        if self.file_type == "csv" or name.endswith(".csv"):
            text = content.decode("utf-8-sig", errors="ignore")
            # a file written by Excel may be separated by semicolons
            sample = text[:2048]
            delimiter = ";" if sample.count(";") > sample.count(",") else ","
            rows = [
                [(c or "").strip() for c in row]
                for row in csv.reader(io.StringIO(text), delimiter=delimiter)
                if any((c or "").strip() for c in row)
            ]
            return rows

        if name.endswith(".xls"):
            return self._read_xls(content)
        return self._read_xlsx(content)

    def _read_xls(self, content):
        try:
            import xlrd
        except ImportError:
            raise UserError(_(
                "The xlrd python library is required to read an old .xls file. "
                "Save the file as .xlsx or as CSV instead."
            ))
        book = xlrd.open_workbook(file_contents=content)
        sheet = book.sheet_by_index(0)
        rows = []
        for index in range(sheet.nrows):
            values = []
            for column in range(sheet.ncols):
                cell_obj = sheet.cell(index, column)
                if cell_obj.ctype == xlrd.XL_CELL_DATE:
                    values.append(datetime(*xlrd.xldate_as_tuple(cell_obj.value, book.datemode)))
                else:
                    values.append(cell_obj.value)
            if any(str(v).strip() for v in values if v is not None):
                rows.append(values)
        return rows

    def _read_xlsx(self, content):
        try:
            import openpyxl
        except ImportError:
            raise UserError(_(
                "The openpyxl python library is required to read Excel files. "
                "Use a CSV file instead."
            ))
        book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        rows = []
        for row in book.active.iter_rows(values_only=True):
            if row and any(c is not None and str(c).strip() for c in row):
                rows.append(["" if c is None else c for c in row])
        return rows

    # ------------------------------------------------------------------ parsing
    def _employee_timezone(self, employee):
        """Times in the file are local, and Odoo stores them in UTC.

        Reading a fingerprint export as if it were UTC is how imported attendances end
        up hours out, so the employee's own timezone decides, and the importing user's
        is the fallback.
        """
        name = employee.tz or self.env.user.tz
        try:
            return pytz.timezone(name) if name else pytz.utc
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    def _to_utc(self, value, timezone, line_no, column):
        """Turn whatever the cell holds into a naive UTC datetime."""
        if isinstance(value, datetime):
            moment = value
        elif isinstance(value, date):
            moment = datetime(value.year, value.month, value.day)
        else:
            text = ("" if value is None else str(value)).strip()
            if not text:
                raise UserError(_(
                    "Row %(row)s: %(column)s is empty. An attendance needs both a sign in "
                    "and a sign out.", row=line_no, column=column,
                ))
            moment = None
            for fmt in DATETIME_FORMATS:
                try:
                    moment = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if moment is None:
                raise UserError(_(
                    "Row %(row)s: '%(value)s' in %(column)s is not a date and time. "
                    "Write it as 2026-07-27 08:00:00.",
                    row=line_no, value=text, column=column,
                ))
        return timezone.localize(moment).astimezone(pytz.utc).replace(tzinfo=None)

    def _find_employee(self, name, line_no):
        if not name:
            raise UserError(_("Row %s: the employee column is empty.") % line_no)
        Employee = self.env["hr.employee"]
        employee = Employee.search([("name", "=", name)], limit=1)
        if not employee:
            employee = Employee.search([("name", "=ilike", name)], limit=1)
        if not employee:
            raise UserError(_(
                "Row %(row)s: no employee named '%(name)s'. Check the spelling, or add "
                "the employee first.", row=line_no, name=name,
            ))
        if len(Employee.search([("name", "=ilike", name)])) > 1:
            raise UserError(_(
                "Row %(row)s: '%(name)s' matches more than one employee, so the "
                "attendance cannot be filed with certainty.", row=line_no, name=name,
            ))
        return employee

    # ------------------------------------------------------------------ actions
    def action_download_sample(self):
        """Hand out a file in the shape the import expects."""
        self.ensure_one()
        if self.sample_type == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(COLUMNS)
            writer.writerows(SAMPLE_ROWS)
            content = buffer.getvalue().encode("utf-8")
            name = "attendance_import_sample.csv"
        else:
            try:
                import xlsxwriter
            except ImportError:
                raise UserError(_(
                    "The xlsxwriter python library is required to build an Excel sample. "
                    "Pick the CSV sample instead."
                ))
            buffer = io.BytesIO()
            book = xlsxwriter.Workbook(buffer, {"in_memory": True})
            sheet = book.add_worksheet("Attendances")
            header = book.add_format({"bold": True, "bg_color": "#D9D9D9", "border": 1})
            for index, title in enumerate(COLUMNS):
                sheet.write(0, index, title, header)
                sheet.set_column(index, index, 24)
            for row_index, row in enumerate(SAMPLE_ROWS, start=1):
                for column, value in enumerate(row):
                    sheet.write(row_index, column, value)
            book.close()
            content = buffer.getvalue()
            name = "attendance_import_sample.xlsx"

        self.write({
            "sample_file": base64.b64encode(content),
            "sample_file_name": name,
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_import(self):
        self.ensure_one()
        rows = self._read_rows()
        if self.has_header and rows:
            rows = rows[1:]
        if not rows:
            raise UserError(_("The file holds no attendance row."))

        values = []
        for line_no, row in enumerate(rows, start=2 if self.has_header else 1):
            name = cell(row, NAME)
            if not name and not cell(row, SIGN_IN) and not cell(row, SIGN_OUT):
                continue
            employee = self._find_employee(name, line_no)
            timezone = self._employee_timezone(employee)
            check_in = self._to_utc(
                row[SIGN_IN] if len(row) > SIGN_IN else "", timezone, line_no, _("Sign In")
            )
            check_out = self._to_utc(
                row[SIGN_OUT] if len(row) > SIGN_OUT else "", timezone, line_no, _("Sign Out")
            )
            if check_out <= check_in:
                raise UserError(_(
                    "Row %(row)s: the sign out is not after the sign in.", row=line_no
                ))
            values.append({
                "employee_id": employee.id,
                "check_in": check_in,
                "check_out": check_out,
            })

        # One create for the lot, inside a savepoint. A clash with an attendance already
        # in Odoo is raised by the last row, and without the savepoint the rows before it
        # would stay written: a request would roll them back, but nothing that calls this
        # from anywhere else would.
        try:
            with self.env.cr.savepoint():
                attendances = self.env["hr.attendance"].create(values)
        except Exception as error:
            raise UserError(_(
                "The attendances were not imported: %s\n\n"
                "Nothing was saved, so the file can be corrected and sent again.",
                error,
            ))

        return {
            "type": "ir.actions.act_window",
            "name": _("Imported Attendances (%s)", len(attendances)),
            "res_model": "hr.attendance",
            "view_mode": "list,form",
            "domain": [("id", "in", attendances.ids)],
        }
