import os
import uuid
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
import gspread

load_dotenv(os.path.join('config', '.env'))

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

CREDENTIALS_PATH = os.path.join('config', 'credentials.json')

HEADERS = [
    "id", "source", "company", "role", "jd_text", "contact_name",
    "contact_email", "x_handle", "status", "resume_version",
    "outreach_draft", "sent_at", "last_checked", "followup_count",
    "listing_url", "posted_date", "domain",
]


def get_service_account_credentials(path: str, scopes: list) -> Credentials:
    """Builds and returns a Google Credentials object from a JSON key file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Credentials file not found at {path}")

    creds = Credentials.from_service_account_file(
        path,
        scopes=scopes
    )
    return creds


def get_worksheet(sheet_id: str):
    """Authenticates and fetches the first sheet of the target Google Spreadsheet."""
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID environment variable is missing or empty.")

    creds = get_service_account_credentials(CREDENTIALS_PATH, SCOPES)
    spreadsheet_client = gspread.authorize(creds)

    return spreadsheet_client.open_by_key(sheet_id).sheet1


def add_lead(lead: dict) -> bool:
    """Adds a new lead to the sheet, unless it's a duplicate.

    Duplicate = same company+role (case-insensitive), or same non-empty x_handle.
    Returns True if the lead was added, False if it was skipped as a duplicate.
    """
    company = lead.get("company", "").strip()
    role = lead.get("role", "").strip()
    x_handle = lead.get("x_handle", "").strip()

    if not (company and role) and not x_handle:
        raise ValueError("A lead requires either 'company' and 'role', or an 'x_handle'.")

    worksheet = get_worksheet(os.getenv("GOOGLE_SHEET_ID"))
    existing_leads = worksheet.get_all_records()

    for existing in existing_leads:
        same_company_role = bool(company) and bool(role) and (
            existing.get("company", "").strip().lower() == company.lower()
            and existing.get("role", "").strip().lower() == role.lower()
        )
        same_handle = bool(x_handle) and existing.get("x_handle", "").strip().lower() == x_handle.lower()

        if same_company_role or same_handle:
            print(f"Skipped duplicate lead: {company} - {role}")
            return False

    lead_id = uuid.uuid4().hex
    row = []
    for field in HEADERS:
        if field == "id":
            row.append(lead_id)
        else:
            row.append(str(lead.get(field, "")))

    worksheet.append_row(row)
    print(f"Added lead: {company} - {role} (id={lead_id})")
    return True


def get_leads(status: str = None) -> list:
    """Returns all leads as a list of dicts, optionally filtered by status."""
    worksheet = get_worksheet(os.getenv("GOOGLE_SHEET_ID"))
    records = worksheet.get_all_records()

    if status is None:
        return records

    return [record for record in records if record.get("status") == status]


def update_lead(lead_id: str, fields: dict) -> None:
    """Updates specific fields for the lead with the given id."""
    worksheet = get_worksheet(os.getenv("GOOGLE_SHEET_ID"))

    cell = worksheet.find(lead_id, in_column=1)
    if cell is None:
        raise ValueError(f"No lead found with id {lead_id}")

    for field_name, value in fields.items():
        if field_name not in HEADERS:
            raise ValueError(f"Unknown field: {field_name}")
        col_index = HEADERS.index(field_name) + 1
        worksheet.update_cell(cell.row, col_index, value)

    print(f"Updated lead {lead_id}: {fields}")


if __name__ == "__main__":
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    worksheet = get_worksheet(sheet_id)
    print("Successfully connected to worksheet:")
    print(worksheet)
