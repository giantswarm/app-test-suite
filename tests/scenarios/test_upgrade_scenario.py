import unittest
from enum import Enum
from typing import cast, Callable
from unittest.mock import Mock

import pytest
from pytest_helm_charts.giantswarm_app_platform.app import create_app
from pytest_helm_charts.utils import YamlDict
from pytest_mock import MockerFixture
from requests import Response
from semver import VersionInfo
from step_exec_lib.types import StepType
from yaml.parser import ParserError

import app_test_suite
import app_test_suite.steps.scenarios.upgrade
from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.errors import ATSTestError
from app_test_suite.steps.base import CONTEXT_KEY_CHART_YAML
from app_test_suite.steps.base import TestExecutor
from app_test_suite.steps.executors.gotest import GotestExecutor
from app_test_suite.steps.executors.pytest import PytestExecutor
from app_test_suite.steps.scenarios.simple import TEST_APP_CATALOG_NAME, TEST_APP_CATALOG_NAMESPACE
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
    MOCK_CHART_VERSION,
    assert_cluster_connection_created,
    MOCK_KUBE_CONFIG_PATH,
    assert_app_platform_ready,
    assert_chart_file_uploaded,
    MOCK_CHART_FILE_NAME,
    assert_deploy_and_wait_for_app_cr,
    MOCK_UPGRADE_APP_VERSION,
    MOCK_APP_DEPLOY_NS,
    MOCK_UPGRADE_CHART_FILE_URL,
    assert_upgrade_tester_exec_hook,
    assert_app_updated,
    assert_upgrade_tester_deletes_app,
    MOCK_APP_VERSION,
    patch_requests_get_chart,
    assert_upgrade_metadata_created,
    MOCK_APP_NAMESPACE,
    MOCK_STABLE_APP_CATALOG_NAMESPACE,
)
from tests.scenarios.executors.gotest import assert_run_gotest, patch_gotest_test_runner
from tests.scenarios.executors.pytest import (
    assert_run_pytest,
    assert_prepare_pytest_test_environment,
    patch_pytest_test_runner,
)


def test_version_sort() -> None:
    versions = [
        "0.7.0",
        "0.6.1",
        "0.6.0",
        "0.5.1",
        "0.5.0",
        "0.4.1",
        "0.4.0",
        "0.4.0-70e98f9c806e784ea1c54c57558bfc25736f89c8",
        "0.3.0",
        "0.3.0-ff7a16aeda6d977730d6e5f4e73962bf5d6503bd",
        "0.3.0-alpha.1",
        "0.3.0-rc1",
        "0.3.0-alpha.2",
        "0.1.0-6727f1050acf0617566d76d590b665c5b98ffc1d",
        "0.3.0-beta",
    ]
    expected = [
        "0.7.0",
        "0.6.1",
        "0.6.0",
        "0.5.1",
        "0.5.0",
        "0.4.1",
        "0.4.0",
        "0.4.0-70e98f9c806e784ea1c54c57558bfc25736f89c8",
        "0.3.0",
        "0.3.0-rc1",
        "0.3.0-ff7a16aeda6d977730d6e5f4e73962bf5d6503bd",
        "0.3.0-beta",
        "0.3.0-alpha.2",
        "0.3.0-alpha.1",
        "0.1.0-6727f1050acf0617566d76d590b665c5b98ffc1d",
    ]
    versions.sort(key=VersionInfo.parse, reverse=True)
    assert expected == versions


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
    cast(Mock, app_test_suite.steps.scenarios.upgrade.requests.get).assert_called_once_with(
        catalog_url + "/index.yaml", headers={"User-agent": "Mozilla/5.0"}, timeout=10
    )


