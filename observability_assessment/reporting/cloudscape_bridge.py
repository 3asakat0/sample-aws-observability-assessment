# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Serialize an assessment and embed the local Cloudscape report bundle."""

import json
import re
from datetime import datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from observability_assessment.models import maturity_label
from observability_assessment.scoring.orchestration import average_level
from .i18n import translate


ASSET_DIRECTORY = Path(__file__).resolve().parent / "assets"
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#0972d3"/>'
    '<path d="M9 34h13l7-16 9 28 6-12h11" fill="none" '
    'stroke="#fff" stroke-linecap="round" stroke-linejoin="round" stroke-width="6"/>'
    "</svg>"
)
FAVICON_DATA_URI = f"data:image/svg+xml,{quote(FAVICON_SVG, safe='')}"
CATEGORIES = (
    ("logs", "Logs", "Logs"),
    ("metrics", "Metrics", "Metrics"),
    ("traces", "Traces", "Traces"),
    ("dashboards", "Dashboards and alerting", "Dashboards & Alerting"),
    ("organization", "Organization", "Organization"),
)
_LINE_BREAK_TAGS = frozenset(
    {"br", "div", "p", "li", "tr", "details", "summary", "section"}
)


def _clean_evidence_lines(parts, *, preserve_spacing=False):
    lines = [" ".join(line.split()) for line in "".join(parts).splitlines()]
    if not preserve_spacing:
        return "\n".join(line for line in lines if line)
    cleaned = []
    for line in lines:
        if line or (cleaned and cleaned[-1]):
            cleaned.append(line)
    return "\n".join(cleaned).strip()


