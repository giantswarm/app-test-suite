import argparse
import datetime
import logging
import os
import re
import shutil
from distutils.version import LooseVersion
from tempfile import TemporaryDirectory
from typing import Tuple, cast, Match, Optional

import requests
import yaml
from pykube import ConfigMap
from pytest_helm_charts.giantswarm_app_platform.catalog import get_catalog_obj
from pytest_helm_charts.giantswarm_app_platform.custom_resources import CatalogCR
from pytest_helm_charts.giantswarm_app_platform.entities import ConfiguredApp
from pytest_helm_charts.giantswarm_app_platform.utils import delete_app, wait_for_app_to_be_deleted
from requests import RequestException
from step_exec_lib.errors import ConfigError
from step_exec_lib.types import StepType, Context
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option
from step_exec_lib.utils.processes import run_and_log
from validators import url as validator_url
from yaml import YAMLError
from yaml.parser import ParserError

from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.cluster_providers.cluster_provider import ClusterInfo
from app_test_suite.config import (
    KEY_CFG_STABLE_APP_URL,
    KEY_CFG_STABLE_APP_FILE,
    KEY_CFG_STABLE_APP_VERSION,
    KEY_CFG_STABLE_APP_CONFIG,
    KEY_CFG_UPGRADE_HOOK,
    KEY_CFG_UPGRADE_SAVE_METADATA,
)
from app_test_suite.errors import ATSTestError
from app_test_suite.steps.base import (
    TestExecutor,
    CONTEXT_KEY_CHART_YAML,
    BaseTestScenariosFilteringPipeline,
    TestExecInfo,
    TestInfoProvider,
    CONTEXT_KEY_STABLE_CHART_YAML,
)
from app_test_suite.steps.scenarios.simple import SimpleTestScenario, TEST_APP_CATALOG_NAME, TEST_APP_CATALOG_NAMESPACE
from app_test_suite.steps.test_types import STEP_TEST_UPGRADE

KEY_PRE_UPGRADE = "pre-upgrade"
KEY_POST_UPGRADE = "post-upgrade"
STABLE_APP_CATALOG_NAME = "stable"

logger = logging.getLogger(__name__)


