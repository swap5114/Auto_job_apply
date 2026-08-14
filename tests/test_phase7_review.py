import os
import unittest
from graph.pipeline import build_pipeline_graph, get_checkpointer_connection
from orchestrator.review_cli import (
    get_pending_review_leads,
    approve_lead,
    edit_lead,
    reject_lead,
)

TEST_DB_PATH = os.path.join("storage", "test_phase7_checkpoints.sqlite")


class TestPhase7Review(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except PermissionError:
                pass

    def tearDown(self):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except PermissionError:
                pass

    def test_phase7_review_interrupt_flow(self):
        cp = get_checkpointer_connection(TEST_DB_PATH)
        graph = build_pipeline_graph(cp)

        leads_data = [
            {
                "lead_id": "lead_001",
                "company": "Tech Corp",
                "role": "Backend Engineer",
                "source": "arbeitnow",
                "resume_version": "resumes/lead_001_resume.pdf",
                "outreach_draft": "Draft for Tech Corp",
                "status": "pending_review",
            },
            {
                "lead_id": "lead_002",
                "company": "Data Inc",
                "role": "AI Specialist",
                "source": "x",
                "resume_version": "resumes/lead_002_resume.pdf",
                "outreach_draft": "Draft for Data Inc",
                "status": "pending_review",
            },
            {
                "lead_id": "lead_003",
                "company": "Legacy Systems",
                "role": "DevOps Engineer",
                "source": "jobicy",
                "resume_version": "resumes/lead_003_resume.pdf",
                "outreach_draft": "Draft for Legacy Systems",
                "status": "pending_review",
            },
        ]

        # Start execution for all 3 leads -> each will interrupt at review node
        for lead in leads_data:
            config = {"configurable": {"thread_id": lead["lead_id"]}}
            graph.invoke(lead, config)

        # Verify all 3 are paused at review node
        pending = get_pending_review_leads(TEST_DB_PATH)
        self.assertEqual(len(pending), 3)
        pending_ids = [item["lead_id"] for item in pending]
        self.assertIn("lead_001", pending_ids)
        self.assertIn("lead_002", pending_ids)
        self.assertIn("lead_003", pending_ids)

        # 1. Approve lead_001
        approve_success = approve_lead("lead_001", db_path=TEST_DB_PATH)
        self.assertTrue(approve_success)

        # Check state of lead_001
        state_001 = graph.get_state({"configurable": {"thread_id": "lead_001"}})
        self.assertEqual(state_001.next, ())  # completed
        self.assertEqual(state_001.values.get("review_decision"), "approved")
        # status becomes "send_skipped" because test leads have no contact_email
        self.assertIn(state_001.values.get("status"), ("approved", "send_skipped"))

        # 2. Edit lead_002
        new_draft_002 = "Customized outreach draft for Data Inc AI Specialist"
        edit_success = edit_lead("lead_002", new_draft=new_draft_002, db_path=TEST_DB_PATH)
        self.assertTrue(edit_success)

        # Check state of lead_002
        state_002 = graph.get_state({"configurable": {"thread_id": "lead_002"}})
        self.assertEqual(state_002.next, ())  # completed
        self.assertEqual(state_002.values.get("review_decision"), "approved")
        self.assertEqual(state_002.values.get("outreach_draft"), new_draft_002)
        self.assertIn(state_002.values.get("status"), ("approved", "send_skipped"))

        # 3. Reject lead_003
        reject_success = reject_lead("lead_003", db_path=TEST_DB_PATH)
        self.assertTrue(reject_success)

        # Check state of lead_003 — rejected leads skip send_node, go to END
        state_003 = graph.get_state({"configurable": {"thread_id": "lead_003"}})
        self.assertEqual(state_003.next, ())  # completed
        self.assertEqual(state_003.values.get("review_decision"), "rejected")
        self.assertEqual(state_003.values.get("status"), "rejected")

        # Verify no pending leads remain
        remaining_pending = get_pending_review_leads(TEST_DB_PATH)
        self.assertEqual(len(remaining_pending), 0)


if __name__ == "__main__":
    unittest.main()