class _EvidenceSections(HTMLParser):
    """Separate HTML evidence summaries and details into escaped-safe text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.summary = []
        self.details = []
        self.details_depth = 0
        self.summary_depth = 0

    def _target(self):
        if self.summary_depth:
            return None
        return self.details if self.details_depth else self.summary

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            self.details_depth += 1
        elif tag == "summary" and self.details_depth:
            self.summary_depth += 1
        elif tag in _LINE_BREAK_TAGS:
            target = self._target()
            if target is not None:
                target.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "summary" and self.summary_depth:
            self.summary_depth -= 1
        elif tag == "details" and self.details_depth:
            self.details_depth -= 1
        elif tag in _LINE_BREAK_TAGS:
            target = self._target()
            if target is not None:
                target.append("\n")

    def handle_data(self, data):
        target = self._target()
        if target is not None:
            target.append(data)

    def sections(self):
        return (
            _clean_evidence_lines(self.summary),
            _clean_evidence_lines(self.details, preserve_spacing=True),
        )


def evidence_sections(markup):
    parser = _EvidenceSections()
    parser.feed(str(markup or ""))
    parser.close()
    return parser.sections()


def _discovery_evidence(assessment, check):
    # The executor has already generated this detail and may have appended a
    # partial-data warning or replaced it with a diagnostic.
    if check.evidence:
        markup = check.evidence
    elif check.status != "success":
        markup = "Check was not evaluated."
    else:
        try:
            markup = assessment.generate_detailed_evidence(check)
        except Exception as exc:
            markup = f"Evidence generation failed: {exc}"
    summary, details = evidence_sections(markup)
    return {
        "evidenceSummary": summary,
        "evidenceDetails": details,
        "evidenceText": "\n".join(part for part in (summary, details) if part),
    }


def _discovery_row(assessment, check, language):
    return {
        "id": check.id,
        "name": translate(check.name, language),
        "category": translate(check.category, language),
        "status": check.status,
        "command": check.command,
        **_discovery_evidence(assessment, check),
    }


def assessment_payload(assessment):
    """Build the exact data contract consumed by the inline React application."""
    results = assessment.results
    language = getattr(assessment, "report_language", "en")
    questions = results.assessment_checks
    discovery = results.discovery_checks
    assessed = [question for question in questions if question.assessed]
    categories = []
    category_ids = {}
    for category_id, label, source_category in CATEGORIES:
        category_ids[source_category] = category_id
        members = [q for q in questions if q.category == source_category]
        categories.append(
            {
                "id": category_id,
                "label": translate(label, language),
                "score": average_level(members),
                "assessedCount": sum(q.assessed for q in members),
                "totalCount": len(members),
            }
        )

    question_rows = []
    for question in questions:
        recommendations = (
            assessment.get_recommendations(question.question_id, question.current_level)
            if question.assessed and question.current_level < 4
            else []
        )
        question_rows.append(
            {
                "id": question.question_id,
                "category": category_ids[question.category],
                "question": translate(question.question, language),
                "assessed": question.assessed,
                "level": question.current_level if question.assessed else None,
                "levelLabel": (
                    translate(maturity_label(question.current_level), language)
                    if question.assessed
                    else translate("Not assessed", language)
                ),
                "explanation": question.explanation,
                "evidenceCheckIds": list(question.evidence_check_ids),
                "unavailableCheckIds": list(question.unavailable_check_ids),
                "incompleteCheckIds": list(question.incomplete_check_ids),
                "maturityDescriptions": [
                    {"level": level, "description": translate(description, language)}
                    for level, description in sorted(
                        question.maturity_descriptions.items()
                    )
                ],
                "recommendations": [
                    {
                        "title": translate(title, language),
                        "description": translate(description, language),
                        "url": url,
                    }
                    for title, description, url in recommendations
                ],
            }
        )

    return {
        "meta": {
            "language": language,
            "accountId": results.account_id,
            "region": assessment.region,
            "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "backLink": assessment.summary_report_filename or "",
        },
        "summary": {
            "overallScore": results.overall_score if assessed else None,
            "maturityLevel": translate(
                results.maturity_level if assessed else "Not assessed", language
            ),
            "discoveryEvaluated": sum(c.status == "success" for c in discovery),
            "discoveryTotal": len(discovery),
            "discoveryUnavailable": sum(c.status == "error" for c in discovery),
            "questionsAssessed": len(assessed),
            "questionsTotal": len(questions),
            "partialQuestions": sum(
                bool(q.unavailable_check_ids or q.incomplete_check_ids)
                for q in assessed
            ),
        },
        "categories": categories,
        "questions": question_rows,
        "discovery": [
            _discovery_row(assessment, check, language) for check in discovery
        ],
    }


def _read_bundle(extension):
    candidates = sorted(ASSET_DIRECTORY.glob(f"*.{extension}"))
    if len(candidates) != 1:
        raise RuntimeError(
            f"Cloudscape report requires exactly one .{extension} bundle in "
            f"{ASSET_DIRECTORY}; found {len(candidates)}. Build the frontend "
            "into that directory before generating reports."
        )
    bundle = candidates[0].read_text(encoding="utf-8")
    if not bundle.strip():
        raise RuntimeError(f"Cloudscape report bundle is empty: {candidates[0]}")
    return bundle


def inline_report(payload, *, title=None, fallback=""):
    """Return a self-contained HTML document or fail before any file is written."""
    css = _read_bundle("css")
    js = _read_bundle("js")
    if re.search(r"</\s*style(?=[\s/>])", css, flags=re.IGNORECASE):
        raise RuntimeError("Cloudscape CSS contains a closing </style> tag.")
    if re.search(r"</\s*script(?=[\s/>])", js, flags=re.IGNORECASE):
        raise RuntimeError("Cloudscape JS contains a closing </script> tag.")

    data = json.dumps(
        payload, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    )
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    language = "ja" if payload["meta"].get("language") == "ja" else "en"
    if title is None:
        title = (
            translate("AWS Observability Assessment Report", language)
            + f" — {payload['meta']['accountId']}"
        )
    safe_title = escape(str(title))
    if not fallback:
        summary = payload["summary"]
        score = summary["overallScore"]
        score_text = f"{score:.1f}/4.0" if score is not None else "N/A"
        account = escape(str(payload["meta"]["accountId"]))
        fallback = (
            f"<main><h1>{translate('AWS Observability Assessment Report', language)}</h1>"
            f"<p>{translate('Account', language)}: {account}</p>"
            f"<p>{translate('Overall score', language)}: {score_text}</p>"
            f"<p>{translate('Questions assessed', language)}: {summary['questionsAssessed']}/"
            f"{summary['questionsTotal']}</p></main>"
        )
    return f"""<!DOCTYPE html>
<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: MIT-0 -->
<html lang="{language}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_title}</title>
    <link rel="icon" type="image/svg+xml" sizes="any" href="{FAVICON_DATA_URI}">
    <style id="assessment-styles">{css}</style>
</head>
<body>
    <div id="root">{fallback}</div>
    <script id="assessment-data" type="application/json">{data}</script>
    <script id="assessment-app">{js}</script>
</body>
</html>"""
