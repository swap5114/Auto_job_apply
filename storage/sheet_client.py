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
    "listing_url", "posted_date", "domain", "review_decision",
    "demo_idea", "company_info",
    # Auto-built demo projects (Option 2). demo_url = live deployed URL;
    # demo_status = deployed | build_failed | skipped | "" (not attempted).
    "demo_url", "demo_status",
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


# Cache the authorized worksheet handle per sheet_id so we don't re-authorize
# (a network/token call) and re-open the spreadsheet on every single add_lead call.
_worksheet_cache: dict = {}


def get_worksheet(sheet_id: str):
    """Authenticates and fetches the first sheet of the target Google Spreadsheet.

    The worksheet handle is cached per sheet_id for the life of the process to
    avoid repeated authorization / open_by_key calls (which count against quota).
    """
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID environment variable is missing or empty.")

    if sheet_id in _worksheet_cache:
        return _worksheet_cache[sheet_id]

    creds = get_service_account_credentials(CREDENTIALS_PATH, SCOPES)
    spreadsheet_client = gspread.authorize(creds)
    worksheet = spreadsheet_client.open_by_key(sheet_id).sheet1

    _worksheet_cache[sheet_id] = worksheet
    return worksheet


# In-run cache of existing dedup keys. Populated once (a single sheet read) and
# then kept in sync on every add, so we NEVER re-read the whole sheet per lead.
# This is what prevents the Google Sheets read-quota rate limit during scraping.
_dedup_cache: set | None = None


def _norm(value) -> str:
    return (value or "").strip().lower()


def _lead_keys(lead: dict) -> list:
    """Return the dedup key(s) for a lead: company+role and/or x_handle."""
    company = _norm(lead.get("company"))
    role = _norm(lead.get("role"))
    x_handle = _norm(lead.get("x_handle"))

    keys = []
    if company and role:
        keys.append(f"cr::{company}|{role}")
    if x_handle:
        keys.append(f"xh::{x_handle}")
    return keys


def load_dedup_cache(worksheet=None, force: bool = False) -> set:
    """Load existing lead dedup keys from the sheet ONCE, then reuse in memory.

    Pass force=True to rebuild it (e.g. if the sheet was changed externally).
    """
    global _dedup_cache
    if _dedup_cache is not None and not force:
        return _dedup_cache

    ws = worksheet or get_worksheet(os.getenv("GOOGLE_SHEET_ID"))
    existing_leads = ws.get_all_records(expected_headers=HEADERS)

    cache = set()
    for existing in existing_leads:
        for key in _lead_keys(existing):
            cache.add(key)

    _dedup_cache = cache
    return _dedup_cache


def reset_dedup_cache() -> None:
    """Drop the in-memory dedup cache (forces a fresh read on next add_lead)."""
    global _dedup_cache
    _dedup_cache = None


def add_lead(lead: dict) -> bool:
    """Adds a new lead to the sheet, unless it's a duplicate.

    Duplicate = same company+role (case-insensitive), or same non-empty x_handle.
    Returns True if the lead was added, False if it was skipped as a duplicate.

    De-duplication uses an in-memory cache that is loaded from the sheet only
    once per process run, so scraping many leads no longer performs one full-sheet
    read per candidate (which is what triggered the Sheets API rate limit).
    """
    company = (lead.get("company") or "").strip()
    role = (lead.get("role") or "").strip()
    x_handle = (lead.get("x_handle") or "").strip()

    if not (company and role) and not x_handle:
        raise ValueError("A lead requires either 'company' and 'role', or an 'x_handle'.")

    worksheet = get_worksheet(os.getenv("GOOGLE_SHEET_ID"))

    cache = load_dedup_cache(worksheet)
    keys = _lead_keys(lead)

    if any(key in cache for key in keys):
        print(f"Skipped duplicate lead: {company} - {role}")
        return False

    lead_id = uuid.uuid4().hex
    row = []
    for field in HEADERS:
        if field == "id":
            row.append(lead_id)
        else:
            row.append(str(lead.get(field, "")))

    # append_row (anchored at A1) writes to the first empty row starting at column A.
    # This needs no extra read to compute the next row, unlike the previous
    # get_all_values() approach.
    worksheet.append_row(row, value_input_option="RAW", table_range="A1")

    # Keep the cache in sync so duplicates within the same run are also caught.
    for key in keys:
        cache.add(key)

    print(f"Added lead: {company} - {role} (id={lead_id[:8]}...)")
    return True


def ensure_headers() -> list:
    """Make the live sheet's header row match HEADERS, adding any missing columns.

    This is an idempotent, additive migration. New columns in HEADERS are only
    ever appended at the end, so the existing sheet headers are a prefix of
    HEADERS and this simply fills in the trailing new cells (e.g. demo_url,
    demo_status). It must be run once after HEADERS gains a column, otherwise
    get_all_records(expected_headers=HEADERS) raises because the sheet's real
    header row is missing that column.

    Returns the list of header names that were written (empty if already in sync).
    """
    worksheet = get_worksheet(os.getenv("GOOGLE_SHEET_ID"))
    current = worksheet.row_values(1)

    added = []
    for idx, header in enumerate(HEADERS):
        # Cell is missing entirely, or holds a stale/different value.
        if idx >= len(current) or current[idx] != header:
            worksheet.update_cell(1, idx + 1, header)
            if idx >= len(current) or not current[idx]:
                added.append(header)

    # A header-row change can invalidate the dedup cache's assumptions; drop it.
    if added:
        reset_dedup_cache()
        print(f"ensure_headers: added columns {added}")
    else:
        print("ensure_headers: header row already in sync.")
    return added


def get_leads(status: str = None) -> list:
    """Returns all leads as a list of dicts, optionally filtered by status."""
    worksheet = get_worksheet(os.getenv("GOOGLE_SHEET_ID"))
    
    # Use expected_headers to avoid duplicate empty column errors
    records = worksheet.get_all_records(expected_headers=HEADERS)

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
