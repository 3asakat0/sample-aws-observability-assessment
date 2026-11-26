# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Synthetic reports shared by the language compatibility and UI tests."""

import re

from observability_assessment.models import (
    OrganizationAssessmentResults,
    maturity_label,
)
from observability_assessment.reporting.cloudscape_bridge import assessment_payload
from observability_assessment.reporting.organization import organization_payload
from test_characterization import configured_assessment


def assessment_for_report(level=1, *, assessed=True):
    assessment = configured_assessment()
    assessment.timestamp = "20261125_010203"
    assessment.results.timestamp = assessment.timestamp
    assessment.results.account_id = "123456789012"
    assessment.summary_report_filename = "organization_summary.html"
    for check in assessment.results.discovery_checks:
        check.status = "error" if check.id == 2 else "success"
        check.result = {}
        check.evidence = (
            f"<p>Logs evidence #{check.id}</p><details>Raw detail</details>"
        )
    for question in assessment.results.assessment_checks:
        question.assessed = assessed and question.question_id != 17
        question.current_level = level if question.assessed else None
        question.explanation = f"Logs explanation Q{question.question_id}"
        question.evidence_check_ids = [1, 2]
        question.unavailable_check_ids = [2]
        question.incomplete_check_ids = [3]
    assessment.results.overall_score = float(level) if assessed else None
    assessment.results.maturity_level = (
        maturity_label(level) if assessed else "Not assessed"
    )
    assessment.results.category_scores = (
        {q.category: float(level) for q in assessment.results.assessment_checks}
        if assessed
        else {}
    )
    return assessment


def organization_for_report(assessment):
    score = assessment.results.overall_score
    return OrganizationAssessmentResults(
        organization_id="o-example",
        account_results={assessment.results.account_id: assessment.results},
        account_names={assessment.results.account_id: "Logs team <&>"},
        failed_accounts={"999999999999": "Logs error <script>"},
        overall_score_avg=score,
        overall_score_min=score,
        overall_score_max=score,
        maturity_level=assessment.results.maturity_level,
        best_maturity_level=assessment.results.maturity_level,
        category_scores_avg=dict(assessment.results.category_scores),
        category_scores_min=dict(assessment.results.category_scores),
        category_scores_max=dict(assessment.results.category_scores),
    )


def report_payloads(language="en"):
    """Build UI test inputs from the live definitions rather than saved reports."""
    reports = {}
    for level in (0, 1, 2, 3, 4):
        assessment = assessment_for_report(level or 1, assessed=bool(level))
        assessment.report_language = language
        reports[str(level)] = {
            "single": assessment_payload(assessment),
            "organization": organization_payload(
                organization_for_report(assessment), language
            ),
        }
    return reports


def document_fields(document):
    return {
        "title": re.search(r"<title>(.*?)</title>", document).group(1),
        "fallback": re.search(r'<div id="root">(.*?)</div>', document).group(1),
        "language": re.search(r'<html lang="(.*?)">', document).group(1),
    }


def english_document_literals(score, questions_assessed, questions_total):
    """Original English HTML wording with controlled synthetic result values."""
    score_text = f"{score:.1f}/4.0" if score is not None else "N/A"
    single = {
        "title": "AWS Observability Assessment Report — 123456789012",
        "language": "en",
        "fallback": (
            "<main><h1>AWS Observability Assessment Report</h1>"
            "<p>Account: 123456789012</p>"
            f"<p>Overall score: {score_text}</p>"
            f"<p>Questions assessed: {questions_assessed}/{questions_total}</p></main>"
        ),
    }
    organization = {
        "title": "Organization Observability Assessment Summary",
        "language": "en",
        "fallback": (
            "<main><h1>Organization Observability Assessment Summary</h1>"
            "<p>Accounts assessed: 1/2</p>"
            f"<p>Average score: {score_text}</p>"
            "<h2>Account reports</h2><ul><li>"
            '<a href="observability_assessment_20261125_010203_123456789012.html">'
            "123456789012 - Logs team &lt;&amp;&gt;</a></li>"
            "<li>999999999999: Failed — Logs error &lt;script&gt;</li></ul></main>"
        ),
    }
    return single, organization
