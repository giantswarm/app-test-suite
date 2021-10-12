import unittest.mock
from typing import cast

from pytest_mock import MockerFixture
from step_exec_lib.types import StepType

import app_test_suite
from app_test_suite.steps.base import CONTEXT_KEY_CHART_YAML
from app_test_suite.steps.pytest.pytest import PytestExecutor
from app_test_suite.steps.scenarios.simple import SmokeTestScenario, TEST_APP_CATALOG_NAME
from tests.helpers import (
    assert_deploy_and_wait_for_app_cr,
    assert_chart_file_uploaded,
    assert_app_platform_ready,
    assert_cluster_connection_created,
    get_base_config,
    get_run_and_log_result_mock,
    patch_base_test_runner,
    get_mock_cluster_manager,
    MOCK_APP_NAME,
    MOCK_APP_NS,
    MOCK_APP_VERSION,
    MOCK_KUBE_CONFIG_PATH,
    MOCK_CHART_FILE_NAME,
    MOCK_APP_DEPLOY_NS,
    assert_base_tester_deletes_app,
)


def test_pytest_smoke_runner_run(mocker: MockerFixture) -> None:
    mock_cluster_manager = get_mock_cluster_manager(mocker)
    run_and_log_call_result_mock = get_run_and_log_result_mock(mocker)

    configured_app_mock = patch_base_test_runner(mocker, run_and_log_call_result_mock, MOCK_APP_NAME, MOCK_APP_NS)
    patch_pytest_test_runner(mocker, run_and_log_call_result_mock)

    config = get_base_config(mocker)
    context = {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_APP_VERSION}}
    # TODO: parametrize and use go as well
    test_executor = PytestExecutor()
    runner = SmokeTestScenario(mock_cluster_manager, test_executor)
    runner.run(config, context)

    assert_cluster_connection_created(MOCK_KUBE_CONFIG_PATH)
    assert_app_platform_ready(MOCK_KUBE_CONFIG_PATH)
    assert_chart_file_uploaded(config, MOCK_CHART_FILE_NAME)
    assert_deploy_and_wait_for_app_cr(MOCK_APP_NAME, MOCK_APP_VERSION, MOCK_APP_DEPLOY_NS, TEST_APP_CATALOG_NAME)
    assert_prepare_pytest_test_environment()
    assert_run_pytest(runner.test_provided, MOCK_KUBE_CONFIG_PATH, config.chart_file, MOCK_APP_VERSION)
    assert_base_tester_deletes_app(configured_app_mock)


def assert_run_pytest(test_provided: StepType, kube_config_path: str, chart_file: str, app_version: str) -> None:
    cast(unittest.mock.Mock, app_test_suite.steps.pytest.pytest.run_and_log).assert_any_call(
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
