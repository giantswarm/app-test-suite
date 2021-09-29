import unittest.mock
from typing import cast

import pykube
from configargparse import Namespace
from pytest_helm_charts.giantswarm_app_platform.entities import ConfiguredApp
from pytest_mock import MockerFixture

import app_test_suite
from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.cluster_providers import ExternalClusterProvider
from app_test_suite.cluster_providers.cluster_provider import ClusterInfo, ClusterType
from app_test_suite.steps.base_test_runner import BaseTestRunner

mock_kube_config_path = "/nonexisting-flsdhge235/kube.config"
mock_app_name = "mock_app"
mock_app_ns = "mock_ns"
mock_app_deploy_ns = "mock_deploy_ns"
mock_app_version = "1.2.3"
mock_chart_file_name = "mock_chart.tar.gz"


def assert_deletes_app(configured_app_mock: ConfiguredApp) -> None:
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.delete_app).assert_called_once_with(
        configured_app_mock
    )
    # noinspection PyProtectedMember
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.wait_for_app_to_be_deleted).assert_called_once_with(
        unittest.mock.ANY,
        configured_app_mock.app.name,
        configured_app_mock.app.namespace,
        BaseTestRunner._app_deletion_timeout_sec,
    )


def assert_deploy_and_wait_for_app_cr(app_name: str, app_version: str, app_deploy_ns: str) -> None:
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.create_app).assert_called_once_with(
        unittest.mock.ANY, app_name, app_version, "chartmuseum", "default", app_deploy_ns, None
    )
    # noinspection PyProtectedMember
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.wait_for_apps_to_run).assert_called_once_with(
        unittest.mock.ANY, [app_name], "default", BaseTestRunner._app_deployment_timeout_sec
    )


def assert_chart_file_uploaded(config: Namespace, chart_file_name: str) -> None:
    cast(
        unittest.mock.Mock, app_test_suite.steps.base_test_runner.ChartMuseumAppRepository.upload_artifact
    ).assert_called_once_with(config, chart_file_name)


def assert_app_platform_ready(kube_config_path: str) -> None:
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.run_and_log).assert_called_with(
        ["apptestctl", "bootstrap", f"--kubeconfig-path={kube_config_path}", "--wait"]
    )


def assert_cluster_connection_created(kube_config_path: str) -> None:
    cast(unittest.mock.Mock, pykube.KubeConfig.from_file).assert_called_once_with(kube_config_path)
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.HTTPClient).called_once()


def get_base_config(mocker: MockerFixture) -> Namespace:
    config = mocker.Mock(name="ConfigMock")
    config.app_tests_skip_app_deploy = False
    config.app_tests_deploy_namespace = mock_app_deploy_ns
    config.app_tests_app_config_file = ""
    config.chart_file = mock_chart_file_name
    return config


def get_run_and_log_result_mock(mocker: MockerFixture) -> unittest.mock.Mock:
    system_call_result_mock = mocker.Mock(name="SysCallResult")
    type(system_call_result_mock).returncode = mocker.PropertyMock(return_value=0)
    return system_call_result_mock


def patch_base_test_runner(
    mocker: MockerFixture, run_and_log_res: unittest.mock.Mock, app_name: str, app_namespace: str
) -> ConfiguredApp:
    mocker.patch("pykube.KubeConfig.from_file", name="MockKubeConfig")
    mocker.patch("app_test_suite.steps.base_test_runner.HTTPClient")
    mocker.patch("app_test_suite.steps.base_test_runner.run_and_log", return_value=run_and_log_res)
    mocker.patch("app_test_suite.steps.base_test_runner.ChartMuseumAppRepository.upload_artifact")
    app_cr = mocker.MagicMock(name="appCR")
    app_cr.name = app_name
    app_cr.namespace = app_namespace
    configured_app_mock = ConfiguredApp(app_cr, mocker.MagicMock(name="appCM"))
    mocker.patch("app_test_suite.steps.base_test_runner.create_app", return_value=configured_app_mock)
    mocker.patch("app_test_suite.steps.base_test_runner.wait_for_apps_to_run")
    mocker.patch("app_test_suite.steps.base_test_runner.delete_app")
    mocker.patch("app_test_suite.steps.base_test_runner.wait_for_app_to_be_deleted")
    return configured_app_mock


def get_mock_cluster_manager(mocker: MockerFixture) -> ClusterManager:
    mock_cluster_manager = mocker.MagicMock(spec=ClusterManager, name="MockClusterManager")
    mock_cluster_manager.get_cluster_for_test_type.return_value = ClusterInfo(
        ClusterType("mock"), None, "1.19.1", "mock_cluster_id", mock_kube_config_path, ExternalClusterProvider(), ""
    )
    return mock_cluster_manager
