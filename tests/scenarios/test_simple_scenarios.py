import unittest.mock
from typing import Callable

import pytest
from pytest_mock import MockerFixture
from step_exec_lib.types import StepType

from app_test_suite.steps.base import CONTEXT_KEY_CHART_YAML, TestExecutor
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
from tests.scenarios.executors.pytest import patch_pytest_test_runner, assert_prepare_and_run_pytest


@pytest.mark.parametrize(
    "test_executor,patcher,asserter",
    [
        (PytestExecutor(), patch_pytest_test_runner, assert_prepare_and_run_pytest),
        # (GotestExecutor()),
    ],
    ids=[
        "pytest",
        # "gotest"
    ],
)
def test_pytest_smoke_runner_run(
    mocker: MockerFixture,
    test_executor: TestExecutor,
    patcher: Callable[[MockerFixture, unittest.mock.Mock], None],
    asserter: Callable[[StepType, str], None],
) -> None:
    mock_cluster_manager = get_mock_cluster_manager(mocker)
    run_and_log_call_result_mock = get_run_and_log_result_mock(mocker)

    configured_app_mock = patch_base_test_runner(mocker, run_and_log_call_result_mock, MOCK_APP_NAME, MOCK_APP_NS)
    patcher(mocker, run_and_log_call_result_mock)

    config = get_base_config(mocker)
    context = {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_APP_VERSION}}
    runner = SmokeTestScenario(mock_cluster_manager, test_executor)
    runner.run(config, context)

    assert_cluster_connection_created(MOCK_KUBE_CONFIG_PATH)
    assert_app_platform_ready(MOCK_KUBE_CONFIG_PATH)
    assert_chart_file_uploaded(config, MOCK_CHART_FILE_NAME)
    assert_deploy_and_wait_for_app_cr(MOCK_APP_NAME, MOCK_APP_VERSION, MOCK_APP_DEPLOY_NS, TEST_APP_CATALOG_NAME)
    asserter(runner.test_provided, config.chart_file)
    assert_base_tester_deletes_app(configured_app_mock)
