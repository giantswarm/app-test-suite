import os
import shutil
import unittest
import unittest.mock
from types import ModuleType
from typing import cast, Tuple, Any

import pykube
import yaml
from configargparse import Namespace
from pytest_helm_charts.giantswarm_app_platform.entities import ConfiguredApp
from pytest_mock import MockerFixture
from requests import Response

import app_test_suite
from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.cluster_providers import ExternalClusterProvider
from app_test_suite.cluster_providers.cluster_provider import ClusterInfo, ClusterType
from app_test_suite.steps.scenarios.simple import SimpleTestScenario
from app_test_suite.steps.scenarios.upgrade import STABLE_APP_CATALOG_NAME

MOCK_UPGRADE_CATALOG_URL = "http://chartmuseum-chartmuseum.giantswarm:8080/charts/"
MOCK_KUBE_CONFIG_PATH = "/nonexisting-flsdhge235/kube.config"
MOCK_KUBE_VERSION = "1.19.1"
MOCK_APP_NAME = "mock_app"
MOCK_APP_NS = "mock_ns"
MOCK_APP_DEPLOY_NS = "mock_deploy_ns"
MOCK_APP_VERSION = "0.1.2"
MOCK_CHART_VERSION = "0.2.5"
MOCK_CHART_FILE_NAME = f"{MOCK_APP_NAME}-{MOCK_CHART_VERSION}.tgz"
MOCK_UPGRADE_UPGRADE_HOOK = "mock.sh"
MOCK_UPGRADE_APP_CONFIG_FILE = ""
MOCK_UPGRADE_APP_VERSION = "0.2.4-1"
MOCK_UPGRADE_CHART_FILE_URL = f"{MOCK_UPGRADE_CATALOG_URL}/{MOCK_APP_NAME}-{MOCK_UPGRADE_APP_VERSION}.tgz"
UPGRADE_META_FILE_NAME = f"tested-upgrade-{MOCK_CHART_VERSION}.yaml"


def assert_runner_deletes_app(runner: ModuleType, configured_app_mock: ConfiguredApp) -> None:
    cast(unittest.mock.Mock, runner.delete_app).assert_called_once_with(configured_app_mock)  # type: ignore
    # noinspection PyProtectedMember
    cast(unittest.mock.Mock, runner.wait_for_app_to_be_deleted).assert_called_once_with(  # type: ignore
        unittest.mock.ANY,
        configured_app_mock.app.name,
        configured_app_mock.app.namespace,
        SimpleTestScenario._APP_DELETION_TIMEOUT_SEC,
    )


def assert_base_tester_deletes_app(configured_app_mock: ConfiguredApp) -> None:
    assert_runner_deletes_app(app_test_suite.steps.scenarios.simple, configured_app_mock)


def assert_upgrade_tester_deletes_app(configured_app_mock: ConfiguredApp) -> None:
    assert_runner_deletes_app(app_test_suite.steps.scenarios.upgrade, configured_app_mock)


def assert_deploy_and_wait_for_app_cr(
    app_name: str, app_version: str, app_deploy_ns: str, catalog_name: str, catalog_namespace: str
) -> None:
    cast(unittest.mock.Mock, app_test_suite.steps.scenarios.simple.create_app).assert_called_once_with(
        unittest.mock.ANY, app_name, app_version, catalog_name, catalog_namespace, "default", app_deploy_ns, None
    )
    # noinspection PyProtectedMember
    cast(unittest.mock.Mock, app_test_suite.steps.scenarios.simple.wait_for_apps_to_run).assert_called_once_with(
        unittest.mock.ANY, [app_name], "default", SimpleTestScenario._APP_DEPLOYMENT_TIMEOUT_SEC
    )


def assert_chart_file_uploaded(config: Namespace, chart_file_name: str) -> None:
    cast(
        unittest.mock.Mock, app_test_suite.steps.scenarios.simple.ChartMuseumAppRepository.upload_artifact
    ).assert_called_once_with(config, chart_file_name)


def assert_app_platform_ready(kube_config_path: str) -> None:
    cast(unittest.mock.Mock, app_test_suite.steps.scenarios.simple.run_and_log).assert_called_with(
        ["apptestctl", "bootstrap", f"--kubeconfig-path={kube_config_path}", "--wait"]
    )


def assert_cluster_connection_created(kube_config_path: str) -> None:
    cast(unittest.mock.Mock, pykube.KubeConfig.from_file).assert_called_once_with(kube_config_path)
    cast(unittest.mock.Mock, app_test_suite.steps.scenarios.simple.HTTPClient).called_once()


def get_base_config(mocker: MockerFixture) -> Namespace:
    config = mocker.Mock(name="ConfigMock")
    config.app_tests_skip_app_deploy = False
    config.app_tests_deploy_namespace = MOCK_APP_DEPLOY_NS
    config.app_tests_app_config_file = ""
    config.chart_file = MOCK_CHART_FILE_NAME
    return config


def get_run_and_log_result_mock(mocker: MockerFixture) -> unittest.mock.Mock:
    system_call_result_mock = mocker.Mock(name="SysCallResult")
    type(system_call_result_mock).returncode = mocker.PropertyMock(return_value=0)
    return system_call_result_mock


