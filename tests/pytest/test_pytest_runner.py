import unittest.mock
from typing import cast

import pykube
from pytest_mock import MockerFixture

import app_test_suite
from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.cluster_providers import ExternalClusterProvider
from app_test_suite.cluster_providers.cluster_provider import ClusterInfo, ClusterType
from app_test_suite.steps.base_test_runner import context_key_chart_yaml, BaseTestRunner
from app_test_suite.steps.pytest.pytest import PytestTestRunner
from step_exec_lib.types import StepType

STEP_TEST_TEST = StepType("test")


class PytestTestTimeRunner(PytestTestRunner):
    def __init__(self, cluster_manager: ClusterManager):
        super().__init__(cluster_manager)

    @property
    def test_provided(self) -> StepType:
        return STEP_TEST_TEST


mock_kube_config_path = "/nonexisting-flsdhge235/kube.config"
mock_app_name = "mock_app"
mock_app_deploy_ns = "mock_deploy_ns"
mock_app_version = "1.2.3"


def test_pytest_runner_run(mocker: MockerFixture) -> None:
    mock_cluster_manager = mocker.MagicMock(spec=ClusterManager, name="MockClusterManager")
    mock_cluster_manager.get_cluster_for_test_type.return_value = ClusterInfo(
        ClusterType("mock"), None, "1.19.1", "mock_cluster_id", mock_kube_config_path, ExternalClusterProvider(), ""
    )

    mocker.patch("pykube.KubeConfig.from_file", name="MockKubeConfig")
    mocker.patch("app_test_suite.steps.base_test_runner.HTTPClient")
    system_call_result_mock = mocker.Mock(name="SysCallResult")
    type(system_call_result_mock).returncode = mocker.PropertyMock(return_value=0)
    mocker.patch("app_test_suite.steps.base_test_runner.run_and_log", return_value=system_call_result_mock)
    mocker.patch("app_test_suite.steps.base_test_runner.ChartMuseumAppRepository.upload_artifacts")
    mocker.patch("app_test_suite.steps.base_test_runner.create_app")
    mocker.patch("app_test_suite.steps.base_test_runner.wait_for_apps_to_run")
    mocker.patch("app_test_suite.steps.base_test_runner.delete_app")
    mocker.patch("app_test_suite.steps.base_test_runner.wait_for_app_to_be_deleted")

    mocker.patch("app_test_suite.steps.pytest.pytest.run_and_log", return_value=system_call_result_mock)

    config = mocker.Mock(name="ConfigMock")
    config.app_tests_skip_app_deploy = False
    config.app_tests_deploy_namespace = mock_app_deploy_ns
    config.app_tests_app_config_file = ""
    config.chart_file = "mock_chart.tar.gz"
    context = {context_key_chart_yaml: {"name": mock_app_name, "version": mock_app_version}}
    runner = PytestTestTimeRunner(mock_cluster_manager)
    runner.run(config, context)

    # assert step created connection with correct config file
    cast(unittest.mock.Mock, pykube.KubeConfig.from_file).assert_called_once_with(mock_kube_config_path)
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.HTTPClient).called_once()
    # assert ensure app platform ready
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.run_and_log).assert_called_with(
        ["apptestctl", "bootstrap", f"--kubeconfig-path={mock_kube_config_path}", "--wait"]
    )
    # uploaded the correct chart to chart repository
    cast(
        unittest.mock.Mock, app_test_suite.steps.base_test_runner.ChartMuseumAppRepository.upload_artifact
    ).assert_called_once_with(config, context)
    # deploys app cr and waits for it to run
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.create_app).assert_called_once_with(
        unittest.mock.ANY, mock_app_name, mock_app_version, "chartmuseum", "default", mock_app_deploy_ns, None
    )
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.wait_for_apps_to_run).assert_called_once_with(
        unittest.mock.ANY, [mock_app_name], "default", BaseTestRunner._app_deployment_timeout_sec
    )
    # installs deps with pipenv and runs pytest
    assert cast(unittest.mock.Mock, app_test_suite.steps.pytest.pytest.run_and_log).call_args_list[0].args[0] == [
        "pipenv",
        "install",
        "--deploy",
    ]
    cast(unittest.mock.Mock, app_test_suite.steps.pytest.pytest.run_and_log).assert_called_with(
        [
            "pipenv",
            "run",
            "pytest",
            "-m",
            STEP_TEST_TEST,
            "--cluster-type",
            "mock",
            "--kube-config",
            mock_kube_config_path,
            "--chart-path",
            config.chart_file,
            "--chart-version",
            mock_app_version,
            "--chart-extra-info",
            "external_cluster_version=1.19.1",
            "--log-cli-level",
            "info",
            f"--junitxml=test_results_{STEP_TEST_TEST}.xml",
        ],
        cwd="",
    )
    # deletes app
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.delete_app).assert_called_once()
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.wait_for_app_to_be_deleted).assert_called_once()