@pytest.mark.parametrize(
    "test_executor,patcher,asserter_test,asserter_prepare",
    [
        (PytestExecutor(), patch_pytest_test_runner, assert_run_pytest, assert_prepare_pytest_test_environment),
        (GotestExecutor(), patch_gotest_test_runner, assert_run_gotest, lambda: None),
    ],
    ids=[
        "pytest",
        "gotest",
    ],
)
def test_upgrade_pytest_runner_run(
    mocker: MockerFixture,
    test_executor: TestExecutor,
    patcher: Callable[[MockerFixture, unittest.mock.Mock], None],
    asserter_test: Callable[[StepType, str, str, str, str], None],
    asserter_prepare: Callable[[], None],
) -> None:
    mock_cluster_manager = get_mock_cluster_manager(mocker)
    run_and_log_call_result_mock = get_run_and_log_result_mock(mocker)

    configured_app_mock = patch_base_test_runner(mocker, run_and_log_call_result_mock, MOCK_APP_NAME, MOCK_APP_NS)
    patcher(mocker, run_and_log_call_result_mock)
    mock_app_catalog_cr, mock_stable_app_catalog_cr = patch_upgrade_test_runner(mocker, run_and_log_call_result_mock)
    mock_requests_get_chart = patch_requests_get_chart(mocker)

    config = get_base_config(mocker)
    configure_for_upgrade_test(config)

    context = {
        CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_CHART_VERSION, "appVersion": MOCK_APP_VERSION}
    }
    runner = UpgradeTestScenario(mock_cluster_manager, test_executor)
    runner.run(config, context)

    assert_cluster_connection_created(MOCK_KUBE_CONFIG_PATH)
    assert_app_platform_ready(MOCK_KUBE_CONFIG_PATH)
    assert_chart_file_uploaded(config, MOCK_CHART_FILE_NAME)
    assert_deploy_and_wait_for_app_cr(
        MOCK_APP_NAME, MOCK_UPGRADE_APP_VERSION, MOCK_APP_DEPLOY_NS, STABLE_APP_CATALOG_NAME, MOCK_APP_DEPLOY_NS
    )
    asserter_prepare()
    mock_stable_app_catalog_cr.create.assert_any_call()
    asserter_test(
        runner.test_provided,
        MOCK_KUBE_CONFIG_PATH,
        MOCK_UPGRADE_CHART_FILE_URL,
        MOCK_UPGRADE_APP_VERSION,
        "ats_extra_upgrade_test_stage=pre_upgrade",
    )
    assert_upgrade_tester_exec_hook(
        KEY_PRE_UPGRADE,
        MOCK_APP_NAME,
        MOCK_UPGRADE_APP_VERSION,
        MOCK_CHART_VERSION,
        MOCK_KUBE_CONFIG_PATH,
        MOCK_APP_DEPLOY_NS,
    )
    assert_app_updated(configured_app_mock)
    assert_upgrade_tester_exec_hook(
        KEY_POST_UPGRADE,
        MOCK_APP_NAME,
        MOCK_UPGRADE_APP_VERSION,
        MOCK_CHART_VERSION,
        MOCK_KUBE_CONFIG_PATH,
        MOCK_APP_DEPLOY_NS,
    )
    asserter_test(
        runner.test_provided,
        MOCK_KUBE_CONFIG_PATH,
        MOCK_CHART_FILE_NAME,
        MOCK_CHART_VERSION,
        "ats_extra_upgrade_test_stage=post_upgrade",
    )
    mock_requests_get_chart.assert_called_once_with(MOCK_UPGRADE_CHART_FILE_URL, allow_redirects=True, timeout=10)
    assert_upgrade_tester_deletes_app(configured_app_mock)
    mock_stable_app_catalog_cr.delete.assert_called_once()
    assert_upgrade_metadata_created()


def test_upgrade_app_cr_no_configs(mocker: MockerFixture) -> None:
    mocker.patch("pytest_helm_charts.giantswarm_app_platform.app.AppCR.create")
    mocker.patch("pytest_helm_charts.giantswarm_app_platform.app.ConfigMap.create")
    configured_app = create_app(
        mocker.MagicMock(),
        MOCK_APP_NAME,
        MOCK_APP_VERSION,
        STABLE_APP_CATALOG_NAME,
        MOCK_STABLE_APP_CATALOG_NAMESPACE,
        MOCK_APP_NAMESPACE,
        MOCK_APP_NAMESPACE,
    )
    mocker.patch.object(configured_app.app, "reload")
    mocker.patch.object(configured_app.app, "update")

    runner = UpgradeTestScenario(mocker.MagicMock(), PytestExecutor())
    new_configured_app = runner._upgrade_app_cr(configured_app, MOCK_UPGRADE_APP_VERSION, app_config_file_path="")

    # both versions used no config, so there should be no change in object references
    assert new_configured_app == configured_app
    assert new_configured_app.app.obj["spec"]["version"] == MOCK_UPGRADE_APP_VERSION
    assert new_configured_app.app.obj["spec"]["catalog"] == TEST_APP_CATALOG_NAME
    assert new_configured_app.app.obj["spec"]["catalogNamespace"] == TEST_APP_CATALOG_NAMESPACE


