import subprocess
import unittest
from typing import cast, Callable
from unittest.mock import Mock

import pytest
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
from app_test_suite.steps.scenarios.upgrade import (
    UpgradeTestScenario,
    KEY_PRE_UPGRADE,
    KEY_POST_UPGRADE,
    _HELM_BIN,
    _HELM_PULL_TIMEOUT_SEC,
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
    assert_cluster_prerequisites_ready,
    assert_helm_deployed,
    assert_helm_uninstalled,
    MOCK_CHART_FILE_NAME,
    MOCK_UPGRADE_APP_VERSION,
    MOCK_UPGRADE_CATALOG_URL,
    MOCK_APP_DEPLOY_NS,
    MOCK_STABLE_APP_FILE,
    assert_upgrade_tester_exec_hook,
    MOCK_APP_VERSION,
    assert_upgrade_metadata_created,
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
    ids=[
        "response OK",
        "index.yaml not found",
        "bad YAML",
        "no 'entries' in YAML",
        "app entry not found",
    ],
)
def test_find_latest_version(
    mocker: MockerFixture,
    resp_code: int,
    resp_reason: str,
    resp_text: str,
    error_type: type,
    ver_found: str,
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
    mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.requests.get",
        return_value=requests_get_res,
    )

    catalog_url = "http://mock.catalog"
    app_name = "hello-world-app"
    caught_error = None
    ver = ""
    try:
        ver = runner._get_latest_stable_version(catalog_url, app_name)
    except Exception as e:
        caught_error = e

    if error_type:
        assert type(caught_error) is error_type
    else:
        assert ver == ver_found
    cast(Mock, app_test_suite.steps.scenarios.upgrade.requests.get).assert_called_once_with(
        catalog_url + "/index.yaml", headers={"User-agent": "Mozilla/5.0"}, timeout=10
    )


