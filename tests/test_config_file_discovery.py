"""Tests for ATS config file discovery in __main__.

.ats/main.yaml is the canonical config file name; .ats/main.yml is also
accepted so repos that default to the shorter YAML extension don't silently
have their overrides ignored.
"""

import os
from pathlib import Path

import pytest

from app_test_suite.__main__ import get_default_config_file_paths


def test_cwd_yaml_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ats_dir = tmp_path / ".ats"
    ats_dir.mkdir()
    (ats_dir / "main.yaml").write_text("smoke-tests-cluster-type: kind\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["ats", "--debug"])

    paths = get_default_config_file_paths()

    assert os.path.join(str(tmp_path), ".ats", "main.yaml") in paths


def test_cwd_yml_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ats_dir = tmp_path / ".ats"
    ats_dir.mkdir()
    (ats_dir / "main.yml").write_text("smoke-tests-cluster-type: kind\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["ats", "--debug"])

    paths = get_default_config_file_paths()

    assert os.path.join(str(tmp_path), ".ats", "main.yml") in paths


def test_yaml_takes_precedence_over_yml_when_both_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ats_dir = tmp_path / ".ats"
    ats_dir.mkdir()
    (ats_dir / "main.yml").write_text("smoke-tests-cluster-type: external\n")
    (ats_dir / "main.yaml").write_text("smoke-tests-cluster-type: kind\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["ats", "--debug"])

    paths = get_default_config_file_paths()

    yml_path = os.path.join(str(tmp_path), ".ats", "main.yml")
    yaml_path = os.path.join(str(tmp_path), ".ats", "main.yaml")
    # .yaml must be parsed last so it wins when both files set the same key
    assert paths.index(yml_path) < paths.index(yaml_path)


def test_chart_relative_yml_is_also_a_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    chart_ats_dir = root / "sub" / ".ats"
    chart_ats_dir.mkdir(parents=True)
    (chart_ats_dir / "main.yml").write_text("functional-tests-cluster-type: kind\n")
    chart_file = root / "sub" / "mychart.tgz"
    chart_file.write_text("x")
    monkeypatch.chdir(root)
    monkeypatch.setattr("sys.argv", ["ats", "-c", str(chart_file)])

    paths = get_default_config_file_paths()

    assert os.path.join(str(root), "sub", ".ats", "main.yml") in paths
