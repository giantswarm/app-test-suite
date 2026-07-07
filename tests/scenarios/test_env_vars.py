import pytest

from app_test_suite.steps.base import TestExecInfo
from app_test_suite.steps.executors.pytest import PytestExecutor


def test_ats_output_env_vars_win_over_ambient_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """ATS_CLUSTER_TYPE / ATS_CLUSTER_VERSION double as input-option env vars (via the 'ATS_'
    auto-env-var prefix for '--cluster-type' / '--cluster-version') and as output vars exported to
    the tests. A stale value in the ambient environment must not shadow the value ATS resolved for
    this run (for example one passed explicitly on the command line), and KUBECONFIG must point at
    the test cluster regardless of any ambient KUBECONFIG."""
    monkeypatch.setenv("ATS_CLUSTER_TYPE", "stale-env-type")
    monkeypatch.setenv("ATS_CLUSTER_VERSION", "stale-env-version")
    monkeypatch.setenv("KUBECONFIG", "/stale/kube.config")

    exec_info = TestExecInfo(
        chart_path="chart.tgz",
        chart_ver="1.2.3",
        app_config_file_path=None,
        cluster_type="resolved-type",
        cluster_version="resolved-version",
        kube_config_path="/resolved/kube.config",
        test_type="smoke",
        debug=False,
    )

    env = PytestExecutor().get_test_info_env_variables(exec_info)

    assert env["ATS_CLUSTER_TYPE"] == "resolved-type"
    assert env["ATS_CLUSTER_VERSION"] == "resolved-version"
    assert env["KUBECONFIG"] == "/resolved/kube.config"