class UpgradeTestScenario(SimpleTestScenario):
    """
    Base class to implement upgrade test scenario for any test executor.

    Do a mixin of this class and a test executor mixin derived from TestExecutor class to get a test scenario.
    """

    def __init__(self, cluster_manager: ClusterManager, test_executor: TestExecutor):
        super().__init__(cluster_manager, test_executor)
        self._skip_app_deploy = True
        self._stable_from_local_file = False
        self._semver_regex_match = re.compile(r"^.+((0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*).*)\.tgz$")

    @property
    def test_provided(self) -> StepType:
        return STEP_TEST_UPGRADE

    def pre_run(self, config: argparse.Namespace) -> None:
        super().pre_run(config)

        catalog_url = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_URL)
        stable_chart_file = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_FILE)
        if catalog_url:
            url_validation_res = validator_url(catalog_url)
            # FIXME: doesn't correctly validate 'http://chartmuseum-chartmuseum:8080/charts/' - needs at least 1 dot in
            #  the domain name
            if url_validation_res is not True:
                raise ConfigError(KEY_CFG_STABLE_APP_URL, f"Wrong catalog URL: '{url_validation_res.args[1]['value']}'")

            app_ver = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_VERSION)
            if not app_ver:
                raise ConfigError(KEY_CFG_STABLE_APP_VERSION, "Version of app to upgrade from can't be empty")
        elif stable_chart_file:
            if not os.path.isfile(stable_chart_file):
                raise ConfigError(
                    KEY_CFG_STABLE_APP_FILE,
                    f"Upgrade test from a stable chart in file '{stable_chart_file}' was requested, but "
                    "the file doesn't exist.",
                )
            self._stable_from_local_file = True
        else:
            raise ConfigError(
                f"{KEY_CFG_STABLE_APP_URL},{KEY_CFG_STABLE_APP_FILE}",
                "Exactly one of these options must be configured.",
            )

        app_cfg_file = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_CONFIG)
        if app_cfg_file and not os.path.isfile(app_cfg_file):
            raise ConfigError(
                KEY_CFG_STABLE_APP_CONFIG,
                f"Config file for the app to upgrade from was given, but not found. File name: '{app_cfg_file}'.",
            )

        upgrade_hook_exe: str = get_config_value_by_cmd_line_option(config, KEY_CFG_UPGRADE_HOOK)
        if upgrade_hook_exe:
            cmd = upgrade_hook_exe.split(" ")[0]
            if not shutil.which(cmd):
                raise ConfigError(
                    KEY_CFG_UPGRADE_HOOK,
                    f"Upgrade hook was configured, but '{cmd}' was not " f"found to be a valid executable.",
                )
        self._test_executor.validate(config, self.name)

    def _prepare_stable_app(
        self, config: argparse.Namespace, context: Context, app_name: str, deploy_namespace: str
    ) -> Tuple[str, str, str, str, str]:
        if self._stable_from_local_file:
            # upload file to existing catalog
            stable_chart_file_path = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_FILE)
            self._upload_chart_to_app_catalog(config, stable_chart_file_path)
            app_catalog_cr = CatalogCR.objects(self._kube_client).get_by_name(TEST_APP_CATALOG_NAME)
            stable_ver_match = self._semver_regex_match.fullmatch(stable_chart_file_path)
            stable_app_version = cast(Match, stable_ver_match).group(1)
            TestInfoProvider().extract_chart_info(stable_chart_file_path, CONTEXT_KEY_STABLE_CHART_YAML, context)
            catalog_url = app_catalog_cr.obj["spec"]["storage"]["URL"]
            chart_url = f"{catalog_url}/{app_name}-{stable_app_version}.tgz"
            return stable_app_version, TEST_APP_CATALOG_NAME, TEST_APP_CATALOG_NAMESPACE, catalog_url, chart_url

        catalog_url = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_URL)
        logger.info(f"Adding new app catalog named '{STABLE_APP_CATALOG_NAME}' with URL '{catalog_url}'.")
        catalog_cr = get_catalog_obj(STABLE_APP_CATALOG_NAME, deploy_namespace, catalog_url, self._kube_client)
        logger.debug(f"Creating Catalog '{catalog_cr.name}' with the stable app version.")
        catalog_cr.create()

        stable_chart_ver = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_VERSION)
        if stable_chart_ver == "latest":
            stable_chart_ver = self._get_latest_app_version(catalog_url, app_name)

        chart_url = f"{catalog_url}/{app_name}-{stable_chart_ver}.tgz"
        with TemporaryDirectory("-ats-download") as d:
            try:
                r = requests.get(chart_url, allow_redirects=True)
                if not r.ok:
                    raise ATSTestError(
                        f"Error 'HTTP-{r.status_code}' when fetching remote chart '{chart_url}': {r.reason}"
                    )
            except RequestException as e:
                logger.error(f"Error when trying to fetch remote chart '{chart_url}': '{e}'.")
                raise
            chart_file_name = os.path.join(d, "chart.tgz")
            with open(chart_file_name, "wb") as f:
                f.write(r.content)
            TestInfoProvider().extract_chart_info(chart_file_name, CONTEXT_KEY_STABLE_CHART_YAML, context)
        return stable_chart_ver, STABLE_APP_CATALOG_NAME, deploy_namespace, catalog_url, chart_url

    def run_tests(self, config: argparse.Namespace, context: Context) -> None:
        app_name = context[CONTEXT_KEY_CHART_YAML]["name"]
        chart_version = context[CONTEXT_KEY_CHART_YAML]["version"]

        deploy_namespace = get_config_value_by_cmd_line_option(
            config, BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_NAMESPACE
        )
        app_cfg_file = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_CONFIG)

        (
            stable_chart_ver,
            stable_app_catalog_name,
            stable_app_catalog_namespace,
            stable_app_catalog_url,
            stable_chart_url,
        ) = self._prepare_stable_app(config, context, app_name, deploy_namespace)

        # deploy the stable version
        stable_app = self._deploy_chart(
            app_name,
            stable_chart_ver,
            deploy_namespace,
            app_cfg_file,
            stable_app_catalog_name,
            stable_app_catalog_namespace,
        )

        # run tests
        exec_info = self._get_test_exec_info(stable_chart_url, stable_chart_ver, app_cfg_file)
        self._test_executor.prepare_test_environment(exec_info)
        self._test_executor.execute_test(exec_info)

        # run the optional upgrade hook
        self._run_upgrade_hook(config, KEY_PRE_UPGRADE, app_name, stable_chart_ver, chart_version)

        # reconfigure App CR to point to the new version UT
        app_config_file_path = get_config_value_by_cmd_line_option(
            config, BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_CONFIG_FILE
        )
        self._upgrade_app_cr(stable_app, chart_version, app_config_file_path)

        # run the optional upgrade hook
        self._run_upgrade_hook(config, KEY_POST_UPGRADE, app_name, stable_chart_ver, chart_version)

        # run tests again
        exec_info.chart_path = config.chart_file
        exec_info.chart_ver = chart_version
        exec_info.app_config_file_path = app_config_file_path
        self._test_executor.execute_test(exec_info)

        # delete App CR
        logger.info(f"Deleting App CR '{stable_app.app.name}'.")
        delete_app(stable_app)
        wait_for_app_to_be_deleted(
            self._kube_client, stable_app.app.name, stable_app.app.namespace, self._APP_DELETION_TIMEOUT_SEC
        )

        # delete Catalog CR, if it was created
        catalog_cr = (
            CatalogCR.objects(self._kube_client)
            .filter(namespace=deploy_namespace)
            .get_or_none(name=STABLE_APP_CATALOG_NAME)
        )
        if catalog_cr:
            logger.debug(f"Deleting Catalog '{catalog_cr.name}'.")
            catalog_cr.delete()

        # save metadata, if requested
        if get_config_value_by_cmd_line_option(config, KEY_CFG_UPGRADE_SAVE_METADATA):
            self._save_metadata(
                app_name,
                chart_version,
                context[CONTEXT_KEY_CHART_YAML]["appVersion"],
                context[CONTEXT_KEY_STABLE_CHART_YAML]["version"],
                context[CONTEXT_KEY_STABLE_CHART_YAML]["appVersion"],
                exec_info.cluster_type,
                exec_info.cluster_version,
            )

    def _upgrade_app_cr(
        self, configured_app: ConfiguredApp, app_version: str, app_config_file_path: Optional[str]
    ) -> ConfiguredApp:
        """
        Upgrade deployed stable version to the Under-Test version:

        Args:
             configured_app: App CR of the deployed stable version
             app_version: version to upgrade to
             app_config_file_path: configuration file for the deployment of the version to upgrade to
        """

        # prepare new values for app and app_cm
        app = configured_app.app
        app_cm: Optional[ConfigMap] = None
        # update chart reference
        app.reload()
        app.obj["spec"]["catalog"] = TEST_APP_CATALOG_NAME
        app.obj["spec"]["catalogNamespace"] = TEST_APP_CATALOG_NAMESPACE
        app.obj["spec"]["version"] = app_version

        # if there's a new config file, let's load it
        if app_config_file_path:
            with open(app_config_file_path) as f:
                config_values_raw = f.read()
                new_config_values = yaml.dump(yaml.safe_load(config_values_raw))

        # if the stable app used no config file, but the under-test version uses one
        # we have to created the CM and update App CR to reference it
        if not configured_app.app_cm and app_config_file_path:
            logger.debug("Detected that the stable app didn't use a ConfigMap, but the new one does. Creating CM.")
            # TODO: extract this to pytest-helm-charts to create Apps' CMs
            app_name = app.obj["spec"]["name"]
            app_namespace = app.obj["spec"]["namespace"]
            app_cm_name = f"{app_name}-testing-user-config"
            app_cm_data = {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": app_cm_name, "namespace": app_namespace},
                "data": {"values": new_config_values},
            }
            app_cm = ConfigMap(self._kube_client, app_cm_data)
            app_cm.create()
            app.obj["spec"]["config"] = {"configMap": {"name": app_cm_name, "namespace": app_namespace}}

        # if the stable app used a config file, but the under-test version doesn't use one
        # we have to delete the CM, remove the reference in App CR and update our app data structure
        if configured_app.app_cm and not app_config_file_path:
            logger.debug("Detected that the stable app used a ConfigMap, but the new one doesn't. Deleting CM.")
            del configured_app.app.obj["spec"]["config"]
            configured_app.app_cm.reload()
            configured_app.app_cm.delete()

        # if both the stable and under-test app versions used a config file, we just have to update the values
        if configured_app.app_cm is not None and app_config_file_path:
            app_cm = configured_app.app_cm
            app_cm.reload()
            if app_cm.obj["data"]["values"] != new_config_values:
                logger.debug("Detected that both old and new app versions use a ConfigMap. Updating CM.")
                app_cm.obj["data"]["values"] = new_config_values
                app_cm.update()
            else:
                logger.debug("Detected that both old and new app versions use the same ConfigMap. No CM update needed.")

        # finally, update the App CR
        logger.info("Updating App CR to point to the newer version.")
        app.update()
        return ConfiguredApp(app, app_cm)

    def _get_latest_app_version(self, stable_app_catalog_url: str, app_name: str) -> str:
        logger.info("Trying to detect latest app version available in the catalog.")
        catalog_index_url = stable_app_catalog_url + "/index.yaml"
        logger.debug(f"Trying to download catalog index '{catalog_index_url}'.")
        try:
            index_response = requests.get(catalog_index_url, headers={"User-agent": "Mozilla/5.0"})
            if not index_response.ok:
                raise ATSTestError(
                    f"Couldn't get the 'index.yaml' fetched from '{catalog_index_url}'. "
                    f"Reason: [{index_response.status_code}] {index_response.reason}."
                )
            index_response.encoding = index_response.apparent_encoding
            index = yaml.safe_load(index_response.text)
            index_response.close()
        except RequestException as e:
            logger.error(
                f"Error when trying to fetch remote '{catalog_index_url}' to detect what the 'latest'"
                f" version of the app is: '{e}'."
            )
            raise
        except (YAMLError, ParserError) as e:
            logger.error(
                f"Error when trying to parse YAML from a remote '{catalog_index_url}' to detect what"
                f" the 'latest' version of the app is: '{e}'."
            )
            raise

        if "entries" not in index:
            raise ATSTestError(f"'entries' field was not found in the 'index.yaml' fetched from '{catalog_index_url}'.")
        if app_name not in index["entries"]:
            raise ATSTestError(
                f"App '{app_name}' was not found in the 'index.yaml' fetched from '{catalog_index_url}'."
            )
        versions = [e["version"] for e in index["entries"][app_name]]
        versions.sort(key=LooseVersion, reverse=True)
        return versions[0]

    def _run_upgrade_hook(
        self,
        config: argparse.Namespace,
        stage_name: str,
        app_name: str,
        from_version: str,
        to_version: str,
    ) -> None:
        upgrade_hook_exe: str = get_config_value_by_cmd_line_option(config, KEY_CFG_UPGRADE_HOOK)
        if not upgrade_hook_exe:
            logger.info(f"No upgrade test {stage_name} hook configured. Moving on.")
            return

        logger.info(f"Executing upgrade hook: '{upgrade_hook_exe}' with stage '{stage_name}'.")
        deploy_namespace = get_config_value_by_cmd_line_option(
            config, BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_NAMESPACE
        )
        args = upgrade_hook_exe.split(" ")
        args += [
            stage_name,
            app_name,
            from_version,
            to_version,
            cast(ClusterInfo, self._cluster_info).kube_config_path,
            deploy_namespace,
        ]
        run_res = run_and_log(args)  # nosec, user configurable input, but we have to accept it here
        if run_res.returncode != 0:
            raise ATSTestError(
                f"Upgrade hook for stage '{stage_name}' returned non-zero exit code: '{run_res.returncode}'."
            )

    def _get_test_exec_info(self, chart_path: str, chart_ver: str, chart_config_file: str) -> TestExecInfo:
        cluster_info = cast(ClusterInfo, self._cluster_info)
        exec_info = TestExecInfo(
            chart_path=chart_path,
            chart_ver=chart_ver,
            app_config_file_path=chart_config_file,
            cluster_type=self._test_cluster_type,
            cluster_version=cluster_info.version,
            kube_config_path=os.path.abspath(cluster_info.kube_config_path),
            test_type=self.test_provided,
        )
        return exec_info

    def _save_metadata(
        self,
        app_name: str,
        chart_version: str,
        app_version: str,
        stable_chart_version: str,
        stable_app_version: str,
        cluster_type: str,
        cluster_version: str,
    ) -> None:
        metadata = {
            "appName": app_name,
            "chartVersion": chart_version,
            "appVersion": app_version,
            "clusterType": cluster_type,
            "clusterVersion": cluster_version,
            "upgradeToChartVersion": stable_chart_version,
            "upgradeToAppVersion": stable_app_version,
            "timestamp": datetime.datetime.utcnow().replace(microsecond=0).isoformat(),
        }
        meta_dir = f"{app_name}-{stable_chart_version}.tgz-meta"
        if not os.path.isdir(meta_dir):
            logger.debug(f"Creating '{meta_dir}' directory to store metadata.")
            os.mkdir(meta_dir)
        file_path = os.path.join(meta_dir, f"tested-upgrade-{chart_version}.yaml")
        with open(file_path, "w") as f:
            yaml.dump(metadata, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"Metadata with upgrade test result saved to '{file_path}'.")
