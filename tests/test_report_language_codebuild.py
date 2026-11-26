# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Exercise the template's actual build command with local AWS/Python stand-ins."""

import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CodeBuildReportLanguageTests(unittest.TestCase):
    def test_parameter_environment_and_both_command_arguments(self):
        template = (ROOT / "2-observability-assessment-codebuild.yaml").read_text()
        parameter = re.search(
            r"^  ReportLanguage:\n(.*?)(?=^  \w+:|^\w+:)", template, re.M | re.S
        )
        self.assertIsNotNone(parameter, "ReportLanguage parameter is missing")
        block = parameter.group(1)
        self.assertRegex(block, r"Type: String")
        self.assertRegex(block, r"Default: en")
        self.assertRegex(block, r"AllowedValues: \[en, ja\]")
        self.assertRegex(block, r"Description: .+")
        self.assertRegex(
            template,
            r"- Name: REPORT_LANGUAGE\n\s+Value: !Ref ReportLanguage\n\s+Type: PLAINTEXT",
        )
        # Extract the whole existing build command, not a copy of the language logic.
        start = template.index("                  # Resolve caller identity once")
        end = template.index("                - |", start)
        command = textwrap.dedent(template[start:end])
        with tempfile.TemporaryDirectory() as directory:
            task_dir = Path(directory)
            for executable, contents in {
                "aws": '#!/bin/sh\ncase "$*" in\n*"--query Arn"*) echo arn:aws:iam::123456789012:role/Builder;;\n*"--query Account"*) echo 123456789012;;\n*) exit 99;;\nesac\n',
                "python3": '#!/bin/sh\nprintf "%s\\n" "$@" > "$TEST_ARGUMENTS"\n',
            }.items():
                file = task_dir / executable
                file.write_text(contents)
                file.chmod(0o755)
            for mode in ("single", "accounts", "ou"):
                for language in ("en", "ja"):
                    with self.subTest(mode=mode, language=language):
                        arguments = task_dir / "arguments"
                        environment = dict(
                            os.environ,
                            PATH=f"{task_dir}:{os.environ['PATH']}",
                            TEST_ARGUMENTS=str(arguments),
                            ASSESSMENT_REGION="us-west-2",
                            ASSESSMENT_ACCOUNTS="123456789012"
                            if mode == "accounts"
                            else "",
                            ASSESSMENT_OUS="ou-example" if mode == "ou" else "",
                            REPORT_LANGUAGE=language,
                        )
                        result = subprocess.run(
                            ["bash", "-euo", "pipefail", "-c", command],
                            env=environment,
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        expected = [
                            "assessment-src/observability_assessment_comprehensive.py",
                            "--region",
                            "us-west-2",
                        ]
                        if mode == "single":
                            expected += [
                                "--role-arn",
                                "arn:aws:iam::123456789012:role/service-role/ObservabilityAssessmentRole",
                            ]
                        elif mode == "accounts":
                            expected += ["--accounts", "123456789012"]
                        else:
                            expected += ["--ou", "ou-example"]
                        if language == "ja":
                            expected += ["--report-language", "ja"]
                        self.assertEqual(arguments.read_text().splitlines(), expected)
