# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Canonical terminology shared by report translation catalogs."""

import unittest

from observability_assessment.reporting.i18n import translate


class ReportLanguageReviewTests(unittest.TestCase):
    def test_catalog_uses_canonical_discovery_check_term(self):
        for source in ("Discovery check", "Discovery checks"):
            with self.subTest(source=source):
                self.assertEqual(translate(source, "ja"), "ディスカバリーチェック")
                self.assertEqual(translate(source, "en"), source)