def patch_base_test_runner(
    mocker: MockerFixture, run_and_log_res: unittest.mock.Mock, app_name: str, app_namespace: str
) -> ConfiguredApp:
    mocker.patch("pykube.KubeConfig.from_file", name="MockKubeConfig")
    mocker.patch("app_test_suite.steps.scenarios.simple.HTTPClient")
    mocker.patch("app_test_suite.steps.scenarios.simple.run_and_log", return_value=run_and_log_res)
    mocker.patch("app_test_suite.steps.scenarios.simple.ChartMuseumAppRepository.upload_artifact")
    app_cr = mocker.MagicMock(name="appCR")
    app_cr.name = app_name
    app_cr.namespace = app_namespace
    configured_app_mock = ConfiguredApp(app_cr, mocker.MagicMock(name="appCM"))
    mocker.patch("app_test_suite.steps.scenarios.simple.create_app", return_value=configured_app_mock)
    mocker.patch("app_test_suite.steps.scenarios.simple.wait_for_apps_to_run")
    mocker.patch("app_test_suite.steps.scenarios.simple.delete_app")
    mocker.patch("app_test_suite.steps.scenarios.simple.wait_for_app_to_be_deleted")
    return configured_app_mock


def get_mock_cluster_manager(mocker: MockerFixture) -> ClusterManager:
    mock_cluster_manager = mocker.MagicMock(spec=ClusterManager, name="MockClusterManager")
    mock_cluster_manager.get_cluster_for_test_type.return_value = ClusterInfo(
        ClusterType("mock"),
        None,
        MOCK_KUBE_VERSION,
        "mock_cluster_id",
        MOCK_KUBE_CONFIG_PATH,
        ExternalClusterProvider(),
        "",
    )
    return mock_cluster_manager


def configure_for_upgrade_test(config: Namespace) -> None:
    config.upgrade_tests_app_catalog_url = MOCK_UPGRADE_CATALOG_URL
    config.upgrade_tests_app_version = MOCK_UPGRADE_APP_VERSION
    config.upgrade_tests_app_config_file = MOCK_UPGRADE_APP_CONFIG_FILE
    config.upgrade_tests_upgrade_hook = MOCK_UPGRADE_UPGRADE_HOOK
    config.upgrade_tests_save_metadata = True
    # normally, `pre_run` method does this in this case to stop the default logic from
    # deploying the current chart before the stable chart can be deployed
    # since we're not calling pre_run() here, we need override in config
    config.app_tests_skip_app_deploy = True


def patch_upgrade_test_runner(
    mocker: MockerFixture, run_and_log_call_result_mock: unittest.mock.Mock
) -> Tuple[unittest.mock.Mock, unittest.mock.Mock]:
    mock_stable_app_catalog_cr = mocker.MagicMock(name="stable CatalogCR Mock")
    mocker.patch("app_test_suite.steps.scenarios.upgrade.get_catalog_obj", return_value=mock_stable_app_catalog_cr)
    mocker.patch("app_test_suite.steps.scenarios.upgrade.run_and_log", return_value=run_and_log_call_result_mock)

    def get_or_none(*_: Any, **kwargs: str) -> None:
        res = mock_stable_app_catalog_cr if kwargs["name"] == STABLE_APP_CATALOG_NAME else mock_app_catalog_cr
        return res

    mock_app_catalog_cr = mocker.MagicMock(name="CatalogCR mock")
    app_catalog_cr_objects_res = mocker.MagicMock(name="CatalogCR.objects() result")
    filter_result = mocker.MagicMock(name="CatalogCR.objects().filter() result")
    filter_result.get_or_none.side_effect = get_or_none
    app_catalog_cr_objects_res.filter.return_value = filter_result
    mocker.patch("app_test_suite.steps.scenarios.upgrade.CatalogCR.objects", return_value=app_catalog_cr_objects_res)
    mocker.patch("app_test_suite.steps.scenarios.upgrade.delete_app")
    mocker.patch("app_test_suite.steps.scenarios.upgrade.wait_for_app_to_be_deleted")
    return mock_app_catalog_cr, mock_stable_app_catalog_cr


def assert_app_updated(configured_app_mock: ConfiguredApp) -> None:
    cast(unittest.mock.Mock, configured_app_mock.app.reload).assert_called_once()
    cast(unittest.mock.Mock, configured_app_mock.app.update).assert_called_once()


def assert_upgrade_tester_exec_hook(
    stage_name: str, app_name: str, from_version: str, to_version: str, kube_config_path: str, deploy_namespace: str
) -> None:
    cast(unittest.mock.Mock, app_test_suite.steps.scenarios.upgrade.run_and_log).assert_any_call(
        [MOCK_UPGRADE_UPGRADE_HOOK, stage_name, app_name, from_version, to_version, kube_config_path, deploy_namespace],
    )


def patch_requests_get_chart(mocker: MockerFixture) -> unittest.mock.Mock:
    requests_get_res = mocker.MagicMock(spec=Response, name="chart get result")
    requests_get_res.ok = True
    requests_get_res.status_code = 200
    with open("examples/apps/hello-world-app/hello-world-app-0.2.4-1.tgz", "rb") as f:
        chart_content = f.read()
    requests_get_res.content = chart_content
    mocker.patch("app_test_suite.steps.scenarios.upgrade.requests.get", return_value=requests_get_res)
    return cast(unittest.mock.Mock, app_test_suite.steps.scenarios.upgrade.requests.get)


def assert_upgrade_metadata_created() -> None:
    meta_dir = f"{MOCK_APP_NAME}-{MOCK_UPGRADE_APP_VERSION}.tgz-meta"
    with open(os.path.join(meta_dir, UPGRADE_META_FILE_NAME)) as f:
        actual = yaml.safe_load(f.read())
        actual.pop("timestamp", None)
    with open(os.path.join("tests", "assets", UPGRADE_META_FILE_NAME), "r") as f:
        expected = yaml.safe_load(f.read())
        expected.pop("timestamp", None)
    assert actual == expected
    shutil.rmtree(meta_dir)
