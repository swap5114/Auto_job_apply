"""Phase 7 review-cycle test -- LangGraph interrupt/approve/edit/reject flow.

IMPORTANT: every external boundary the graph can reach is mocked here --
find_contact_email_for_lead (Apollo/Hunter), research_company (LLM),
tailor_resume_for_lead (LLM), llm_generate (draft_node's direct call), and
the Gmail service (send_node). This test exists to verify the review
state machine (interrupt -> approve/edit/reject -> resume), not to place
real network calls.

A prior version of this test had NO mocking at all. It happened to pass
only because it always crashed earlier in the graph (tailor_resume_node
called a function, tailor_resume_for_lead, that didn't exist yet) --
before ever reaching send_node. Once that bug was fixed, this same
unmocked test actually called Apollo's API and SENT A REAL EMAIL via
whatever Gmail account was authenticated in config/gmail_token.json.
That is a serious violation of this project's own "human review before
any send" rule and its stated testing philosophy ("externals mocked in
CI"). This rewrite closes that hole by mocking every node that can reach
a real network service, so a fixed bug elsewhere in the graph can never
again turn a unit test into a live send.
"""

import os
import unittest
from unittest.mock import patch, MagicMock

from graph.pipeline import build_pipeline_graph, get_checkpointer_connection, make_thread_id
from orchestrator.review_cli import (
    get_pending_review_leads,
    approve_lead,
    edit_lead,
    reject_lead,
)

TEST_DB_PATH = os.path.join("storage", "test_phase7_checkpoints.sqlite")
TEST_USER_ID = "test-user-phase7"