@pytest.mark.parametrize(
    "test_executor,patcher,asserter_test,asserter_prepare",
    [
        (
            PytestExecutor(),
            patch_pytest_test_runner,
            assert_run_pytest,
            assert_prepare_pytest_test_environment,
        ),
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

    patch_base_test_runner(mocker, run_and_log_call_result_mock, MOCK_APP_NAME, MOCK_APP_NS)
    patcher(mocker, run_and_log_call_result_mock)
    patch_upgrade_test_runner(mocker, run_and_log_call_result_mock)

    config = get_base_config(mocker)
    configure_for_upgrade_test(config)

    context = {
        CONTEXT_KEY_CHART_YAML: {
            "name": MOCK_APP_NAME,
            "version": MOCK_CHART_VERSION,
            "appVersion": MOCK_APP_VERSION,
        }
    }
    runner = UpgradeTestScenario(mock_cluster_manager, test_executor)
    runner._stable_from_local_file = True
    runner.run(config, context)

    assert_cluster_connection_created(MOCK_KUBE_CONFIG_PATH)
    assert_cluster_prerequisites_ready(MOCK_KUBE_CONFIG_PATH)
    # stable version installed via helm
    assert_helm_deployed(MOCK_APP_NAME, MOCK_STABLE_APP_FILE, MOCK_APP_DEPLOY_NS, MOCK_KUBE_CONFIG_PATH)
    asserter_prepare()
    asserter_test(
        runner.test_provided,
        MOCK_KUBE_CONFIG_PATH,
        MOCK_STABLE_APP_FILE,
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
    # under-test version installed via helm upgrade
    assert_helm_deployed(MOCK_APP_NAME, MOCK_CHART_FILE_NAME, MOCK_APP_DEPLOY_NS, MOCK_KUBE_CONFIG_PATH)
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
    assert_helm_uninstalled(MOCK_APP_NAME, MOCK_APP_DEPLOY_NS, MOCK_KUBE_CONFIG_PATH)
    assert_upgrade_metadata_created()


def _make_remote_upgrade_runner(mocker: MockerFixture) -> UpgradeTestScenario:
    runner = UpgradeTestScenario(get_mock_cluster_manager(mocker), PytestExecutor())
    cluster_info = mocker.MagicMock(name="ClusterInfo")
    cluster_info.kube_config_path = MOCK_KUBE_CONFIG_PATH
    runner._cluster_info = cluster_info
    runner._stable_from_local_file = False
    return runner


def _remote_upgrade_config(mocker: MockerFixture) -> Mock:
    config = mocker.Mock(name="ConfigMock")
    config.upgrade_tests_app_catalog_url = MOCK_UPGRADE_CATALOG_URL
    config.upgrade_tests_app_version = MOCK_UPGRADE_APP_VERSION
    return config


def test_resolve_stable_chart_remote_pulls_with_helm(mocker: MockerFixture) -> None:
    mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.run_and_log",
        return_value=get_run_and_log_result_mock(mocker),
    )
    mocker.patch("app_test_suite.steps.scenarios.upgrade.TestInfoProvider")
    runner = _make_remote_upgrade_runner(mocker)

    chart_file, chart_ver = runner._resolve_stable_chart(
        _remote_upgrade_config(mocker), {}, MOCK_APP_NAME, "/tmp/ats-dl"
    )

    assert chart_ver == MOCK_UPGRADE_APP_VERSION
    assert chart_file == f"/tmp/ats-dl/{MOCK_APP_NAME}-{MOCK_UPGRADE_APP_VERSION}.tgz"
    run_and_log = cast(Mock, app_test_suite.steps.scenarios.upgrade.run_and_log)
    run_and_log.assert_called_once()
    assert run_and_log.call_args.args[0] == [
        _HELM_BIN,
        "pull",
        MOCK_APP_NAME,
        "--repo",
        MOCK_UPGRADE_CATALOG_URL,
        "--version",
        MOCK_UPGRADE_APP_VERSION,
        "--destination",
        "/tmp/ats-dl",
    ]
    assert run_and_log.call_args.kwargs["timeout"] == _HELM_PULL_TIMEOUT_SEC


def test_resolve_stable_chart_remote_pull_timeout(mocker: MockerFixture) -> None:
    mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.run_and_log",
        side_effect=subprocess.TimeoutExpired(cmd="helm pull", timeout=_HELM_PULL_TIMEOUT_SEC),
    )
    mocker.patch("app_test_suite.steps.scenarios.upgrade.TestInfoProvider")
    runner = _make_remote_upgrade_runner(mocker)

    with pytest.raises(ATSTestError, match="timed out"):
        runner._resolve_stable_chart(_remote_upgrade_config(mocker), {}, MOCK_APP_NAME, "/tmp/ats-dl")


def test_resolve_stable_chart_remote_pull_fails(mocker: MockerFixture) -> None:
    failed = mocker.Mock(name="FailedPull")
    failed.returncode = 1
    mocker.patch("app_test_suite.steps.scenarios.upgrade.run_and_log", return_value=failed)
    mocker.patch("app_test_suite.steps.scenarios.upgrade.TestInfoProvider")
    runner = _make_remote_upgrade_runner(mocker)

    with pytest.raises(ATSTestError, match="failed"):
        runner._resolve_stable_chart(_remote_upgrade_config(mocker), {}, MOCK_APP_NAME, "/tmp/ats-dl")


MOCK_OCI_CATALOG_URL = "oci://giantswarmpublic.azurecr.io/giantswarm-catalog"


def _oci_upgrade_config(mocker: MockerFixture) -> Mock:
    config = mocker.Mock(name="OciConfigMock")
    config.upgrade_tests_app_catalog_url = MOCK_OCI_CATALOG_URL
    config.upgrade_tests_app_version = MOCK_UPGRADE_APP_VERSION
    return config


def _oci_upgrade_config_stable(mocker: MockerFixture) -> Mock:
    config = mocker.Mock(name="OciConfigMockStable")
    config.upgrade_tests_app_catalog_url = MOCK_OCI_CATALOG_URL
    config.upgrade_tests_app_version = "stable"
    return config


def _http_upgrade_config_stable(mocker: MockerFixture) -> Mock:
    config = mocker.Mock(name="HttpConfigMockStable")
    config.upgrade_tests_app_catalog_url = MOCK_UPGRADE_CATALOG_URL
    config.upgrade_tests_app_version = "stable"
    return config


def test_resolve_stable_chart_oci_pulls_with_helm(mocker: MockerFixture) -> None:
    mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.run_and_log",
        return_value=get_run_and_log_result_mock(mocker),
    )
    mocker.patch("app_test_suite.steps.scenarios.upgrade.TestInfoProvider")
    runner = _make_remote_upgrade_runner(mocker)

    chart_file, chart_ver = runner._resolve_stable_chart(_oci_upgrade_config(mocker), {}, MOCK_APP_NAME, "/tmp/ats-dl")

    assert chart_ver == MOCK_UPGRADE_APP_VERSION
    assert chart_file == f"/tmp/ats-dl/{MOCK_APP_NAME}-{MOCK_UPGRADE_APP_VERSION}.tgz"
    run_and_log_mock = cast(Mock, app_test_suite.steps.scenarios.upgrade.run_and_log)
    run_and_log_mock.assert_called_once()
    assert run_and_log_mock.call_args.args[0] == [
        _HELM_BIN,
        "pull",
        f"{MOCK_OCI_CATALOG_URL}/{MOCK_APP_NAME}",
        "--version",
        MOCK_UPGRADE_APP_VERSION,
        "--destination",
        "/tmp/ats-dl",
    ]
    assert run_and_log_mock.call_args.kwargs["timeout"] == _HELM_PULL_TIMEOUT_SEC