class ExpectedAction(Enum):
    NO_CHANGE = 1
    CM_DELETED = 2
    CM_CREATED = 3
    CM_UPDATED = 4


@pytest.mark.parametrize(
    "stable_config,under_test_config_file,expected_action",
    [
        (None, "", ExpectedAction.NO_CHANGE),
        ({"test1": "val1"}, "", ExpectedAction.CM_DELETED),
        (None, "tests/assets/mock_config.yaml", ExpectedAction.CM_CREATED),
        ({"test1": "val1"}, "tests/assets/mock_config.yaml", ExpectedAction.NO_CHANGE),
        ({"test1": "val2"}, "tests/assets/mock_config.yaml", ExpectedAction.CM_UPDATED),
    ],
    ids=[
        "both no config",
        "only stable has config",
        "only under-test has config",
        "both use config - no change",
        "both use config - with change",
    ],
)
def test_upgrade_app_cr_stable_has_config(
    stable_config: YamlDict, under_test_config_file: str, expected_action: ExpectedAction, mocker: MockerFixture
) -> None:
    mocker.patch("pytest_helm_charts.giantswarm_app_platform.app.AppCR.create")
    mocker.patch("pytest_helm_charts.giantswarm_app_platform.app.ConfigMap.create")
    configured_app = create_app(
        mocker.MagicMock(),
        MOCK_APP_NAME,
        MOCK_APP_VERSION,
        STABLE_APP_CATALOG_NAME,
        MOCK_STABLE_APP_CATALOG_NAMESPACE,
        MOCK_APP_NAMESPACE,
        MOCK_APP_NAMESPACE,
        config_values=stable_config,
    )
    mocker.patch.object(configured_app.app, "reload")
    mocker.patch.object(configured_app.app, "update")
    if configured_app.app_cm:
        mocker.patch.object(configured_app.app_cm, "create")
        mocker.patch.object(configured_app.app_cm, "reload")
        mocker.patch.object(configured_app.app_cm, "update")
        mocker.patch.object(configured_app.app_cm, "delete")

    runner = UpgradeTestScenario(mocker.MagicMock(), PytestExecutor())
    new_configured_app = runner._upgrade_app_cr(
        configured_app, MOCK_UPGRADE_APP_VERSION, app_config_file_path=under_test_config_file
    )

    assert new_configured_app.app.obj["spec"]["version"] == MOCK_UPGRADE_APP_VERSION
    assert new_configured_app.app.obj["spec"]["catalog"] == TEST_APP_CATALOG_NAME
    assert new_configured_app.app.obj["spec"]["catalogNamespace"] == TEST_APP_CATALOG_NAMESPACE
    if expected_action == ExpectedAction.NO_CHANGE:
        assert new_configured_app == configured_app
        if new_configured_app.app_cm:
            cast(Mock, new_configured_app.app_cm.update).assert_not_called()
    elif expected_action == ExpectedAction.CM_UPDATED:
        cast(Mock, new_configured_app.app_cm.update).assert_called_once()
    elif expected_action == ExpectedAction.CM_DELETED:
        cast(Mock, configured_app.app_cm.delete).assert_called_once()
        assert new_configured_app.app_cm is None
        assert "config" not in new_configured_app.app.obj["spec"]
    elif expected_action == ExpectedAction.CM_CREATED:
        assert new_configured_app.app_cm is not None
        cast(Mock, new_configured_app.app_cm.create).assert_called_once()
        assert "config" in new_configured_app.app.obj["spec"]
        assert (
            new_configured_app.app.obj["spec"]["config"]["configMap"]["name"]
            == new_configured_app.app_cm.obj["metadata"]["name"]
        )
        assert (
            new_configured_app.app.obj["spec"]["config"]["configMap"]["namespace"]
            == new_configured_app.app_cm.obj["metadata"]["namespace"]
        )