class TestPhase7Review(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except PermissionError:
                pass

        # --- Mock every external boundary the graph can reach ---------------
        # find_email_node -> skills.find_contact_email.find_contact_email_for_lead
        patcher_email = patch(
            "skills.find_contact_email.find_contact_email_for_lead",
            return_value={"contact_email": "contact@example.com", "contact_name": "Jamie Contact"},
        )
        # research_company_node -> skills.research_company.research_company
        patcher_research = patch(
            "skills.research_company.research_company",
            return_value={
                "overview": "A test company.",
                "stage": "Growth-stage",
                "industry": "Software",
                "tech_signals": ["Python"],
                "demo_project": {
                    "title": "Test demo",
                    "description": "A small demo.",
                    "tech_stack": ["Python"],
                    "deliverable": "GitHub repo",
                    "time_estimate": "2-3 days",
                },
                "talking_points": [],
                "smart_questions": [],
                "fit_summary": "Good fit.",
            },
        )
        # tailor_resume_node -> skills.tailor_resume.tailor_resume_for_lead
        patcher_tailor = patch(
            "skills.tailor_resume.tailor_resume_for_lead",
            return_value={"resume_version": "fake_resume_version", "keyword_coverage": 50.0},
        )
        # draft_node -> skills.llm_client.llm_generate (direct outreach draft call)
        patcher_llm = patch(
            "skills.llm_client.llm_generate",
            return_value="Subject: Test outreach\n\nThis is a test draft.",
        )
        # draft_node -> skills.draft_outreach.load_tailored_resume (avoid needing a real file)
        patcher_load_resume = patch(
            "skills.draft_outreach.load_tailored_resume",
            return_value={"name": "Test Candidate", "contact": {}, "skills": {}},
        )
        # send_node -> skills.send_via_gmail.get_gmail_service (never touch real Gmail)
        fake_gmail_service = MagicMock()
        patcher_gmail = patch(
            "skills.send_via_gmail.get_gmail_service",
            return_value=fake_gmail_service,
        )
        # send_node -> skills.send_via_gmail.send_email / create_draft (never place a real API call)
        patcher_send_email = patch(
            "skills.send_via_gmail.send_email",
            return_value={"id": "fake-sent-id"},
        )
        patcher_create_draft = patch(
            "skills.send_via_gmail.create_draft",
            return_value={"id": "fake-draft-id"},
        )

        for patcher in (
            patcher_email, patcher_research, patcher_tailor, patcher_llm,
            patcher_load_resume, patcher_gmail, patcher_send_email, patcher_create_draft,
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

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
                "jd_text": "We need a backend engineer with Python and Postgres experience.",
                "resume_version": "resumes/lead_001_resume.pdf",
                "outreach_draft": "Draft for Tech Corp",
                "status": "pending_review",
            },
            {
                "lead_id": "lead_002",
                "company": "Data Inc",
                "role": "AI Specialist",
                "source": "x",
                "jd_text": "Looking for an AI specialist with NLP experience.",
                "resume_version": "resumes/lead_002_resume.pdf",
                "outreach_draft": "Draft for Data Inc",
                "status": "pending_review",
            },
            {
                "lead_id": "lead_003",
                "company": "Legacy Systems",
                "role": "DevOps Engineer",
                "source": "jobicy",
                "jd_text": "DevOps engineer needed for Kubernetes migration.",
                "resume_version": "resumes/lead_003_resume.pdf",
                "outreach_draft": "Draft for Legacy Systems",
                "status": "pending_review",
            },
        ]

        # Start execution for all 3 leads -> each will interrupt at review
        # node. Thread IDs are scoped by user_id (Phase 4.2), matching how
        # feed_pending_leads/check_and_queue_followups construct them in
        # production.
        for lead in leads_data:
            lead["user_id"] = TEST_USER_ID
            thread_id = make_thread_id(TEST_USER_ID, lead["lead_id"])
            config = {"configurable": {"thread_id": thread_id}}
            graph.invoke(lead, config)

        # Verify all 3 are paused at review node
        pending = get_pending_review_leads(TEST_USER_ID, checkpointer=cp)
        self.assertEqual(len(pending), 3)
        pending_ids = [item["lead_id"] for item in pending]
        self.assertIn("lead_001", pending_ids)
        self.assertIn("lead_002", pending_ids)
        self.assertIn("lead_003", pending_ids)

        # 1. Approve lead_001 -> should reach send_node, which is fully mocked
        approve_success = approve_lead("lead_001", user_id=TEST_USER_ID, checkpointer=cp)
        self.assertTrue(approve_success)

        thread_001 = make_thread_id(TEST_USER_ID, "lead_001")
        state_001 = graph.get_state({"configurable": {"thread_id": thread_001}})
        self.assertEqual(state_001.next, ())  # completed
        self.assertEqual(state_001.values.get("review_decision"), "approved")
        # With a mocked contact_email + mocked Gmail send, send_node reaches
        # "sent" (GMAIL_DIRECT_SEND defaults to false, so "draft_created" is
        # the more common real-world outcome, but either is a valid,
        # fully-mocked completion of the approved path).
        self.assertIn(state_001.values.get("status"), ("sent", "draft_created"))

        # 2. Edit lead_002 -> draft replaced, then approved, then sent (mocked)
        new_draft_002 = "Customized outreach draft for Data Inc AI Specialist"
        edit_success = edit_lead(
            "lead_002", new_draft=new_draft_002, user_id=TEST_USER_ID, checkpointer=cp
        )
        self.assertTrue(edit_success)

        thread_002 = make_thread_id(TEST_USER_ID, "lead_002")
        state_002 = graph.get_state({"configurable": {"thread_id": thread_002}})
        self.assertEqual(state_002.next, ())  # completed
        self.assertEqual(state_002.values.get("review_decision"), "approved")
        self.assertEqual(state_002.values.get("outreach_draft"), new_draft_002)
        self.assertIn(state_002.values.get("status"), ("sent", "draft_created"))

        # 3. Reject lead_003 -> rejected leads skip send_node entirely, go to END
        reject_success = reject_lead("lead_003", user_id=TEST_USER_ID, checkpointer=cp)
        self.assertTrue(reject_success)

        thread_003 = make_thread_id(TEST_USER_ID, "lead_003")
        state_003 = graph.get_state({"configurable": {"thread_id": thread_003}})
        self.assertEqual(state_003.next, ())  # completed
        self.assertEqual(state_003.values.get("review_decision"), "rejected")
        self.assertEqual(state_003.values.get("status"), "rejected")

        # Verify no pending leads remain
        remaining_pending = get_pending_review_leads(TEST_USER_ID, checkpointer=cp)
        self.assertEqual(len(remaining_pending), 0)


if __name__ == "__main__":
    unittest.main()
