from typing import cast
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture
from requests import Response
from yaml.parser import ParserError

import app_test_suite
import app_test_suite.steps.scenarios.upgrade
from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.errors import ATSTestError
from app_test_suite.steps.base import CONTEXT_KEY_CHART_YAML
from app_test_suite.steps.base import TestExecutor
from app_test_suite.steps.pytest.pytest import PytestExecutor
from app_test_suite.steps.scenarios.upgrade import (
    UpgradeTestScenario,
    STABLE_APP_CATALOG_NAME,
    KEY_PRE_UPGRADE,
    KEY_POST_UPGRADE,
)
from tests.helpers import (
    get_mock_cluster_manager,
    get_run_and_log_result_mock,
    patch_base_test_runner,
    MOCK_APP_NAME,
    MOCK_APP_NS,
    patch_upgrade_test_runner,
    get_base_config,
    configure_for_upgrade_test,
    MOCK_APP_VERSION,
    assert_cluster_connection_created,
    MOCK_KUBE_CONFIG_PATH,
    assert_app_platform_ready,
    assert_chart_file_uploaded,
    MOCK_CHART_FILE_NAME,
    assert_deploy_and_wait_for_app_cr,
    MOCK_UPGRADE_APP_VERSION,
    MOCK_APP_DEPLOY_NS,
    MOCK_UPGRADE_CHART_FILE_NAME,
    assert_upgrade_tester_exec_hook,
    assert_app_updated,
    assert_upgrade_tester_deletes_app,
)
from tests.scenarios.pytest.test_simple_scenarios import (
    patch_pytest_test_runner,
    assert_prepare_pytest_test_environment,
    assert_run_pytest,
)


@pytest.mark.parametrize(
    "resp_code,resp_reason,resp_text,error_type,ver_found",
    [
        (200, "OK", "", None, "0.2.4"),
        (404, "Not found", "", ATSTestError, ""),
        (200, "OK", ": - : not a YAML", ParserError, ""),
        (200, "OK", "yaml: {}", ATSTestError, ""),
        (200, "OK", "entries: {}", ATSTestError, ""),
    ],
    ids=["response OK", "index.yaml not found", "bad YAML", "no 'entries' in YAML", "app entry not found"],
)
def test_find_latest_version(
    mocker: MockerFixture, resp_code: int, resp_reason: str, resp_text: str, error_type: type, ver_found: str
) -> None:
    mock_cluster_manager = mocker.MagicMock(spec=ClusterManager)
    test_executor = mocker.MagicMock(spec=TestExecutor, name="Mock Test Executor")
    runner = UpgradeTestScenario(mock_cluster_manager, test_executor)
    with open("tests/assets/test_index.yaml", "r") as file:
        test_index_yaml = file.read()

    requests_get_res = mocker.MagicMock(spec=Response, name="index.yaml get result")
    requests_get_res.ok = 300 > resp_code >= 200
    requests_get_res.status_code = resp_code
    requests_get_res.reason = resp_reason
    requests_get_res.text = test_index_yaml if resp_text == "" else resp_text
    mocker.patch("app_test_suite.steps.scenarios.upgrade.requests.get", return_value=requests_get_res)

    catalog_url = "http://mock.catalog"
    app_name = "hello-world-app"
    caught_error = None
    ver = ""
    try:
        ver = runner._get_latest_app_version(catalog_url, app_name)
    except Exception as e:
        caught_error = e

    if error_type:
        assert type(caught_error) == error_type
    else:
        assert ver == ver_found
    cast(Mock, app_test_suite.steps.scenarios.upgrade.requests.get).assert_called_once_with(catalog_url + "/index.yaml")


def test_upgrade_pytest_runner_run(mocker: MockerFixture) -> None:
    mock_cluster_manager = get_mock_cluster_manager(mocker)
    run_and_log_call_result_mock = get_run_and_log_result_mock(mocker)

    configured_app_mock = patch_base_test_runner(mocker, run_and_log_call_result_mock, MOCK_APP_NAME, MOCK_APP_NS)
    patch_pytest_test_runner(mocker, run_and_log_call_result_mock)
    mock_app_catalog_cr, mock_stable_app_catalog_cr = patch_upgrade_test_runner(mocker, run_and_log_call_result_mock)

    config = get_base_config(mocker)
    configure_for_upgrade_test(config)

    context = {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_APP_VERSION}}
    # TODO: parametrize and use go as well
    test_executor = PytestExecutor()
    runner = UpgradeTestScenario(mock_cluster_manager, test_executor)
    runner.run(config, context)

    assert_cluster_connection_created(MOCK_KUBE_CONFIG_PATH)
    assert_app_platform_ready(MOCK_KUBE_CONFIG_PATH)
    assert_chart_file_uploaded(config, MOCK_CHART_FILE_NAME)
    assert_deploy_and_wait_for_app_cr(
        MOCK_APP_NAME, MOCK_UPGRADE_APP_VERSION, MOCK_APP_DEPLOY_NS, STABLE_APP_CATALOG_NAME
    )
    assert_prepare_pytest_test_environment()
    mock_stable_app_catalog_cr.create.assert_any_call()
    assert_run_pytest(
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
    assert_run_pytest(runner.test_provided, MOCK_KUBE_CONFIG_PATH, MOCK_CHART_FILE_NAME, MOCK_APP_VERSION)
    assert_upgrade_tester_deletes_app(configured_app_mock)
    mock_stable_app_catalog_cr.delete.assert_called_once()
