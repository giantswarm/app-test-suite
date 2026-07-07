import os
import shutil
import unittest
import unittest.mock
from typing import cast
from unittest.mock import Mock

import pykube
import yaml
from configargparse import Namespace
from pytest_mock import MockerFixture

import app_test_suite
from app_test_suite.cluster_manager import ClusterManager, ClusterInfo
from app_test_suite.steps.scenarios.simple import _HELM_BIN, _HELM_DEPLOY_TIMEOUT

MOCK_KUBE_CONFIG_PATH = "/nonexisting-flsdhge235/kube.config"
MOCK_KUBE_VERSION = "1.19.1"
MOCK_APP_NAME = "mock_app"
MOCK_APP_NS = "mock_ns"
MOCK_APP_DEPLOY_NS = "mock_deploy_ns"
MOCK_APP_VERSION = "0.1.2"
MOCK_CHART_VERSION = "0.2.5"
MOCK_CHART_FILE_NAME = f"{MOCK_APP_NAME}-{MOCK_CHART_VERSION}.tgz"
MOCK_UPGRADE_UPGRADE_HOOK = "mock.sh"
MOCK_UPGRADE_APP_CONFIG_FILE = ""
MOCK_UPGRADE_APP_VERSION = "0.2.4-1"
MOCK_UPGRADE_CATALOG_URL = "http://mock-chart-repo.example.com"
MOCK_STABLE_APP_FILE = f"examples/apps/hello-world-app/hello-world-app-{MOCK_UPGRADE_APP_VERSION}.tgz"
UPGRADE_META_FILE_NAME = f"tested-upgrade-{MOCK_CHART_VERSION}.yaml"


def _helm_deploy_args(release_name: str, chart_file: str, deploy_namespace: str, values_file: str = "") -> list:
    args = [
        _HELM_BIN,
        "upgrade",
        "--install",
        release_name,
        chart_file,
        "--namespace",
        deploy_namespace,
        "--create-namespace",
        "--reset-values",
        "--wait",
        "--timeout",
        _HELM_DEPLOY_TIMEOUT,
    ]
    if values_file:
        args += ["--values", values_file]
    return args


def assert_helm_deployed(
    release_name: str,
    chart_file: str,
    deploy_namespace: str,
    kube_config_path: str,
    values_file: str = "",
) -> None:
    cast(Mock, app_test_suite.steps.scenarios.simple.run_and_log).assert_any_call(
        _helm_deploy_args(release_name, chart_file, deploy_namespace, values_file),
        env={"KUBECONFIG": kube_config_path},
    )


def assert_helm_uninstalled(release_name: str, deploy_namespace: str, kube_config_path: str) -> None:
    cast(Mock, app_test_suite.steps.scenarios.simple.run_and_log).assert_any_call(
        [_HELM_BIN, "uninstall", release_name, "--namespace", deploy_namespace, "--wait"],
        env={"KUBECONFIG": kube_config_path},
    )


def assert_cluster_prerequisites_ready(kube_config_path: str) -> None:
    cast(unittest.mock.Mock, app_test_suite.steps.scenarios.simple.run_and_log).assert_any_call(
        ["kubectl", f"--kubeconfig={kube_config_path}", "apply", "--server-side", "-f", "/etc/ats/crds"],
        capture_output=True,
    )


def assert_cluster_connection_created(kube_config_path: str) -> None:
    cast(unittest.mock.Mock, pykube.KubeConfig.from_file).assert_called_once_with(kube_config_path)
    cast(unittest.mock.Mock, app_test_suite.steps.scenarios.simple.HTTPClient).assert_called_once()


def get_base_config(mocker: MockerFixture) -> Namespace:
    config = mocker.Mock(name="ConfigMock")
    config.app_tests_skip_app_deploy = False
    config.app_tests_skip_app_delete = False
    config.app_tests_deploy_namespace = MOCK_APP_DEPLOY_NS
    config.app_tests_app_config_file = ""
    config.app_tests_pre_deploy_script = ""
    config.app_tests_pre_hook = ""
    config.app_tests_post_hook = ""
    config.chart_file = MOCK_CHART_FILE_NAME
    config.debug = False
    return config


