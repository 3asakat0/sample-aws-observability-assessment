# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Render the actual React UI using the already installed Node dependencies."""

import json
import os
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReportAssetLanguageTests(unittest.TestCase):
    def test_compiled_assets_include_canonical_term_in_single_bundles(self):
        assets = ROOT / "observability_assessment/reporting/assets"
        javascript = list(assets.glob("*.js"))
        stylesheets = list(assets.glob("*.css"))
        self.assertEqual(len(javascript), 1)
        self.assertEqual(len(stylesheets), 1)
        bundle = javascript[0].read_text()
        self.assertTrue(
            "組織の評価結果" in bundle,
            "Japanese organization text is missing from the built bundle",
        )
        self.assertTrue(
            "ディスカバリーチェック" in bundle,
            "Canonical discovery-check term is missing from the built bundle",
        )
        self.assertTrue(stylesheets[0].read_text().strip())


class VisibleReport(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.text = []
        self.labels = []
        self.feed(markup)

    def handle_data(self, text):
        self.text.append(text)

    def handle_starttag(self, tag, attrs):
        self.labels.extend(
            [name, value]
            for name, value in attrs
            if name.startswith("aria-") or name in ("placeholder", "title")
        )

    def content(self):
        return {"text": " ".join("".join(self.text).split()), "labels": self.labels}


def render(language):
    from report_language_support import report_payloads

    result = subprocess.run(
        ["node", str(ROOT / "tests/report_ui_language.cjs"), language],
        cwd=ROOT,
        env=dict(os.environ, TZ="UTC", LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8"),
        capture_output=True,
        input=json.dumps(report_payloads("ja" if language == "ja" else "en")),
        text=True,
        timeout=120,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def japanese_matches(texts):
    """Use Node's Unicode Script properties without an additional Python package."""
    result = subprocess.run(
        [
            "node",
            "--eval",
            r"""
const fs = require('node:fs');
const pattern = /\p{Script=Hiragana}|\p{Script=Katakana}|\p{Script=Han}/u;
const texts = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(texts.map(text => text.match(pattern)?.[0] ?? null)));
""",
        ],
        input=json.dumps(texts),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(result.stdout)


@unittest.skipUnless(
    shutil.which("node") and (ROOT / "report_ui/node_modules/typescript").is_dir(),
    "Requires installed report UI dependencies",
)
class ReportUiLanguageTests(unittest.TestCase):
    def test_discovery_check_translation_is_consistent(self):
        rendered = render("ja")
        translations = rendered["discoveryTranslations"]
        self.assertEqual(translations["Discovery checks"], "ディスカバリーチェック")
        self.assertEqual(translations["Discovery check"], "ディスカバリーチェック")
        for source, translation in translations.items():
            with self.subTest(source=source):
                self.assertIn("ディスカバリーチェック", translation)
        self.assertEqual(rendered["deprecatedDiscoveryTerms"], [])
        for scenario, markup in rendered["views"].items():
            content = VisibleReport(markup).content()
            self.assertNotIn("検出チェック", content["text"], scenario)
            for name, value in content["labels"]:
                self.assertNotIn("検出チェック", value, f"{scenario}: {name}")
        self.assertIn(
            "ディスカバリーチェック",
            VisibleReport(rendered["views"]["1-single"]).content()["text"],
        )

    def test_language_controls_rendering_without_generated_snapshots(self):
        for language in ("ja", "en", "missing", "unknown"):
            rendered = render(language)
            self.assertEqual(
                set(rendered["views"]),
                {
                    f"{level}-{kind}"
                    for level in range(5)
                    for kind in ("single", "organization")
                }
                | {"detail", "discovery", "error"},
            )
            english_texts = []
            for scenario, markup in rendered["views"].items():
                content = VisibleReport(markup).content()
                if language == "ja":
                    if scenario.endswith(("-single", "-organization")):
                        self.assertIn("評価方法", content["text"])
                        self.assertIn("評価済み", content["text"])
                        self.assertNotIn("Assessment methodology", content["text"])
                        self.assertIn("AWS オブザーバビリティ評価", content["text"])
                        self.assertIn(
                            "アカウントの評価結果"
                            if scenario.endswith("-single")
                            else "組織の評価結果",
                            content["text"],
                        )
                else:
                    if scenario.endswith(("-single", "-organization")):
                        self.assertIn("Assessment methodology", content["text"])
                        self.assertIn("AWS Observability Assessment", content["text"])
                    english_texts.append((scenario, content["text"]))
                    english_texts.extend(
                        (f"{scenario}: {name}", value)
                        for name, value in content["labels"]
                    )
            if language != "ja":
                # The positive controls ensure all three requested scripts match.
                matches = japanese_matches(
                    ["あ", "ア", "漢"] + [text for _, text in english_texts]
                )
                self.assertEqual(matches[:3], ["あ", "ア", "漢"])
                for (label, _), match in zip(english_texts, matches[3:]):
                    self.assertIsNone(match, f"{language}: {label}")
            self.assertEqual(rendered["date"], rendered["expectedDate"])
            self.assertTrue(rendered["keysEqual"])
            self.assertEqual(rendered["usesProvider"], language == "ja")
            self.assertEqual(rendered["errorUsesProvider"], language == "ja")
            self.assertEqual(
                rendered["dateArguments"], [["ja-JP"]] if language == "ja" else [[]]
            )
            self.assertEqual(rendered["invalidDate"], "not a date")
            self.assertEqual(rendered["missingDate"], "N/A")
            if language == "ja":
                self.assertEqual(rendered["providerLocale"], "ja")
            if language == "ja":
                self.assertEqual(
                    rendered["parseError"], "組織の評価データにアカウントがありません。"
                )
                self.assertIn("レポートを表示できません", rendered["views"]["error"])
                self.assertIn("推奨事項", rendered["views"]["detail"])
                self.assertIn("エビデンスと説明", rendered["views"]["detail"])
                self.assertIn("検出コマンドをコピー", rendered["views"]["discovery"])
                self.assertIn("コマンド", rendered["views"]["discovery"])
            else:
                self.assertEqual(
                    rendered["parseError"],
                    "Organization assessment data is missing accounts.",
                )
