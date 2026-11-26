# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Report-language contracts; all account data and AWS calls are synthetic."""

import contextlib
import copy
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

from observability_assessment import cli
from observability_assessment.assessment import ComprehensiveObservabilityAssessment
from observability_assessment.discovery.check_specs import CHECK_SPECS
from observability_assessment.models import maturity_label
from observability_assessment.reporting.cloudscape_bridge import (
    CATEGORIES,
    assessment_payload,
    inline_report,
)
from observability_assessment.reporting.recommendations import (
    RecommendationReportingMixin,
)
from observability_assessment.orchestration.multi_account import MultiAccountAssessment
from observability_assessment.orchestration import multi_account
from observability_assessment.reporting.organization import (
    OrganizationReportMixin,
    _fallback_html,
    organization_payload,
)
from test_characterization import configured_assessment, temporary_working_directory
from report_language_support import (
    assessment_for_report,
    document_fields,
    english_document_literals,
    organization_for_report,
)


class ReportLanguageTests(unittest.TestCase):
    def test_japanese_saved_html_titles_fallback_and_escaping(self):
        for language in ("en", "ja"):
            assessment = assessment_for_report(1)
            assessment.report_language = language
            assessment.html_file = "assessment-result/account.html"
            organization = OrganizationReportMixin()
            organization.org_results = organization_for_report(assessment)
            organization.report_language = language
            organization.summary_report_filename = "summary.html"
            with (
                temporary_working_directory(),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                assessment.generate_html_report()
                organization.generate_summary_report()
                single_html = Path(assessment.html_file).read_text()
                org_html = Path("assessment-result/summary.html").read_text()
            single = document_fields(single_html)
            org = document_fields(org_html)
            self.assertEqual(single["language"], language)
            self.assertEqual(org["language"], language)
            data = json.loads(
                org_html.split('<script id="assessment-data" type="application/json">')[
                    1
                ].split("</script>")[0]
            )
            self.assertEqual(data["meta"]["language"], language)
            if language == "ja":
                self.assertEqual(
                    single["title"], "AWS オブザーバビリティ評価レポート — 123456789012"
                )
                self.assertEqual(org["title"], "組織オブザーバビリティ評価サマリー")
                self.assertEqual(
                    single["fallback"],
                    "<main><h1>AWS オブザーバビリティ評価レポート</h1><p>アカウント: 123456789012</p><p>総合スコア: 1.0/4.0</p><p>評価済みの質問: 16/17</p></main>",
                )
                self.assertIn(
                    "<h1>組織オブザーバビリティ評価サマリー</h1>", org["fallback"]
                )
                self.assertIn("評価済みのアカウント: 1/2", org["fallback"])
                self.assertIn("平均スコア: 1.0/4.0", org["fallback"])
                self.assertIn("<h2>アカウントレポート</h2>", org["fallback"])
                self.assertIn("失敗 — Logs error &lt;script&gt;", org["fallback"])
            else:
                questions = assessment.results.assessment_checks
                expected_single, expected_organization = english_document_literals(
                    assessment.results.overall_score,
                    sum(question.assessed for question in questions),
                    len(questions),
                )
                self.assertEqual(single, expected_single)
                self.assertEqual(org, expected_organization)
            self.assertIn("Logs team &lt;&amp;&gt;", org["fallback"])
            self.assertIn(
                'href="observability_assessment_20261125_010203_123456789012.html"',
                org["fallback"],
            )

    def test_japanese_organization_payload_preserves_results(self):
        from observability_assessment.reporting.i18n_ja import TRANSLATIONS

        for level in (0, 1, 2, 3, 4):
            results = organization_for_report(
                assessment_for_report(level or 1, assessed=bool(level))
            )
            before = copy.deepcopy(results)
            en = organization_payload(results)
            ja = organization_payload(results, "ja")
            self.assertEqual(ja["meta"]["language"], "ja")
            expected = copy.deepcopy(en)
            expected["meta"]["language"] = "ja"
            expected["meta"]["generatedAt"] = ja["meta"]["generatedAt"]
            for category in expected["categories"]:
                category["label"] = TRANSLATIONS[category["label"]]
            for field in ("maturityLevel", "bestMaturityLevel"):
                value = expected["summary"][field]
                expected["summary"][field] = TRANSLATIONS.get(value, value)
            for account in expected["accounts"]:
                value = account["maturity"]
                account["maturity"] = TRANSLATIONS.get(value, value)
            self.assertEqual(ja, expected)
            self.assertEqual(results, before)
            if not level:
                self.assertEqual(ja["accounts"][0]["maturity"], "未評価")
                self.assertEqual(ja["summary"]["maturityLevel"], "未評価")
                self.assertEqual(ja["summary"]["bestMaturityLevel"], "未評価")

    def test_japanese_single_payload_preserves_results_evidence_and_csv(self):
        from observability_assessment.reporting.i18n_ja import TRANSLATIONS

        for level in (0, 1, 2, 3, 4):
            assessment = assessment_for_report(level or 1, assessed=bool(level))
            before = copy.deepcopy(assessment.results)
            en = assessment_payload(assessment)
            assessment.report_language = "ja"
            ja = assessment_payload(assessment)
            self.assertEqual(ja["meta"]["language"], "ja")
            self.assertEqual(
                ja["questions"][0]["question"], "ログをどのように収集していますか？"
            )
            self.assertEqual(ja["categories"][0]["label"], "ログ")
            self.assertEqual(ja["questions"][-1]["levelLabel"], "未評価")
            if not level:
                self.assertEqual(ja["summary"]["maturityLevel"], "未評価")
            expected = copy.deepcopy(en)
            expected["meta"]["language"] = "ja"
            expected["meta"]["generatedAt"] = ja["meta"]["generatedAt"]
            expected["summary"]["maturityLevel"] = TRANSLATIONS.get(
                en["summary"]["maturityLevel"], en["summary"]["maturityLevel"]
            )
            for category in expected["categories"]:
                category["label"] = TRANSLATIONS[category["label"]]
            for question in expected["questions"]:
                question["question"] = TRANSLATIONS[question["question"]]
                question["levelLabel"] = TRANSLATIONS.get(
                    question["levelLabel"], question["levelLabel"]
                )
                for description in question["maturityDescriptions"]:
                    description["description"] = TRANSLATIONS[
                        description["description"]
                    ]
                for recommendation in question["recommendations"]:
                    for field in ("title", "description"):
                        recommendation[field] = TRANSLATIONS[recommendation[field]]
            for check in expected["discovery"]:
                check["name"] = TRANSLATIONS[check["name"]]
                check["category"] = TRANSLATIONS[check["category"]]
            self.assertEqual(ja, expected)
            self.assertEqual(assessment.results, before)
            csv_outputs = []
            for language in ("en", "ja"):
                assessment.report_language = language
                assessment.csv_file = None
                with temporary_working_directory():
                    for check in assessment.results.discovery_checks:
                        assessment.export_check_result_to_csv(check)
                    csv_outputs.append(Path(assessment.csv_file).read_bytes())
            self.assertEqual(csv_outputs[0], csv_outputs[1])
            self.assertEqual(assessment.results, before)

    def test_english_payload_and_html_match_sources_without_snapshot(self):
        for level in (None, 1, 2, 3, 4):
            with self.subTest(level=level):
                assessment = assessment_for_report(
                    level or 1, assessed=level is not None
                )
                # Include every recommendation source, including question 17.
                for question in assessment.results.assessment_checks:
                    question.assessed = level is not None
                    question.current_level = level
                single = assessment_payload(assessment)
                self.assertEqual(single["meta"]["language"], "en")
                self.assertEqual(
                    [(row["id"], row["label"]) for row in single["categories"]],
                    [(category_id, label) for category_id, label, _ in CATEGORIES],
                )
                sources = {
                    question.question_id: question
                    for question in assessment.results.assessment_checks
                }
                self.assertEqual(
                    [row["id"] for row in single["questions"]], list(sources)
                )
                for row in single["questions"]:
                    source = sources[row["id"]]
                    self.assertEqual(row["question"], source.question)
                    self.assertEqual(
                        row["maturityDescriptions"],
                        [
                            {"level": value, "description": description}
                            for value, description in sorted(
                                source.maturity_descriptions.items()
                            )
                        ],
                    )
                    expected_recommendations = (
                        assessment.get_recommendations(source.question_id, level)
                        if level is not None and level < 4
                        else []
                    )
                    self.assertEqual(
                        [
                            (item["title"], item["description"], item["url"])
                            for item in row["recommendations"]
                        ],
                        expected_recommendations,
                    )
                    self.assertEqual(
                        row["levelLabel"],
                        maturity_label(level) if source.assessed else "Not assessed",
                    )
                self.assertEqual(
                    [
                        (row["id"], row["name"], row["category"])
                        for row in single["discovery"]
                    ],
                    [
                        (check.id, check.name, check.category)
                        for check in assessment.results.discovery_checks
                    ],
                )
                expected_maturity = (
                    maturity_label(level) if level is not None else "Not assessed"
                )
                self.assertEqual(single["summary"]["maturityLevel"], expected_maturity)
                results = organization_for_report(assessment)
                organization = organization_payload(results)
                self.assertEqual(organization["meta"]["language"], "en")
                self.assertEqual(
                    [row["label"] for row in organization["categories"]],
                    [label for _, label, _ in CATEGORIES],
                )
                for field in ("maturityLevel", "bestMaturityLevel"):
                    self.assertEqual(organization["summary"][field], expected_maturity)
                self.assertEqual(
                    organization["accounts"][0]["maturity"], expected_maturity
                )
                self.assertIsNone(organization["accounts"][1]["maturity"])
                expected_single, expected_organization = english_document_literals(
                    assessment.results.overall_score,
                    sum(question.assessed for question in sources.values()),
                    len(sources),
                )
                self.assertEqual(
                    document_fields(inline_report(single)), expected_single
                )
                self.assertEqual(
                    document_fields(
                        inline_report(
                            organization,
                            title="Organization Observability Assessment Summary",
                            fallback=_fallback_html(organization),
                        )
                    ),
                    expected_organization,
                )

    def test_translate_contract(self):
        from observability_assessment.reporting.i18n import (
            SUPPORTED_REPORT_LANGUAGES,
            translate,
        )

        self.assertEqual(SUPPORTED_REPORT_LANGUAGES, ("en", "ja"))
        text = "How do you collect logs?"
        self.assertIs(translate(text, "en"), text)
        self.assertEqual(translate(text, "ja"), "ログをどのように収集していますか？")
        self.assertEqual(translate("Not assessed", "ja"), "未評価")
        for label in ("Reactive", "Proactive", "Autonomous", "Unknown text"):
            self.assertEqual(translate(label, "ja"), label)

    def test_static_catalog_has_translations(self):
        from observability_assessment.reporting.i18n_ja import TRANSLATIONS

        assessment = configured_assessment()
        texts = {"Not assessed"}
        self.assertEqual(len(CHECK_SPECS), 52)
        self.assertEqual(len(assessment.results.assessment_checks), 17)
        for check in CHECK_SPECS:
            texts.update((check.name, check.category))
        for _, label, category in CATEGORIES:
            texts.update((label, category))
        for question in assessment.results.assessment_checks:
            texts.add(question.question)
            texts.update(question.maturity_descriptions.values())
        recommendations = RecommendationReportingMixin()
        for question_id in range(1, 18):
            for level in range(1, 5):
                for title, description, _ in recommendations.get_recommendations(
                    question_id, level
                ):
                    texts.update((title, description))
        missing = sorted(
            text for text in texts if not TRANSLATIONS.get(text, "").strip()
        )
        self.assertEqual(missing, [])
        for text in texts:
            self.assertNotEqual(TRANSLATIONS[text], text)

    def test_cli_language_default_choices_and_propagation(self):
        for mode in ("single", "accounts", "ou"):
            for language in (None, "en", "ja"):
                with self.subTest(mode=mode, language=language):
                    args = ["assessment"]
                    if mode != "single":
                        args += [
                            f"--{mode}",
                            "123456789012" if mode == "accounts" else "ou-test",
                        ]
                    if language:
                        args += ["--report-language", language]
                    with (
                        patch.object(sys, "argv", args),
                        patch.object(
                            cli, "ComprehensiveObservabilityAssessment"
                        ) as single,
                        patch.object(cli, "MultiAccountAssessment") as organization,
                    ):
                        cli.main()
                    constructor = single if mode == "single" else organization
                    self.assertEqual(
                        constructor.call_args.kwargs["report_language"],
                        language or "en",
                    )
        for language in ("fr", "", "JA"):
            with (
                self.subTest(invalid=language),
                patch.object(
                    sys, "argv", ["assessment", "--report-language", language]
                ),
                contextlib.redirect_stderr(io.StringIO()) as stderr,
                patch.object(
                    cli, "ComprehensiveObservabilityAssessment"
                ) as constructor,
                self.assertRaises(SystemExit) as error,
            ):
                cli.main()
            self.assertEqual(error.exception.code, 2)
            self.assertIn("invalid choice", stderr.getvalue())
            constructor.assert_not_called()

    def test_multi_account_language_propagates_through_both_paths(self):
        for language in (None, "en", "ja"):
            kwargs = {"report_language": language} if language else {}
            single = ComprehensiveObservabilityAssessment(**kwargs)
            self.assertEqual(single.report_language, language or "en")
            session = Mock()
            session.client.return_value.get_caller_identity.return_value = {
                "Account": "123456789012"
            }
            with patch.object(multi_account.boto3, "Session", return_value=session):
                organization = MultiAccountAssessment(**kwargs)
            self.assertEqual(organization.report_language, language or "en")
            for fallback in (False, True):
                with self.subTest(language=language, fallback=fallback):
                    assessed = Mock()
                    with (
                        patch.object(
                            multi_account, "ComprehensiveObservabilityAssessment"
                        ) as constructor,
                        contextlib.redirect_stdout(io.StringIO()),
                    ):
                        denied = ClientError(
                            {"Error": {"Code": "AccessDenied", "Message": "Denied"}},
                            "AssumeRole",
                        )
                        constructor.side_effect = (
                            [denied, assessed] if fallback else [assessed]
                        )
                        _, result, error = organization.assess_account("123456789012")
                    self.assertIs(result, assessed.results)
                    self.assertIsNone(error)
                    for call in constructor.call_args_list:
                        self.assertEqual(
                            call.kwargs["report_language"], language or "en"
                        )
                    self.assertEqual(
                        len(constructor.call_args_list), 2 if fallback else 1
                    )
