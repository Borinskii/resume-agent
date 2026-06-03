import unittest

from app.services.github import GitHubEvidence, parse_github_username
from app.services.job_search import JobPosting
from app.services.linkedin_cleaner import clean_linkedin_profile_text
from app.services.matching import analyze_resume
from app.services.parsing import _parse_pdf
from app.services.target_jobs import strip_html
from app.services.target_jobs import resolve_target_input


class MatchingTests(unittest.TestCase):
    def test_backend_resume_scores_from_evidence(self) -> None:
        resume = """
        Backend Engineer
        Built REST APIs with Python and FastAPI for internal tools.
        Implemented SQL queries, PostgreSQL models with SQLAlchemy, and wrote pytest tests.
        Used Git and Docker in delivery workflows.
        Designed and maintained API endpoints and integrated external services.
        """

        analysis = analyze_resume(resume_text=resume)

        self.assertTrue(analysis.has_resume)
        self.assertGreaterEqual(analysis.top_role.current_score, 50)
        self.assertGreaterEqual(analysis.top_role.tailored_score, analysis.top_role.current_score)
        self.assertEqual(analysis.top_role.title, "Backend Python Engineer")

    def test_missing_required_skill_stays_gap(self) -> None:
        resume = "Customer support specialist with Excel reporting experience."

        analysis = analyze_resume(resume_text=resume)
        backend = next(role for role in analysis.roles if role.title == "Backend Python Engineer")

        self.assertIn("Python", backend.missing_required)
        self.assertTrue(any(action.kind == "gap" and "Python" in action.title for action in backend.tailoring_actions))

    def test_custom_job_text_creates_target(self) -> None:
        resume = "Developed Python services, SQL dashboards, and REST API integrations."
        job = "We need a Python engineer with REST APIs, SQL, and Git experience."

        analysis = analyze_resume(resume_text=resume, target_text=job)

        self.assertEqual(analysis.roles[0].title, "Custom target from pasted job")
        self.assertGreater(analysis.roles[0].total_requirements, 0)

    def test_title_only_target_creates_ml_target(self) -> None:
        resume = "Built Python forecasting models with pandas, scikit-learn, SQL, and statistics."

        analysis = analyze_resume(resume_text=resume, target_text="ML Engineer")

        self.assertEqual(analysis.roles[0].title, "ML Engineer")
        self.assertIn("Machine Learning", [item.name for item in analysis.roles[0].requirement_matches])

    def test_github_contact_url_does_not_prove_git_skill(self) -> None:
        resume = "Portfolio: https://github.com/candidate"

        analysis = analyze_resume(resume_text=resume)
        backend = next(role for role in analysis.roles if role.title == "Backend Python Engineer")

        git_match = next(item for item in backend.requirement_matches if item.name == "Git")
        self.assertEqual(git_match.evidence_level, 0)

    def test_github_evidence_is_supporting_not_cv_claim(self) -> None:
        resume = "Backend engineer with SQL experience."
        github = GitHubEvidence(
            username="candidate",
            status="connected",
            skills={"Python", "FastAPI"},
            repositories=["api-service"],
            message="Read public repositories through the official GitHub API.",
        )

        analysis = analyze_resume(resume_text=resume, github_evidence=github)
        backend = next(role for role in analysis.roles if role.title == "Backend Python Engineer")

        self.assertTrue(any(item.source == "github" for item in backend.requirement_matches))
        self.assertTrue(any(action.kind == "confirm" for action in backend.tailoring_actions))

    def test_github_username_parser(self) -> None:
        self.assertEqual(parse_github_username("https://github.com/octocat"), "octocat")
        self.assertEqual(parse_github_username("https://www.github.com/octocat/"), "octocat")
        self.assertEqual(parse_github_username("@octocat"), "octocat")
        self.assertEqual(parse_github_username("octocat"), "octocat")
        self.assertEqual(parse_github_username("not a profile"), "")
        self.assertEqual(parse_github_username("https://github.com/pricing"), "")

    def test_linkedin_cleaner_removes_ui_noise(self) -> None:
        raw = """
        Главная
        Сообщения
        Boris Candidate
        Developer & Business Analyst
        Developed backend functionality using Python and Django.
        Люди, которых вы можете знать
        Random Person
        """

        cleaned = clean_linkedin_profile_text(raw)

        self.assertIn("Developer & Business Analyst", cleaned.text)
        self.assertIn("Python", cleaned.text)
        self.assertNotIn("Главная", cleaned.text)
        self.assertNotIn("Random Person", cleaned.text)

    def test_blocked_job_url_is_not_fetched(self) -> None:
        resolved = resolve_target_input("https://www.linkedin.com/jobs/view/123")

        self.assertEqual(resolved.text, "")
        self.assertEqual(resolved.statuses[0].status, "blocked_by_policy")

    def test_real_job_postings_replace_static_benchmarks(self) -> None:
        resume = "Built Python machine learning forecasting models with pandas, SQL, and statistics."
        jobs = [
            JobPosting(
                provider="Greenhouse",
                company="Example AI",
                external_id="1",
                title="Machine Learning Engineer",
                location="Remote",
                url="https://boards.greenhouse.io/example/jobs/1",
                updated_at="2026-04-30",
                description="We need Python, machine learning, SQL, pandas, statistics, forecasting, and model evaluation.",
                department="Engineering",
            )
        ]

        analysis = analyze_resume(resume_text=resume, target_text="ML Engineer", job_postings=jobs)

        self.assertEqual(len(analysis.roles), 1)
        self.assertEqual(analysis.roles[0].source_kind, "job")
        self.assertEqual(analysis.roles[0].company, "Example AI")
        self.assertEqual(analysis.roles[0].url, "https://boards.greenhouse.io/example/jobs/1")
        self.assertTrue(any(status.status == "jobs_found" for status in analysis.source_statuses))

    def test_confidence_uses_linkedin_evidence_when_pdf_empty(self) -> None:
        linkedin = "Built Python machine learning forecasting systems with LLM pipelines."

        analysis = analyze_resume(
            resume_text="",
            target_text="ML Engineer",
            linkedin_text=linkedin,
        )

        self.assertFalse(analysis.has_resume)
        self.assertGreater(analysis.confidence_score, 0)

    def test_uploaded_empty_resume_is_not_marked_missing(self) -> None:
        analysis = analyze_resume(
            resume_text="",
            target_text="ML Engineer",
            resume_uploaded=True,
            resume_filename="scan.pdf",
        )

        resume_status = next(item for item in analysis.source_statuses if item.name == "CV / Resume")
        self.assertEqual(resume_status.status, "text_unavailable")
        self.assertIn("scan.pdf", resume_status.detail)

    def test_strip_html_unescapes_before_removing_tags(self) -> None:
        html = "&lt;p&gt;Build machine learning models&lt;/p&gt;"

        self.assertEqual(strip_html(html).strip(), "Build machine learning models")

    def test_empty_pdf_reports_ocr_needed(self) -> None:
        empty_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"

        parsed = _parse_pdf(empty_pdf, "empty.pdf")

        self.assertEqual(parsed.text, "")
        self.assertTrue(any("OCR" in warning for warning in parsed.warnings))


if __name__ == "__main__":
    unittest.main()
