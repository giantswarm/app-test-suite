import json
import unittest.mock
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch
from pytest_mock import MockerFixture

from app_test_suite.errors import ATSTestError
from app_test_suite.gitops import (
    GitOpsEngine,
    detect_engines,
    install_engine,
    parse_engines_option,
    parse_timeout_to_seconds,
    resolve_engine_overlay,
    wait_for_bundle_drained,
    wait_for_bundle_ready,
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


KUBE_CONFIG = "/mock/kube.config"


@pytest.mark.parametrize(
    "value,expected",
    [("600", 600), ("90s", 90), ("10m", 600), ("1h", 3600)],
    ids=["bare-seconds", "seconds", "minutes", "hours"],
)
def test_parse_timeout_to_seconds(value: str, expected: int) -> None:
    assert parse_timeout_to_seconds(value) == expected


@pytest.mark.parametrize("value", ["", "10x", "m", "1.5m"], ids=["empty", "bad-unit", "no-number", "fraction"])
def test_parse_timeout_to_seconds_rejects(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid timeout"):
        parse_timeout_to_seconds(value)


def _kubectl_result(mocker: MockerFixture, stdout: str = "", returncode: int = 0) -> unittest.mock.Mock:
    result = mocker.Mock(name="KubectlResult")
    type(result).returncode = mocker.PropertyMock(return_value=returncode)
    type(result).stdout = mocker.PropertyMock(return_value=stdout)
    type(result).stderr = mocker.PropertyMock(return_value="kubectl error" if returncode else "")
    return result


def test_install_engine_applies_manifest_and_waits(mocker: MockerFixture, tmp_path: Path) -> None:
    manifest = tmp_path / "flux.yaml"
    manifest.write_text("# flux install manifest")
    run_and_log_mock = mocker.patch("app_test_suite.gitops.run_and_log", return_value=_kubectl_result(mocker))

    install_engine(GitOpsEngine.FLUX, KUBE_CONFIG, str(manifest))

    run_and_log_mock.assert_any_call(
        ["kubectl", f"--kubeconfig={KUBE_CONFIG}", "apply", "--server-side", "-f", str(manifest)],
        capture_output=True,
    )
    run_and_log_mock.assert_any_call(
        [
            "kubectl",
            f"--kubeconfig={KUBE_CONFIG}",
            "--namespace",
            "flux-system",
            "wait",
            "--for=condition=Available",
            "deployment",
            "--all",
            "--timeout=5m",
        ],
        capture_output=True,
    )


def test_install_engine_rejects_missing_manifest(mocker: MockerFixture, tmp_path: Path) -> None:
    run_and_log_mock = mocker.patch("app_test_suite.gitops.run_and_log")

    with pytest.raises(ATSTestError, match="doesn't exist"):
        install_engine(GitOpsEngine.FLUX, KUBE_CONFIG, str(tmp_path / "missing.yaml"))
    run_and_log_mock.assert_not_called()


def test_install_engine_rejects_unimplemented_engine(mocker: MockerFixture) -> None:
    mocker.patch("app_test_suite.gitops.run_and_log")

    with pytest.raises(ATSTestError, match="not implemented yet"):
        install_engine(GitOpsEngine.ARGO, KUBE_CONFIG, "https://example.com/argo.yaml")


def _flux_cr(uid: str, ready: bool, name: str = "child", namespace: str = "default") -> dict:
    return {
        "kind": "HelmRelease",
        "metadata": {"uid": uid, "name": name, "namespace": namespace},
        "status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}]},
    }


def _patch_polls(mocker: MockerFixture, polls: list) -> unittest.mock.Mock:
    """Patch run_and_log so each poll (3 flux resource lists) serves the given CR items."""
    results = []
    for items in polls:
        results.append(_kubectl_result(mocker, json.dumps({"items": items})))
        results.append(_kubectl_result(mocker, json.dumps({"items": []})))
        results.append(_kubectl_result(mocker, json.dumps({"items": []})))
    mocker.patch("app_test_suite.gitops.time.sleep")
    return mocker.patch("app_test_suite.gitops.run_and_log", side_effect=results)


def test_wait_for_bundle_ready_requires_stable_resource_set(mocker: MockerFixture) -> None:
    late_cr_polls = [
        [_flux_cr("uid-a", ready=True)],
        [_flux_cr("uid-a", ready=True), _flux_cr("uid-b", ready=False, name="grandchild")],
        [_flux_cr("uid-a", ready=True), _flux_cr("uid-b", ready=True, name="grandchild")],
    ]
    run_and_log_mock = _patch_polls(mocker, late_cr_polls)

    wait_for_bundle_ready(KUBE_CONFIG, GitOpsEngine.FLUX, timeout_seconds=3600)

    # 3 polls of 3 resource lists each: poll 1 is all-ready but unconfirmed, poll 2 surfaces the
    # late-appearing grandchild (so an early return would have missed it), poll 3 confirms the
    # ready fixpoint against poll 2's resource set
    assert run_and_log_mock.call_count == 9


def test_wait_for_bundle_ready_times_out_on_stuck_cr(mocker: MockerFixture) -> None:
    stuck_polls = [[_flux_cr("uid-a", ready=False)]] * 100
    _patch_polls(mocker, stuck_polls)
    mocker.patch("app_test_suite.gitops.time.monotonic", side_effect=[0, 5, 11])

    with pytest.raises(ATSTestError, match="not ready after 10s"):
        wait_for_bundle_ready(KUBE_CONFIG, GitOpsEngine.FLUX, timeout_seconds=10)


def test_wait_for_bundle_drained(mocker: MockerFixture) -> None:
    polls = [
        [_flux_cr("uid-a", ready=True)],
        [],
    ]
    run_and_log_mock = _patch_polls(mocker, polls)

    wait_for_bundle_drained(KUBE_CONFIG, GitOpsEngine.FLUX, "default-flux", timeout_seconds=3600)

    run_and_log_mock.assert_any_call(
        [
            "kubectl",
            f"--kubeconfig={KUBE_CONFIG}",
            "get",
            "helmreleases.helm.toolkit.fluxcd.io",
            "-o",
            "json",
            "--namespace",
            "default-flux",
        ],
        capture_output=True,
    )


def test_wait_for_bundle_drained_times_out(mocker: MockerFixture) -> None:
    polls = [[_flux_cr("uid-a", ready=True)]] * 100
    _patch_polls(mocker, polls)
    mocker.patch("app_test_suite.gitops.time.monotonic", side_effect=[0, 11])

    with pytest.raises(ATSTestError, match="still present: HelmRelease/default/child"):
        wait_for_bundle_drained(KUBE_CONFIG, GitOpsEngine.FLUX, "default-flux", timeout_seconds=10)
