import unittest.mock
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch
from pytest_mock import MockerFixture

from app_test_suite.errors import ATSTestError
from app_test_suite.gitops import (
    GitOpsEngine,
    detect_engines,
    parse_engines_option,
    resolve_engine_overlay,
)

FLUX_RENDERED_CHART = """
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: catalog
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: child
"""

ARGO_RENDERED_CHART = """
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: child
"""

PLAIN_RENDERED_CHART = """
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
---
# a comment-only document
"""


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("auto", None),
        ("AUTO", None),
        ("helm", []),
        ("flux", [GitOpsEngine.FLUX]),
        ("flux,argo", [GitOpsEngine.FLUX, GitOpsEngine.ARGO]),
        ("argo, flux", [GitOpsEngine.ARGO, GitOpsEngine.FLUX]),
        ("flux,flux", [GitOpsEngine.FLUX]),
    ],
    ids=["none", "empty", "auto", "auto-case", "helm", "flux", "flux-argo", "argo-flux-spaces", "dedup"],
)
def test_parse_engines_option(value: str, expected: list) -> None:
    assert parse_engines_option(value) == expected


def test_parse_engines_option_rejects_unknown_engine() -> None:
    with pytest.raises(ValueError, match="Unknown GitOps engine 'bogus'"):
        parse_engines_option("flux,bogus")


def _mock_helm_template(mocker: MockerFixture, stdout: str, returncode: int = 0) -> unittest.mock.Mock:
    run_res = mocker.Mock(name="HelmTemplateResult")
    type(run_res).returncode = mocker.PropertyMock(return_value=returncode)
    type(run_res).stdout = mocker.PropertyMock(return_value=stdout)
    type(run_res).stderr = mocker.PropertyMock(return_value="rendering error" if returncode else "")
    return mocker.patch("app_test_suite.gitops.run_and_log", return_value=run_res)


@pytest.mark.parametrize(
    "rendered,expected",
    [
        (FLUX_RENDERED_CHART, [GitOpsEngine.FLUX]),
        (ARGO_RENDERED_CHART, [GitOpsEngine.ARGO]),
        (FLUX_RENDERED_CHART + ARGO_RENDERED_CHART, [GitOpsEngine.ARGO, GitOpsEngine.FLUX]),
        (PLAIN_RENDERED_CHART, []),
        ("", []),
    ],
    ids=["flux", "argo", "both", "plain", "empty"],
)
def test_detect_engines(mocker: MockerFixture, rendered: str, expected: list) -> None:
    run_and_log_mock = _mock_helm_template(mocker, rendered)

    assert detect_engines("chart.tgz", []) == expected
    run_and_log_mock.assert_called_once_with(["helm", "template", "chart.tgz"], capture_output=True)


def test_detect_engines_passes_values_files(mocker: MockerFixture) -> None:
    run_and_log_mock = _mock_helm_template(mocker, FLUX_RENDERED_CHART)

    detect_engines("chart.tgz", ["app-config.yaml"])

    run_and_log_mock.assert_called_once_with(
        ["helm", "template", "chart.tgz", "--values", "app-config.yaml"], capture_output=True
    )


def test_detect_engines_raises_on_template_failure(mocker: MockerFixture) -> None:
    _mock_helm_template(mocker, "", returncode=1)

    with pytest.raises(ATSTestError, match="GitOps engine detection"):
        detect_engines("chart.tgz", [])


def test_resolve_engine_overlay_configured_path_wins(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "gitops-values-flux.yaml").write_text("gitops: {}")

    assert resolve_engine_overlay(GitOpsEngine.FLUX, "custom.yaml") == "custom.yaml"


def test_resolve_engine_overlay_uses_convention(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "gitops-values-flux.yaml").write_text("gitops: {}")

    assert resolve_engine_overlay(GitOpsEngine.FLUX, None) == "ci/gitops-values-flux.yaml"
    assert resolve_engine_overlay(GitOpsEngine.ARGO, None) is None
