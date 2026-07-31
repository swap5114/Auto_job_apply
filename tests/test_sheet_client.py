"""Manual verification script for Phase 1 acceptance criteria.

Run from the project root with: python tests/test_sheet_client.py
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from storage.sheet_client import add_lead, get_leads, update_lead


def run():
    print("--- Inserting 3 fake leads ---")
    lead_1 = {"source": "test", "company": "Acme Corp", "role": "Backend Engineer", "jd_text": "Test JD 1"}
    lead_2 = {"source": "test", "company": "Globex", "role": "Data Scientist", "jd_text": "Test JD 2"}
    lead_3 = {"source": "test", "company": "Initech", "role": "DevOps Engineer", "jd_text": "Test JD 3"}

    add_lead(lead_1)
    add_lead(lead_2)
    add_lead(lead_3)

    print("\n--- Reading leads back ---")
    leads = get_leads()
    test_companies = {"Acme Corp", "Globex", "Initech"}
    matching = [lead for lead in leads if lead["company"] in test_companies]
    for lead in matching:
        print(lead)

    assert len(matching) == 3, f"Expected 3 test leads, found {len(matching)}"

    print("\n--- Updating status of one lead ---")
    acme_lead = next(lead for lead in leads if lead["company"] == "Acme Corp")
    update_lead(acme_lead["id"], {"status": "pending_review"})

    updated = get_leads(status="pending_review")
    assert any(lead["id"] == acme_lead["id"] for lead in updated), "Status update did not persist"
    print("Status update confirmed.")

    print("\n--- Testing dedupe rejection ---")
    result = add_lead(lead_1)
    assert result is False, "Duplicate lead was not rejected"
    print("Duplicate correctly rejected.")

    print("\nAll Phase 1 checks passed.")


if __name__ == "__main__":
    run()
