import unittest.mock
from typing import cast

import pykube
from configargparse import Namespace
from pytest_mock import MockerFixture

import app_test_suite
from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.cluster_providers import ExternalClusterProvider
from app_test_suite.cluster_providers.cluster_provider import ClusterInfo, ClusterType
from app_test_suite.steps.base_test_runner import context_key_chart_yaml, BaseTestRunner
from app_test_suite.steps.pytest.pytest import PytestSmokeTestRunner, PytestUpgradeTestRunner

mock_kube_config_path = "/nonexisting-flsdhge235/kube.config"
mock_app_name = "mock_app"
mock_app_deploy_ns = "mock_deploy_ns"
mock_app_version = "1.2.3"
mock_chart_file_name = "mock_chart.tar.gz"


def test_upgrade_pytest_runner_run(mocker: MockerFixture) -> None:
    mock_cluster_manager = get_mock_cluster_manager(mocker)
    run_and_log_call_result_mock = get_run_and_log_result_mock(mocker)
    patch_base_test_runner(mocker, run_and_log_call_result_mock)

    mocker.patch("app_test_suite.steps.pytest.pytest.run_and_log", return_value=run_and_log_call_result_mock)

    mocker.patch("app_test_suite.steps.upgrade_test_runner.get_app_catalog_obj")
    mocker.patch("app_test_suite.steps.upgrade_test_runner.run_and_log", return_value=run_and_log_call_result_mock)

    mock_app_catalog_cr = mocker.MagicMock(name="AppCatalogCR mock")
    app_catalog_cr_objects_res = mocker.MagicMock(name="AppCatalogCR.objects()")
    app_catalog_cr_objects_res.get_or_none.return_value = mock_app_catalog_cr
    mocker.patch(
        "app_test_suite.steps.upgrade_test_runner.AppCatalogCR.objects", return_value=app_catalog_cr_objects_res
    )

    # app_catalog_cr = AppCatalogCR.objects(self._kube_client).get_or_none(name=self._STABLE_APP_CATALOG_NAME)

    config = get_config(mocker)
    config.upgrade_tests_app_catalog_url = "http://chartmuseum-chartmuseum.giantswarm:8080/charts/"
    config.upgrade_tests_app_version = "0.2.4-1"
    config.app_tests_app_config_file = ""
    config.upgrade_tests_app_config_file = ""
    config.upgrade_tests_upgrade_hook = "mock.sh"
    # normally, `pre_run` method does this in this case to stop the default logic from
    # deploying the current chart before the stable chart can be deployed
    # since we're not calling pre_run() here, we need override in config
    config.app_tests_skip_app_deploy = True

    context = {context_key_chart_yaml: {"name": mock_app_name, "version": mock_app_version}}
    runner = PytestUpgradeTestRunner(mock_cluster_manager)
    runner.run(config, context)


def test_pytest_smoke_runner_run(mocker: MockerFixture) -> None:
    mock_cluster_manager = get_mock_cluster_manager(mocker)
    run_and_log_call_result_mock = get_run_and_log_result_mock(mocker)

    patch_base_test_runner(mocker, run_and_log_call_result_mock)

    mocker.patch("app_test_suite.steps.pytest.pytest.run_and_log", return_value=run_and_log_call_result_mock)

    config = get_config(mocker)
    context = {context_key_chart_yaml: {"name": mock_app_name, "version": mock_app_version}}
    runner = PytestSmokeTestRunner(mock_cluster_manager)
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
    ).assert_called_once_with(config, mock_chart_file_name)
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
            runner.test_provided,
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
            f"--junitxml=test_results_{runner.test_provided}.xml",
        ],
        cwd="",
    )
    # deletes app
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.delete_app).assert_called_once()
    cast(unittest.mock.Mock, app_test_suite.steps.base_test_runner.wait_for_app_to_be_deleted).assert_called_once()


def get_config(mocker: MockerFixture) -> Namespace:
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


def patch_base_test_runner(mocker: MockerFixture, run_and_log_res: unittest.mock.Mock) -> None:
    mocker.patch("pykube.KubeConfig.from_file", name="MockKubeConfig")
    mocker.patch("app_test_suite.steps.base_test_runner.HTTPClient")
    mocker.patch("app_test_suite.steps.base_test_runner.run_and_log", return_value=run_and_log_res)
    mocker.patch("app_test_suite.steps.base_test_runner.ChartMuseumAppRepository.upload_artifact")
    mocker.patch("app_test_suite.steps.base_test_runner.create_app")
    mocker.patch("app_test_suite.steps.base_test_runner.wait_for_apps_to_run")
    mocker.patch("app_test_suite.steps.base_test_runner.delete_app")
    mocker.patch("app_test_suite.steps.base_test_runner.wait_for_app_to_be_deleted")


def get_mock_cluster_manager(mocker: MockerFixture) -> ClusterManager:
    mock_cluster_manager = mocker.MagicMock(spec=ClusterManager, name="MockClusterManager")
    mock_cluster_manager.get_cluster_for_test_type.return_value = ClusterInfo(
        ClusterType("mock"), None, "1.19.1", "mock_cluster_id", mock_kube_config_path, ExternalClusterProvider(), ""
    )
    return mock_cluster_manager
