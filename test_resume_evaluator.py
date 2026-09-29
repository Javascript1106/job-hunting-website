"""Behavioral tests for résumé evaluation, scoring explanations, and response schema."""

import main


POOR_RESUME = """Summary
Seeking work.
Experience
Responsible for tasks.
"""

AVERAGE_RESUME = """Jordan Lee | jordan@example.com | 555-555-1212
Summary
Customer service associate with 2 years of experience.
Experience
Store Associate | Jan 2023 - Present
- Helped with customers and cash handling
- Restocked inventory and maintained displays
Skills
Customer service, POS, inventory
Education
High School Diploma
"""

STRONG_TECH_RESUME = """Alex Kim | alex@example.com | 555-555-3434
Summary
Software engineer with 6 years of experience.
Experience
Senior Software Engineer | Jan 2022 - Present
- Led Python API redesign using AWS and Docker, reducing latency 38% for 2 million users
- Built CI/CD testing pipeline that reduced deployment time 45%
Software Engineer | Jan 2019 - Dec 2021
- Developed React and TypeScript applications serving 50000 users
- Improved SQL query performance 60% through indexing
Skills
Python, TypeScript, React, SQL, AWS, Docker, Kubernetes, Git, API testing, CI/CD
Projects
GitHub: github.com/alex
Education
BS Computer Science
"""


def test_score_calibration_ranges():
    poor = main.evaluate_resume_document(POOR_RESUME)
    average = main.evaluate_resume_document(AVERAGE_RESUME)
    strong = main.evaluate_resume_document(STRONG_TECH_RESUME)

    assert 25 <= poor["overall_score"] <= 40
    assert 45 <= average["overall_score"] <= 60
    assert 68 <= strong["overall_score"] <= 80
    assert strong["overall_score"] < 85


def test_structured_contract_and_weights():
    result = main.evaluate_resume_document(AVERAGE_RESUME)
    assert result["evaluation_mode"] == "GENERAL"
    assert result["industry_alignment"] is None
    assert set(result["category_scores"]) == {
        "formatting", "impact_metrics", "skills",
        "timeline_logic", "grammar_tone",
    }
    assert sum(result["applied_weights"].values()) == 100
    assert "ai_generated_risk" in result
    assert "red_flags" in result
    assert "key_strengths" in result
    assert "critical_improvements" in result
    assert "industry_alignment" in result


def test_ai_risk_is_explainable_and_timeline_is_separate():
    resume = """Summary
A pivotal driving force and beacon fostering a holistic paradigm.
Experience
Role | Jan 2025 - Jan 2024
- Spearheaded seamless initiatives
- Fostered seamless initiatives
- Spearheaded pivotal initiatives
- Fostered holistic initiatives
- Spearheaded seamless outcomes
"""
    result = main.evaluate_resume_document(resume)
    risk = result["ai_generated_risk"]
    assert risk["flagged"] is True
    assert risk["risk_level"] == "High"
    assert "spearheaded" in risk["flagged_phrases"]
    assert any(
        flag["type"] == "timeline_contradiction"
        for flag in result["red_flags"]
    )


def test_rewrites_are_complete_and_do_not_invent_metrics():
    result = main.evaluate_resume_document(POOR_RESUME)
    for improvement in result["critical_improvements"]:
        after = improvement["after"]
        assert "[" not in after and "]" not in after
        assert not any(token in after for token in ("15%", "40+", "$"))
        assert after.endswith(".")


def test_student_claim_is_checked_against_documented_months():
    resume = """Taylor Morgan | taylor@example.com | 555-555-1212
Objective
High school student with a 3.74 GPA and 1+ year of food handling experience.
Experience
Crew Member, Wendy's | Oct 2024 - Mar 2025
- Provided friendly customer service during peak hours
Skills
Dependable, friendly, teamwork
Education
Central High School | GPA: 3.74
"""
    result = main.evaluate_resume_document(resume)
    assert result["evaluation_mode"] == "GENERAL"
    assert result["analysis_evidence"]["career_stage"] == "entry_level"
    assert result["analysis_evidence"]["dated_range_count"] == 1
    assert any(
        flag["type"] == "experience_claim_mismatch"
        for flag in result["red_flags"]
    )


def test_job_alignment_requires_a_substantive_job_description():
    general = main.evaluate_resume_document(
        AVERAGE_RESUME,
        target_job_description="Sales associate",
    )
    job_review = main.evaluate_resume_document(
        AVERAGE_RESUME,
        target_job_description=(
            "Serve customers, operate a point of sale system, handle cash, "
            "maintain inventory, resolve customer questions, and work "
            "reliably with the store team during scheduled shifts."
        ),
    )
    assert general["evaluation_mode"] == "GENERAL"
    assert general["industry_alignment"] is None
    assert job_review["evaluation_mode"] == "JOB_REVIEW"
    assert job_review["industry_alignment"] is not None


