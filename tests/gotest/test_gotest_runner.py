import os
import unittest.mock
from typing import cast

from pytest_mock import MockerFixture

import app_test_suite
from app_test_suite.steps.base_test_runner import context_key_chart_yaml, TEST_APP_CATALOG_NAME
from app_test_suite.steps.gotest.gotest import GotestSmokeTestScenario, GotestUpgradeTestScenario
from app_test_suite.steps.upgrade_test_runner import STABLE_APP_CATALOG_NAME, KEY_PRE_UPGRADE, KEY_POST_UPGRADE
from step_exec_lib.types import StepType
from tests.helpers import (
    MOCK_KUBE_VERSION,
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
    configure_for_upgrade_test,
    patch_upgrade_test_runner,
    MOCK_UPGRADE_APP_VERSION,
    MOCK_UPGRADE_CHART_FILE_NAME,
    assert_base_tester_deletes_app,
    assert_upgrade_tester_deletes_app,
    assert_app_updated,
    assert_upgrade_tester_exec_hook,
)


def test_upgrade_gotest_runner_run(mocker: MockerFixture) -> None:
    mock_cluster_manager = get_mock_cluster_manager(mocker)
    run_and_log_call_result_mock = get_run_and_log_result_mock(mocker)

    configured_app_mock = patch_base_test_runner(mocker, run_and_log_call_result_mock, MOCK_APP_NAME, MOCK_APP_NS)
    patch_gotest_test_runner(mocker, run_and_log_call_result_mock)
    mock_app_catalog_cr, mock_stable_app_catalog_cr = patch_upgrade_test_runner(mocker, run_and_log_call_result_mock)

    config = get_base_config(mocker)
    configure_for_upgrade_test(config)

    context = {context_key_chart_yaml: {"name": MOCK_APP_NAME, "version": MOCK_APP_VERSION}}
    runner = GotestUpgradeTestScenario(mock_cluster_manager)
    runner.run(config, context)

    assert_cluster_connection_created(MOCK_KUBE_CONFIG_PATH)
    assert_app_platform_ready(MOCK_KUBE_CONFIG_PATH)
    assert_chart_file_uploaded(config, MOCK_CHART_FILE_NAME)
    assert_deploy_and_wait_for_app_cr(
        MOCK_APP_NAME, MOCK_UPGRADE_APP_VERSION, MOCK_APP_DEPLOY_NS, STABLE_APP_CATALOG_NAME
    )
    mock_stable_app_catalog_cr.create.assert_any_call()
    assert_run_gotest(
        runner.test_provided, MOCK_KUBE_CONFIG_PATH, MOCK_UPGRADE_CHART_FILE_NAME, MOCK_UPGRADE_APP_VERSION
    )
    assert_upgrade_tester_exec_hook(
        KEY_PRE_UPGRADE,
        MOCK_APP_NAME,
        MOCK_UPGRADE_APP_VERSION,
        MOCK_APP_VERSION,
        MOCK_KUBE_CONFIG_PATH,
        MOCK_APP_DEPLOY_NS,
    )
    assert_app_updated(configured_app_mock)
    assert_upgrade_tester_exec_hook(
        KEY_POST_UPGRADE,
        MOCK_APP_NAME,
        MOCK_UPGRADE_APP_VERSION,
        MOCK_APP_VERSION,
        MOCK_KUBE_CONFIG_PATH,
        MOCK_APP_DEPLOY_NS,
    )
    assert_run_gotest(runner.test_provided, MOCK_KUBE_CONFIG_PATH, MOCK_CHART_FILE_NAME, MOCK_APP_VERSION)
    assert_upgrade_tester_deletes_app(configured_app_mock)
    mock_stable_app_catalog_cr.delete.assert_called_once()


def test_gotest_smoke_runner_run(mocker: MockerFixture) -> None:
    mock_cluster_manager = get_mock_cluster_manager(mocker)
    run_and_log_call_result_mock = get_run_and_log_result_mock(mocker)

    configured_app_mock = patch_base_test_runner(mocker, run_and_log_call_result_mock, MOCK_APP_NAME, MOCK_APP_NS)
    patch_gotest_test_runner(mocker, run_and_log_call_result_mock)

    config = get_base_config(mocker)
    context = {context_key_chart_yaml: {"name": MOCK_APP_NAME, "version": MOCK_APP_VERSION}}
    runner = GotestSmokeTestScenario(mock_cluster_manager)
    runner.run(config, context)

    assert_cluster_connection_created(MOCK_KUBE_CONFIG_PATH)
    assert_app_platform_ready(MOCK_KUBE_CONFIG_PATH)
    assert_chart_file_uploaded(config, MOCK_CHART_FILE_NAME)
    assert_deploy_and_wait_for_app_cr(MOCK_APP_NAME, MOCK_APP_VERSION, MOCK_APP_DEPLOY_NS, TEST_APP_CATALOG_NAME)
    assert_run_gotest(runner.test_provided, MOCK_KUBE_CONFIG_PATH, config.chart_file, MOCK_APP_VERSION)
    assert_base_tester_deletes_app(configured_app_mock)


def assert_run_gotest(test_provided: StepType, kube_config_path: str, chart_file: str, app_version: str) -> None:
    env_vars = {}
    env_vars["ATS_APP_CONFIG_FILE_PATH"] = ""
    env_vars["ATS_CHART_PATH"] = chart_file
    env_vars["ATS_CHART_VERSION"] = app_version
    env_vars["ATS_CLUSTER_TYPE"] = "mock"
    env_vars["ATS_CLUSTER_VERSION"] = MOCK_KUBE_VERSION
    env_vars["ATS_KUBE_CONFIG_PATH"] = kube_config_path
    env_vars["ATS_TEST_TYPE"] = test_provided
    env_vars["ATS_TEST_DIR"] = ""

    # Set env vars needed for Go.
    env_vars["GOPATH"] = os.getenv("GOPATH", "")
    env_vars["HOME"] = os.getenv("HOME", "")
    env_vars["PATH"] = os.getenv("PATH", "")

    cast(unittest.mock.Mock, app_test_suite.steps.gotest.gotest.run_and_handle_error).assert_any_call(
        [
            "go",
            "test",
            "-v",
            f"-tags={test_provided}",
        ],
        "build constraints exclude all Go files",
        cwd="",
        env=env_vars,
    )


def patch_gotest_test_runner(mocker: MockerFixture, run_and_handle_error_res: unittest.mock.Mock) -> None:
    mocker.patch("app_test_suite.steps.gotest.gotest.run_and_handle_error", return_value=run_and_handle_error_res)