def _mock_tags_response(mocker: MockerFixture, status_code: int, tags: list) -> Mock:
    response = mocker.MagicMock(spec=Response, name="tags response")
    response.status_code = status_code
    response.ok = 300 > status_code >= 200
    response.reason = "OK" if response.ok else "Unauthorized"
    response.headers = {}
    response.links = {}
    response.json.return_value = {"name": "repo", "tags": tags}
    return response


def test_resolve_stable_chart_oci_stable_discovers_and_pulls(mocker: MockerFixture) -> None:
    mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.run_and_log",
        return_value=get_run_and_log_result_mock(mocker),
    )
    mocker.patch("app_test_suite.steps.scenarios.upgrade.TestInfoProvider")
    mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.requests.get",
        return_value=_mock_tags_response(mocker, 200, ["0.1.0", "0.3.0-rc1", "0.2.0", "not-semver"]),
    )
    runner = _make_remote_upgrade_runner(mocker)

    chart_file, chart_ver = runner._resolve_stable_chart(
        _oci_upgrade_config_stable(mocker), {}, MOCK_APP_NAME, "/tmp/ats-dl"
    )

    assert chart_ver == "0.2.0"
    assert chart_file == f"/tmp/ats-dl/{MOCK_APP_NAME}-0.2.0.tgz"
    run_and_log_mock = cast(Mock, app_test_suite.steps.scenarios.upgrade.run_and_log)
    assert run_and_log_mock.call_args.args[0] == [
        _HELM_BIN,
        "pull",
        f"{MOCK_OCI_CATALOG_URL}/{MOCK_APP_NAME}",
        "--version",
        "0.2.0",
        "--destination",
        "/tmp/ats-dl",
    ]


def test_resolve_stable_chart_http_stable_discovers_and_pulls(mocker: MockerFixture) -> None:
    mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.run_and_log",
        return_value=get_run_and_log_result_mock(mocker),
    )
    mocker.patch("app_test_suite.steps.scenarios.upgrade.TestInfoProvider")
    mocker.patch.object(UpgradeTestScenario, "_get_latest_stable_version", return_value="0.2.4")
    runner = _make_remote_upgrade_runner(mocker)

    chart_file, chart_ver = runner._resolve_stable_chart(
        _http_upgrade_config_stable(mocker), {}, MOCK_APP_NAME, "/tmp/ats-dl"
    )

    assert chart_ver == "0.2.4"
    assert chart_file == f"/tmp/ats-dl/{MOCK_APP_NAME}-0.2.4.tgz"
    cast(Mock, UpgradeTestScenario._get_latest_stable_version).assert_called_once_with(
        MOCK_UPGRADE_CATALOG_URL, MOCK_APP_NAME
    )