def get_run_and_log_result_mock(mocker: MockerFixture) -> unittest.mock.Mock:
    system_call_result_mock = mocker.Mock(name="SysCallResult")
    type(system_call_result_mock).returncode = mocker.PropertyMock(return_value=0)
    type(system_call_result_mock).stdout = mocker.PropertyMock(return_value="")
    type(system_call_result_mock).stderr = mocker.PropertyMock(return_value="")
    return system_call_result_mock


def patch_base_test_runner(
    mocker: MockerFixture,
    run_and_log_res: unittest.mock.Mock,
    app_name: str = "",
    app_namespace: str = "",
) -> None:
    mocker.patch.dict(os.environ, {}, clear=True)
    mocker.patch("pykube.KubeConfig.from_file", name="MockKubeConfig")
    mocker.patch("app_test_suite.steps.scenarios.simple.HTTPClient")
    mocker.patch(
        "app_test_suite.steps.scenarios.simple.run_and_log",
        return_value=run_and_log_res,
    )
    mocker.patch("app_test_suite.steps.scenarios.simple.ensure_namespace_exists")


def get_mock_cluster_manager(mocker: MockerFixture) -> ClusterManager:
    mock_cluster_manager = mocker.MagicMock(spec=ClusterManager, name="MockClusterManager")
    mock_cluster_manager.get_cluster.return_value = ClusterInfo(
        kube_config_path=MOCK_KUBE_CONFIG_PATH,
        cluster_type="mock",
        version=MOCK_KUBE_VERSION,
    )
    return mock_cluster_manager


def configure_for_upgrade_test(config: Namespace) -> None:
    config.upgrade_tests_app_catalog_url = ""
    config.upgrade_tests_app_file = MOCK_STABLE_APP_FILE
    config.upgrade_tests_app_version = ""
    config.upgrade_tests_app_config_file = MOCK_UPGRADE_APP_CONFIG_FILE
    config.upgrade_tests_upgrade_hook = MOCK_UPGRADE_UPGRADE_HOOK
    config.upgrade_tests_save_metadata = True
    # normally, `pre_run` method does this in this case to stop the default logic from
    # deploying the current chart before the stable chart can be deployed
    # since we're not calling pre_run() here, we need override in config
    config.app_tests_skip_app_deploy = True


def patch_upgrade_test_runner(mocker: MockerFixture, run_and_log_call_result_mock: unittest.mock.Mock) -> None:
    mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.run_and_log",
        return_value=run_and_log_call_result_mock,
    )


def assert_upgrade_tester_exec_hook(
    stage_name: str,
    app_name: str,
    from_version: str,
    to_version: str,
    kube_config_path: str,
    deploy_namespace: str,
) -> None:
    run_and_log_mock = cast(unittest.mock.Mock, app_test_suite.steps.scenarios.upgrade.run_and_log)
    hook_call = next(
        c
        for c in run_and_log_mock.call_args_list
        if c.args[0] == [MOCK_UPGRADE_UPGRADE_HOOK] and c.kwargs.get("env", {}).get("ATS_HOOK_STAGE") == stage_name
    )
    env = hook_call.kwargs["env"]
    assert env["ATS_TEST_TYPE"] == "upgrade"
    assert env["ATS_RELEASE_NAME"] == app_name
    assert env["ATS_UPGRADE_FROM_VERSION"] == from_version
    assert env["ATS_UPGRADE_TO_VERSION"] == to_version
    assert env["KUBECONFIG"] == kube_config_path
    assert env["ATS_RELEASE_NAMESPACE"] == deploy_namespace


def assert_upgrade_metadata_created() -> None:
    meta_dir = f"{MOCK_APP_NAME}-{MOCK_UPGRADE_APP_VERSION}.tgz-meta"
    with open(os.path.join(meta_dir, UPGRADE_META_FILE_NAME)) as f:
        actual = yaml.safe_load(f.read())
        actual.pop("timestamp", None)
    with open(os.path.join("tests", "assets", UPGRADE_META_FILE_NAME), "r") as f:
        expected = yaml.safe_load(f.read())
        expected.pop("timestamp", None)
    assert actual == expected
    shutil.rmtree(meta_dir)
