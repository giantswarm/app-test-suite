"""Tests for the cluster options removed in 1.0.0, which are still accepted and ignored with a warning.

Many charts still carry ATS 0.x keys such as 'smoke-tests-cluster-type: kind' in '.ats/main.yaml'. Without
these options registered, configargparse turns every such key into an 'unrecognized arguments' error.
"""

import os
from pathlib import Path

import pytest
from _pytest.logging import LogCaptureFixture

from app_test_suite.__main__ import DEPRECATED_IGNORED_OPTIONS, get_config


@pytest.fixture(autouse=True)
def _no_ats_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    # get_config also reads 'ATS_*' env vars, which would leak a developer's settings into these tests
    for key in list(os.environ):
        if key.startswith("ATS_"):
            monkeypatch.delenv(key)


def _deprecation_warnings(caplog: LogCaptureFixture) -> list[str]:
    return [rec.message for rec in caplog.records if "was removed in app-test-suite 1.0.0" in rec.message]


def test_removed_options_in_config_file_are_ignored_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    ats_dir = tmp_path / ".ats"
    ats_dir.mkdir()
    (ats_dir / "main.yaml").write_text(
        "".join(f"{option.lstrip('-')}: some-value\n" for option in DEPRECATED_IGNORED_OPTIONS)
        + "skip-steps: [upgrade]\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["ats"])

    config = get_config([])

    assert config.skip_steps == ["upgrade"]
    warnings = _deprecation_warnings(caplog)
    assert len(warnings) == len(DEPRECATED_IGNORED_OPTIONS)
    for option in DEPRECATED_IGNORED_OPTIONS:
        assert any(f"'{option}'" in message for message in warnings)


def test_removed_options_on_command_line_are_ignored_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    # the form configargparse produces from a 0.x '.ats/main.yaml', as seen in the 1.x CI failures
    monkeypatch.setattr("sys.argv", ["ats", "--smoke-tests-cluster-type=kind", "--upgrade-tests-cluster-type", "kind"])

    get_config([])

    warnings = _deprecation_warnings(caplog)
    assert len(warnings) == 2
    assert "'--smoke-tests-cluster-type'" in warnings[0]
    assert "'--upgrade-tests-cluster-type'" in warnings[1]


def test_removed_options_from_env_vars_are_ignored_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["ats"])
    monkeypatch.setenv("ATS_SMOKE_TESTS_CLUSTER_TYPE", "kind")

    get_config([])

    warnings = _deprecation_warnings(caplog)
    assert len(warnings) == 1
    assert "'--smoke-tests-cluster-type'" in warnings[0]


def test_warning_is_logged_before_config_validation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["ats", "--smoke-tests-cluster-type=kind", "--steps", "no-such-step"])

    with pytest.raises(SystemExit):
        get_config([])

    assert len(_deprecation_warnings(caplog)) == 1


def test_no_warning_without_removed_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["ats", "--skip-steps", "upgrade"])

    get_config([])

    assert _deprecation_warnings(caplog) == []


def test_other_unknown_options_still_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["ats", "--no-such-option=kind"])

    with pytest.raises(SystemExit) as exc:
        get_config([])

    assert exc.value.code == 2
    assert "unrecognized arguments: --no-such-option=kind" in capsys.readouterr().err