def test_get_latest_stable_oci_version_skips_prereleases_and_unparseable(mocker: MockerFixture) -> None:
    mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.requests.get",
        return_value=_mock_tags_response(mocker, 200, ["1.0.0", "1.2.0-rc.1", "1.1.0", "latest"]),
    )
    runner = _make_remote_upgrade_runner(mocker)

    assert runner._get_latest_stable_oci_version(MOCK_OCI_CATALOG_URL, MOCK_APP_NAME) == "1.1.0"
    cast(Mock, app_test_suite.steps.scenarios.upgrade.requests.get).assert_called_once_with(
        f"https://giantswarmpublic.azurecr.io/v2/giantswarm-catalog/{MOCK_APP_NAME}/tags/list",
        headers={},
        timeout=10,
    )


def test_get_latest_stable_oci_version_no_stable_raises(mocker: MockerFixture) -> None:
    mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.requests.get",
        return_value=_mock_tags_response(mocker, 200, ["1.0.0-rc.1", "not-semver"]),
    )
    runner = _make_remote_upgrade_runner(mocker)

    with pytest.raises(ATSTestError, match="No stable version"):
        runner._get_latest_stable_oci_version(MOCK_OCI_CATALOG_URL, MOCK_APP_NAME)


def test_get_latest_stable_oci_version_handles_token_auth(mocker: MockerFixture) -> None:
    challenge = _mock_tags_response(mocker, 401, [])
    challenge.headers = {
        "WWW-Authenticate": 'Bearer realm="https://auth.example.com/token",'
        'service="registry.example.com",scope="repository:giantswarm-catalog/app:pull"'
    }
    token_response = mocker.MagicMock(spec=Response, name="token response")
    token_response.ok = True
    token_response.json.return_value = {"access_token": "secret-token"}
    tags_response = _mock_tags_response(mocker, 200, ["2.0.0", "1.0.0"])

    get_mock = mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.requests.get",
        side_effect=[challenge, token_response, tags_response],
    )
    runner = _make_remote_upgrade_runner(mocker)

    assert runner._get_latest_stable_oci_version(MOCK_OCI_CATALOG_URL, MOCK_APP_NAME) == "2.0.0"
    assert get_mock.call_count == 3
    # token is fetched from the advertised realm
    assert get_mock.call_args_list[1].args[0] == "https://auth.example.com/token"
    # authenticated retry carries the bearer token
    assert get_mock.call_args_list[2].kwargs["headers"] == {"Authorization": "Bearer secret-token"}


def test_get_latest_stable_oci_version_follows_link_pagination(mocker: MockerFixture) -> None:
    base = f"https://giantswarmpublic.azurecr.io/v2/giantswarm-catalog/{MOCK_APP_NAME}/tags/list"
    page1 = _mock_tags_response(mocker, 200, ["1.0.0", "1.1.0"])
    page1.links = {"next": {"url": f"/v2/giantswarm-catalog/{MOCK_APP_NAME}/tags/list?last=1.1.0&n=2"}}
    # the newest stable tag lives only on the second page
    page2 = _mock_tags_response(mocker, 200, ["1.2.0", "2.0.0-rc.1"])

    get_mock = mocker.patch(
        "app_test_suite.steps.scenarios.upgrade.requests.get",
        side_effect=[page1, page2],
    )
    runner = _make_remote_upgrade_runner(mocker)

    assert runner._get_latest_stable_oci_version(MOCK_OCI_CATALOG_URL, MOCK_APP_NAME) == "1.2.0"
    assert get_mock.call_count == 2
    assert get_mock.call_args_list[0].args[0] == base
    # the relative rel="next" link is resolved against the current page URL
    assert get_mock.call_args_list[1].args[0] == f"{base}?last=1.1.0&n=2"
