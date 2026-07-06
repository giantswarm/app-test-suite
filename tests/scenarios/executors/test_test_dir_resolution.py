"""Tests for test source directory discovery (issue #196).

Tests must be discovered relative to the executing directory (the current working directory), so the
chart archive under test can live anywhere. A legacy fallback to the chart-file-relative location is
kept for backward compatibility.
"""

import argparse
import os
from pathlib import Path

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture
from step_exec_lib.errors import ValidationError

from app_test_suite.steps.base import TestExecutor
from app_test_suite.steps.executors.gotest import GotestExecutor
from app_test_suite.steps.executors.pytest import PytestExecutor

PYTEST_TESTS_DIR_ATTR = "app_tests_pytest_tests_dir"
GOTEST_TESTS_DIR_ATTR = "app_tests_gotest_tests_dir"
DEFAULT_TESTS_DIR = os.path.join("tests", "ats")


def _make_config(chart_file: str, tests_dir: str = DEFAULT_TESTS_DIR) -> argparse.Namespace:
    config = argparse.Namespace()
    config.chart_file = chart_file
    setattr(config, PYTEST_TESTS_DIR_ATTR, tests_dir)
    setattr(config, GOTEST_TESTS_DIR_ATTR, tests_dir)
    return config


def _touch(dir_path: Path, file_name: str) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / file_name).write_text("x")


def test_resolve_test_dir_prefers_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # tests live relative to the working directory; the chart archive lives somewhere else entirely
    project = tmp_path / "project"
    (project / "tests" / "ats").mkdir(parents=True)
    chart_file = tmp_path / "charts" / "mychart.tgz"
    chart_file.parent.mkdir(parents=True)
    chart_file.write_text("x")
    monkeypatch.chdir(project)

    resolved = TestExecutor._resolve_test_dir(_make_config(str(chart_file)), DEFAULT_TESTS_DIR)

    assert resolved == str(project / "tests" / "ats")


def test_resolve_test_dir_falls_back_to_chart_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    # legacy layout: no tests relative to CWD, but they exist next to the chart file
    root = tmp_path / "root"
    (root / "sub" / "tests" / "ats").mkdir(parents=True)
    chart_file = root / "sub" / "mychart.tgz"
    chart_file.write_text("x")
    monkeypatch.chdir(root)

    import logging

    with caplog.at_level(logging.WARNING):
        resolved = TestExecutor._resolve_test_dir(_make_config(str(chart_file)), DEFAULT_TESTS_DIR)

    assert resolved == str(root / "sub" / "tests" / "ats")
    assert any("deprecated" in rec.message for rec in caplog.records)


def test_resolve_test_dir_points_at_cwd_when_nothing_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chart_file = tmp_path / "mychart.tgz"
    chart_file.write_text("x")
    monkeypatch.chdir(tmp_path)

    resolved = TestExecutor._resolve_test_dir(_make_config(str(chart_file)), DEFAULT_TESTS_DIR)

    # points at the recommended working-directory-relative location so the error message guides the user there
    assert resolved == str(tmp_path / "tests" / "ats")


def test_resolve_test_dir_honors_absolute_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    abs_tests = tmp_path / "elsewhere" / "mytests"
    abs_tests.mkdir(parents=True)
    chart_file = tmp_path / "charts" / "mychart.tgz"
    chart_file.parent.mkdir(parents=True)
    chart_file.write_text("x")
    monkeypatch.chdir(tmp_path)

    resolved = TestExecutor._resolve_test_dir(_make_config(str(chart_file), str(abs_tests)), str(abs_tests))

    assert resolved == str(abs_tests)


def test_pytest_validate_discovers_tests_in_cwd_with_chart_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    project = tmp_path / "project"
    _touch(project / "tests" / "ats", "test_example.py")
    chart_file = tmp_path / "charts" / "mychart.tgz"
    chart_file.parent.mkdir(parents=True)
    chart_file.write_text("x")
    monkeypatch.chdir(project)
    mocker.patch("app_test_suite.steps.executors.pytest.shutil.which", return_value="/usr/bin/uv")

    executor = PytestExecutor()
    executor.validate(_make_config(str(chart_file)), "SmokeTestScenario")

    assert executor._test_dir == str(project / "tests" / "ats")


def test_gotest_validate_discovers_tests_in_cwd_with_chart_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    _touch(project / "tests" / "ats", "main_test.go")
    chart_file = tmp_path / "charts" / "mychart.tgz"
    chart_file.parent.mkdir(parents=True)
    chart_file.write_text("x")
    monkeypatch.chdir(project)

    executor = GotestExecutor()
    executor.validate(_make_config(str(chart_file)), "SmokeTestScenario")

    assert executor._test_dir == str(project / "tests" / "ats")


def test_pytest_validate_errors_point_at_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    chart_file = tmp_path / "charts" / "mychart.tgz"
    chart_file.parent.mkdir(parents=True)
    chart_file.write_text("x")
    monkeypatch.chdir(tmp_path)
    mocker.patch("app_test_suite.steps.executors.pytest.shutil.which", return_value="/usr/bin/uv")

    with pytest.raises(ValidationError) as exc_info:
        PytestExecutor().validate(_make_config(str(chart_file)), "SmokeTestScenario")

    assert str(tmp_path / "tests" / "ats") in exc_info.value.msg
