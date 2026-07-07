"""Tests for automatic test-executor detection and chart-file discovery in __main__.

The single ``--tests-dir`` option replaced the per-executor ``--app-tests-{pytest,gotest}-tests-dir``
options; the executor is now auto-detected from marker files in that directory ('go.mod' -> gotest,
'pyproject.toml' -> pytest).
"""

import os
from pathlib import Path

import pytest
from _pytest.logging import LogCaptureFixture

from app_test_suite.__main__ import (
    TEST_EXECUTOR_GOTEST,
    TEST_EXECUTOR_PYTEST,
    detect_test_executor,
    get_chart_file_from_argv,
)

DEFAULT_TESTS_DIR = os.path.join("tests", "ats")


def _make_tests_dir(base: Path, *marker_files: str) -> None:
    tests_dir = base / "tests" / "ats"
    tests_dir.mkdir(parents=True)
    for marker in marker_files:
        (tests_dir / marker).write_text("x")


def test_detect_gotest_from_gomod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_tests_dir(tmp_path, "go.mod", "main_test.go")
    monkeypatch.chdir(tmp_path)

    assert detect_test_executor(DEFAULT_TESTS_DIR, None) == TEST_EXECUTOR_GOTEST


def test_detect_pytest_from_pyproject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_tests_dir(tmp_path, "pyproject.toml", "test_example.py")
    monkeypatch.chdir(tmp_path)

    assert detect_test_executor(DEFAULT_TESTS_DIR, None) == TEST_EXECUTOR_PYTEST


def test_detect_defaults_to_pytest_when_both_markers_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    _make_tests_dir(tmp_path, "go.mod", "pyproject.toml")
    monkeypatch.chdir(tmp_path)

    import logging

    with caplog.at_level(logging.WARNING):
        detected = detect_test_executor(DEFAULT_TESTS_DIR, None)

    assert detected == TEST_EXECUTOR_PYTEST
    assert any("can't be" in rec.message for rec in caplog.records)


def test_detect_defaults_to_pytest_when_no_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    _make_tests_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    import logging

    with caplog.at_level(logging.WARNING):
        detected = detect_test_executor(DEFAULT_TESTS_DIR, None)

    assert detected == TEST_EXECUTOR_PYTEST
    assert any("auto-detect" in rec.message for rec in caplog.records)


def test_detect_uses_legacy_chart_relative_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # tests live next to the chart file, not relative to CWD (the deprecated legacy layout)
    root = tmp_path / "root"
    _make_tests_dir(root / "sub", "go.mod")
    chart_file = root / "sub" / "mychart.tgz"
    chart_file.write_text("x")
    monkeypatch.chdir(root)

    assert detect_test_executor(DEFAULT_TESTS_DIR, str(chart_file)) == TEST_EXECUTOR_GOTEST


def test_get_chart_file_from_argv_long_and_short(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["ats", "-c", "charts/my.tgz", "--test-executor", "auto"])
    assert get_chart_file_from_argv() == "charts/my.tgz"

    monkeypatch.setattr("sys.argv", ["ats", "--chart-file", "other/my.tgz"])
    assert get_chart_file_from_argv() == "other/my.tgz"

    monkeypatch.setattr("sys.argv", ["ats", "--debug"])
    assert get_chart_file_from_argv() is None