def test_education_dates_do_not_contaminate_employment_timeline():
    resume = """Taylor Morgan | taylor@example.com | 555-555-1212
Objective
High school student with 1+ year of food handling experience.
Experience
Crew Member, Wendy's | Oct 2024 - Mar 2025
- Provided friendly customer service during peak hours
Skills
Dependable, friendly, teamwork
Education
Central High School | Aug 2022 - May 2026
GPA: 3.74
"""
    result = main.evaluate_resume_document(resume)
    timeline = result["timeline_audit"]
    assert timeline["documented_employment_months"] == 6
    assert len(timeline["employment_ranges"]) == 1
    assert timeline["education_dates_excluded"] is True


def test_prompt_is_external_and_structured_fields_are_present():
    prompt = main.load_resume_prompt()
    result = main.evaluate_resume_document(AVERAGE_RESUME)
    assert "GENERAL mode" in prompt
    assert result["prompt_version"] == "evaluator_v1.txt"
    assert "timeline_audit" in result
    assert "skill_audit" in result
    assert "job_alignment" in result


def test_score_breakdown_explains_entry_level_context():
    result = main.evaluate_resume_document(
        """Taylor Morgan | taylor@example.com | 555-555-1212
Objective
High school student seeking an entry-level customer service role.
Experience
Crew Member, Wendy's | Oct 2024 - Mar 2025
- Delivered friendly customer service during peak hours
- Maintained clean food preparation areas and followed food safety procedures
Skills
Customer service, food safety
Education
Central High School | Expected Graduation May 2026
Activities
Volunteered at community events, organized supplies, greeted visitors, and completed assigned shifts reliably.
"""
    )
    breakdown = result["score_breakdown"]
    assert result["schema_version"] == "2.3"
    assert breakdown["career_stage"]["label"] == "Entry-Level / Early Career"
    assert "6 months" in breakdown["context_explanation"]
    assert 2 <= len(breakdown["factors_lowering_score"]) <= 3
    assert 2 <= len(breakdown["factors_supporting_score"]) <= 3
    assert "normal" in breakdown["reassurance_note"].lower()


def test_student_and_career_changer_use_distinct_rubrics():
    resume = """Maxwell Pratt | maxwell@example.com | 555-555-1212
Objective
Motivated student seeking a food-service role.
Education
Westlake High School | May 2026 Graduate | GPA: 3.744
Completed 5 CE Classes and 1 AP Class; earned 20 college credits; Honor Roll student.
Experience
Wendy's | Oct 2024 - Mar 2025
- Provided friendly customer service during peak hours
- Maintained food safety standards and cleanliness
Skills
Customer service, food safety, cash handling, communication
"""
    automatic = main.evaluate_resume_document(resume, career_stage="auto")
    student = main.evaluate_resume_document(resume, career_stage="student")
    changer = main.evaluate_resume_document(resume, career_stage="career_changer")

    assert automatic["score_breakdown"]["career_stage"]["label"] == "Entry-Level / Early Career"
    assert student["score_breakdown"]["career_stage"] == {
        "code": "student", "label": "Student", "source": "selected"
    }
    assert changer["score_breakdown"]["career_stage"]["label"] == "Career Changer"
    assert student["applied_weights"]["skills"] > automatic["applied_weights"]["skills"]
    assert student["applied_weights"]["timeline_logic"] < automatic["applied_weights"]["timeline_logic"]
    assert changer["applied_weights"]["skills"] > automatic["applied_weights"]["skills"]
    assert student["overall_score"] != automatic["overall_score"]
    assert sum(student["applied_weights"].values()) == 100


def test_completed_action_is_not_duplicated_or_padded_with_filler():
    resume = """Taylor Morgan | taylor@example.com | 555-555-1212
Objective
High school student seeking a restaurant role.
Experience
Crew Member, Wendy's | Oct 2024 - Mar 2025
- Completed assigned responsibilities
- Provided friendly customer service during peak hours
- Restocked inventory for the next shift
Skills
Customer service, inventory
Education
Central High School
"""
    result = main.evaluate_resume_document(resume)
    completed_rewrite = next(
        item for item in result["critical_improvements"]
        if item["before"] == "Completed assigned responsibilities"
    )
    after = completed_rewrite["after"].lower()
    assert "completed completed" not in after
    assert "supported the team's daily operations" not in after
    assert "supported daily operations" not in after
    assert "delivered responsive customer service" in after
    assert "maintained inventory readiness" in after
    assert "responded to" not in after
    assert "supported daily operations" not in after
