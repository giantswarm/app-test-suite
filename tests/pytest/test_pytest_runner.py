import unittest.mock
from typing import cast

from configargparse import Namespace
from pytest_mock import MockerFixture

import app_test_suite
from app_test_suite.steps.base_test_runner import context_key_chart_yaml
from app_test_suite.steps.pytest.pytest import PytestSmokeTestRunner, PytestUpgradeTestRunner
from step_exec_lib.types import StepType
from tests.helpers import (
    assert_deletes_app,
    assert_deploy_and_wait_for_app_cr,
    assert_chart_file_uploaded,
    assert_app_platform_ready,
    assert_cluster_connection_created,
    get_base_config,
    get_run_and_log_result_mock,
    patch_base_test_runner,
    get_mock_cluster_manager,
    mock_app_name,
    mock_app_ns,
    mock_app_version,
    mock_kube_config_path,
    mock_chart_file_name,
    mock_app_deploy_ns,
)


def test_upgrade_pytest_runner_run(mocker: MockerFixture) -> None:
    mock_cluster_manager = get_mock_cluster_manager(mocker)
    run_and_log_call_result_mock = get_run_and_log_result_mock(mocker)

    configured_app_mock = patch_base_test_runner(mocker, run_and_log_call_result_mock, mock_app_name, mock_app_ns)
    patch_pytest_test_runner(mocker, run_and_log_call_result_mock)
    mock_app_catalog_cr = patch_upgrade_test_runner(mocker, run_and_log_call_result_mock)

    config = get_base_config(mocker)
    configure_for_upgrade_test(config)

    context = {context_key_chart_yaml: {"name": mock_app_name, "version": mock_app_version}}
    runner = PytestUpgradeTestRunner(mock_cluster_manager)
    runner.run(config, context)


def configure_for_upgrade_test(config: Namespace):
    config.upgrade_tests_app_catalog_url = "http://chartmuseum-chartmuseum.giantswarm:8080/charts/"
    config.upgrade_tests_app_version = "0.2.4-1"
    config.upgrade_tests_app_config_file = ""
    config.upgrade_tests_upgrade_hook = "mock.sh"
    # normally, `pre_run` method does this in this case to stop the default logic from
    # deploying the current chart before the stable chart can be deployed
    # since we're not calling pre_run() here, we need override in config
    config.app_tests_skip_app_deploy = True


def patch_upgrade_test_runner(
    mocker: MockerFixture, run_and_log_call_result_mock: unittest.mock.Mock
) -> unittest.mock.Mock:
    mocker.patch("app_test_suite.steps.upgrade_test_runner.get_app_catalog_obj")
    mocker.patch("app_test_suite.steps.upgrade_test_runner.run_and_log", return_value=run_and_log_call_result_mock)
    mock_app_catalog_cr = mocker.MagicMock(name="AppCatalogCR mock")
    app_catalog_cr_objects_res = mocker.MagicMock(name="AppCatalogCR.objects()")
    app_catalog_cr_objects_res.get_or_none.return_value = mock_app_catalog_cr
    mocker.patch(
        "app_test_suite.steps.upgrade_test_runner.AppCatalogCR.objects", return_value=app_catalog_cr_objects_res
    )
    return mock_app_catalog_cr


def test_pytest_smoke_runner_run(mocker: MockerFixture) -> None:
    mock_cluster_manager = get_mock_cluster_manager(mocker)
    run_and_log_call_result_mock = get_run_and_log_result_mock(mocker)

    configured_app_mock = patch_base_test_runner(mocker, run_and_log_call_result_mock, mock_app_name, mock_app_ns)
    patch_pytest_test_runner(mocker, run_and_log_call_result_mock)

    config = get_base_config(mocker)
    context = {context_key_chart_yaml: {"name": mock_app_name, "version": mock_app_version}}
    runner = PytestSmokeTestRunner(mock_cluster_manager)
    runner.run(config, context)

    assert_cluster_connection_created(mock_kube_config_path)
    assert_app_platform_ready(mock_kube_config_path)
    assert_chart_file_uploaded(config, mock_chart_file_name)
    assert_deploy_and_wait_for_app_cr(mock_app_name, mock_app_version, mock_app_deploy_ns)
    assert_prepare_pytest_test_environment()
    assert_run_pytest(runner.test_provided, mock_kube_config_path, config.chart_file, mock_app_version)
    assert_deletes_app(configured_app_mock)


def assert_run_pytest(test_provided: StepType, kube_config_path: str, chart_file: str, app_version: str) -> None:
    cast(unittest.mock.Mock, app_test_suite.steps.pytest.pytest.run_and_log).assert_called_with(
        [
            "pipenv",
            "run",
            "pytest",
            "-m",
            test_provided,
            "--cluster-type",
            "mock",
            "--kube-config",
            kube_config_path,
            "--chart-path",
            chart_file,
            "--chart-version",
            app_version,
            "--chart-extra-info",
            "external_cluster_version=1.19.1",
            "--log-cli-level",
            "info",
            f"--junitxml=test_results_{test_provided}.xml",
        ],
        cwd="",
    )


def assert_prepare_pytest_test_environment() -> None:
    run_and_log_mock = cast(unittest.mock.Mock, app_test_suite.steps.pytest.pytest.run_and_log)
    assert run_and_log_mock.call_args_list[0].args[0] == [
        "pipenv",
        "install",
        "--deploy",
    ]
    assert run_and_log_mock.call_args_list[1].args[0] == [
        "pipenv",
        "--venv",
    ]


def patch_pytest_test_runner(mocker: MockerFixture, run_and_log_res: unittest.mock.Mock) -> None:
    mocker.patch("app_test_suite.steps.pytest.pytest.run_and_log", return_value=run_and_log_res)
