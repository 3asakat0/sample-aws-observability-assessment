# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Translate display text only, leaving assessment definitions untouched."""

from .i18n_ja import TRANSLATIONS

SUPPORTED_REPORT_LANGUAGES = ("en", "ja")


def translate(text, language):
    """Keep English text verbatim and fall back to it for unknown translations."""
    return TRANSLATIONS.get(text, text) if language == "ja" else text
