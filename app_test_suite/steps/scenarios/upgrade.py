import argparse
import datetime
import logging
import os
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Tuple, cast, List, Match, Optional, Dict

import requests
import yaml
from requests import RequestException
from semver import VersionInfo
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
from app_test_suite.steps.scenarios.simple import (
    SimpleTestScenario,
    CONTEXT_KEY_RELEASE_NAME,
    _HELM_BIN,
)
from app_test_suite.steps.test_types import STEP_TEST_UPGRADE

KEY_PRE_UPGRADE = "pre_upgrade"
KEY_POST_UPGRADE = "post_upgrade"
KEY_UPGRADE_TEST_STAGE_EXTRA_INFO = "upgrade_test_stage"
_HELM_PULL_TIMEOUT_SEC = 120
_HTTP_TIMEOUT_SEC = 10
_OCI_SCHEME = "oci://"
_STABLE_VERSION_KEYWORD = "stable"

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
            # FIXME: doesn't correctly validate 'http://chartmuseum:8080/charts/' - needs at least 1 dot in
            #  the domain name
            if url_validation_res is not True:
                raise ConfigError(
                    KEY_CFG_STABLE_APP_URL,
                    f"Wrong catalog URL: '{url_validation_res.args[1]['value']}'",
                )

            app_ver = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_VERSION)
            if not app_ver:
                raise ConfigError(
                    KEY_CFG_STABLE_APP_VERSION,
                    "Version of app to upgrade from can't be empty",
                )
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
                    f"Upgrade hook was configured, but '{cmd}' was not found to be a valid executable.",
                )
        self._test_executor.validate(config, self.name)

    def _resolve_stable_chart(
        self,
        config: argparse.Namespace,
        context: Context,
        app_name: str,
        download_dir: str,
    ) -> Tuple[str, str]:
        """Resolve the stable chart to a local .tgz file and return its path and version."""
        if self._stable_from_local_file:
            stable_chart_file_path = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_FILE)
            stable_ver_match = self._semver_regex_match.fullmatch(stable_chart_file_path)
            stable_app_version = cast(Match, stable_ver_match).group(1)
            TestInfoProvider().extract_chart_info(stable_chart_file_path, CONTEXT_KEY_STABLE_CHART_YAML, context)
            return stable_chart_file_path, stable_app_version

        catalog_url = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_URL)
        stable_chart_ver = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_VERSION)
        is_oci = catalog_url.startswith(_OCI_SCHEME)

        if stable_chart_ver == _STABLE_VERSION_KEYWORD:
            if is_oci:
                stable_chart_ver = self._get_latest_stable_oci_version(catalog_url, app_name)
            else:
                stable_chart_ver = self._get_latest_stable_version(catalog_url, app_name)

        logger.info(f"Pulling stable chart '{app_name}' version '{stable_chart_ver}' from '{catalog_url}'.")
        if is_oci:
            pull_args = [
                _HELM_BIN,
                "pull",
                f"{catalog_url}/{app_name}",
                "--version",
                stable_chart_ver,
                "--destination",
                download_dir,
            ]
        else:
            pull_args = [
                _HELM_BIN,
                "pull",
                app_name,
                "--repo",
                catalog_url,
                "--version",
                stable_chart_ver,
                "--destination",
                download_dir,
            ]
        try:
            run_res = run_and_log(
                pull_args,
                env=self._helm_env(),
                timeout=_HELM_PULL_TIMEOUT_SEC,
            )  # nosec
        except subprocess.TimeoutExpired:
            raise ATSTestError(
                f"Pulling stable chart '{app_name}' version '{stable_chart_ver}' from '{catalog_url}' "
                f"timed out after {_HELM_PULL_TIMEOUT_SEC}s"
            )
        if run_res.returncode != 0:
            raise ATSTestError(
                f"Pulling stable chart '{app_name}' version '{stable_chart_ver}' from '{catalog_url}' failed"
            )
        stable_chart_file_path = os.path.join(download_dir, f"{app_name}-{stable_chart_ver}.tgz")
        TestInfoProvider().extract_chart_info(stable_chart_file_path, CONTEXT_KEY_STABLE_CHART_YAML, context)
        return stable_chart_file_path, stable_chart_ver

    def run_tests(self, config: argparse.Namespace, context: Context) -> None:
        app_name = context[CONTEXT_KEY_CHART_YAML]["name"]
        chart_version = context[CONTEXT_KEY_CHART_YAML]["version"]

        deploy_namespace = get_config_value_by_cmd_line_option(
            config,
            BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_NAMESPACE,
        )
        stable_app_cfg_file = get_config_value_by_cmd_line_option(config, KEY_CFG_STABLE_APP_CONFIG)
        app_config_file_path = get_config_value_by_cmd_line_option(
            config,
            BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_CONFIG_FILE,
        )

        with TemporaryDirectory("-ats-stable-chart") as stable_dir:
            stable_chart_file, stable_chart_ver = self._resolve_stable_chart(config, context, app_name, stable_dir)
            if VersionInfo.parse(stable_chart_ver) >= VersionInfo.parse(chart_version):
                logger.warning(
                    "You have requested upgrade test where the stable chart version seems to be "
                    "newer then (or the same as) the version under test. Stable version is "
                    f"'{stable_chart_ver}', under test '{chart_version}'."
                )

            # deploy the stable version
            self._helm_deploy(app_name, stable_chart_file, deploy_namespace, stable_app_cfg_file)
            context[CONTEXT_KEY_RELEASE_NAME] = app_name

            # run pre-upgrade tests
            exec_info = self._get_test_exec_info(
                stable_chart_file,
                stable_chart_ver,
                stable_app_cfg_file,
                config,
                release_name=app_name,
                deploy_namespace=deploy_namespace,
                test_extra_info={KEY_UPGRADE_TEST_STAGE_EXTRA_INFO: KEY_PRE_UPGRADE},
            )
            self._test_executor.prepare_test_environment(exec_info)
            self._test_executor.execute_test(exec_info)

            # run the optional pre-upgrade hook
            self._run_upgrade_hook(config, KEY_PRE_UPGRADE, app_name, stable_chart_ver, chart_version)

            # upgrade to the version under test
            self._helm_deploy(app_name, config.chart_file, deploy_namespace, app_config_file_path)

            # run the optional post-upgrade hook
            self._run_upgrade_hook(config, KEY_POST_UPGRADE, app_name, stable_chart_ver, chart_version)

            # run tests again against the upgraded release
            exec_info.chart_path = config.chart_file
            exec_info.chart_ver = chart_version
            exec_info.app_config_file_path = app_config_file_path
            cast(Dict[str, str], exec_info.test_extra_info)[KEY_UPGRADE_TEST_STAGE_EXTRA_INFO] = KEY_POST_UPGRADE
            self._test_executor.execute_test(exec_info)

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

    def _get_latest_stable_version(self, stable_app_catalog_url: str, app_name: str) -> str:
        logger.info("Trying to detect the latest stable app version available in the catalog.")
        catalog_index_url = stable_app_catalog_url + "/index.yaml"
        logger.debug(f"Trying to download catalog index '{catalog_index_url}'.")
        try:
            index_response = requests.get(
                catalog_index_url, headers={"User-agent": "Mozilla/5.0"}, timeout=_HTTP_TIMEOUT_SEC
            )
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
                f"Error when trying to fetch remote '{catalog_index_url}' to detect the latest stable"
                f" version of the app: '{e}'."
            )
            raise
        except (YAMLError, ParserError) as e:
            logger.error(
                f"Error when trying to parse YAML from a remote '{catalog_index_url}' to detect the latest"
                f" stable version of the app: '{e}'."
            )
            raise

        if "entries" not in index:
            raise ATSTestError(f"'entries' field was not found in the 'index.yaml' fetched from '{catalog_index_url}'.")
        if app_name not in index["entries"]:
            raise ATSTestError(
                f"App '{app_name}' was not found in the 'index.yaml' fetched from '{catalog_index_url}'."
            )
        versions = [e["version"] for e in index["entries"][app_name]]
        latest_stable = self._pick_latest_stable_version(versions, app_name, catalog_index_url)
        logger.info(
            f"Detected '{latest_stable}' as the latest stable version of app '{app_name}'"
            f" in catalog '{catalog_index_url}'."
        )
        return latest_stable

    def _get_latest_stable_oci_version(self, stable_app_catalog_url: str, app_name: str) -> str:
        logger.info("Trying to detect the latest stable app version available in the OCI registry.")
        registry_path = stable_app_catalog_url[len(_OCI_SCHEME) :]
        registry_host, _, repository_prefix = registry_path.partition("/")
        repository = f"{repository_prefix}/{app_name}" if repository_prefix else app_name
        tags = self._list_oci_tags(registry_host, repository)
        latest_stable = self._pick_latest_stable_version(tags, app_name, stable_app_catalog_url)
        logger.info(
            f"Detected '{latest_stable}' as the latest stable version of app '{app_name}'"
            f" in OCI registry '{stable_app_catalog_url}'."
        )
        return latest_stable

    @staticmethod
    def _list_oci_tags(registry_host: str, repository: str) -> List[str]:
        tags_url = f"https://{registry_host}/v2/{repository}/tags/list"
        try:
            response = requests.get(tags_url, timeout=_HTTP_TIMEOUT_SEC)
            if response.status_code == 401:
                token = UpgradeTestScenario._get_oci_pull_token(response, repository)
                response = requests.get(
                    tags_url, headers={"Authorization": f"Bearer {token}"}, timeout=_HTTP_TIMEOUT_SEC
                )
            if not response.ok:
                raise ATSTestError(
                    f"Couldn't list tags for '{repository}' from '{tags_url}'. "
                    f"Reason: [{response.status_code}] {response.reason}."
                )
            tags = response.json().get("tags") or []
            response.close()
        except RequestException as e:
            logger.error(f"Error when trying to list tags for '{repository}' from '{tags_url}': '{e}'.")
            raise
        return tags

    @staticmethod
    def _get_oci_pull_token(challenge_response: requests.Response, repository: str) -> str:
        challenge = challenge_response.headers.get("WWW-Authenticate", "")
        params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        realm = params.get("realm")
        if not realm:
            raise ATSTestError(
                f"OCI registry did not advertise a bearer token realm for '{repository}'; "
                f"'WWW-Authenticate' header was '{challenge}'."
            )
        query = {
            "service": params.get("service", ""),
            "scope": params.get("scope") or f"repository:{repository}:pull",
        }
        token_response = requests.get(realm, params=query, timeout=_HTTP_TIMEOUT_SEC)
        if not token_response.ok:
            raise ATSTestError(
                f"Couldn't get an anonymous pull token from '{realm}' for '{repository}'. "
                f"Reason: [{token_response.status_code}] {token_response.reason}."
            )
        token_body = token_response.json()
        token = token_body.get("token") or token_body.get("access_token")
        if not token:
            raise ATSTestError(f"Token endpoint '{realm}' returned no token for '{repository}'.")
        return token

    @staticmethod
    def _pick_latest_stable_version(versions: List[str], app_name: str, source: str) -> str:
        stable_versions = []
        for version in versions:
            try:
                parsed = VersionInfo.parse(version)
            except ValueError:
                continue
            if parsed.prerelease is None:
                stable_versions.append(version)
        if not stable_versions:
            raise ATSTestError(f"No stable version of app '{app_name}' was found in '{source}'.")
        stable_versions.sort(key=VersionInfo.parse, reverse=True)
        return stable_versions[0]

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
            config,
            BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_NAMESPACE,
        )
        env = os.environ.copy()
        env["KUBECONFIG"] = cast(ClusterInfo, self._cluster_info).kube_config_path
        env["ATS_HOOK_STAGE"] = stage_name
        env["ATS_TEST_TYPE"] = str(self.test_provided)
        env["ATS_RELEASE_NAME"] = app_name
        env["ATS_UPGRADE_FROM_VERSION"] = from_version
        env["ATS_UPGRADE_TO_VERSION"] = to_version
        if deploy_namespace:
            env["ATS_RELEASE_NAMESPACE"] = deploy_namespace
        args = upgrade_hook_exe.split(" ")
        run_res = run_and_log(args, env=env)  # nosec, user configurable input, but we have to accept it here
        if run_res.returncode != 0:
            raise ATSTestError(
                f"Upgrade hook for stage '{stage_name}' returned non-zero exit code: '{run_res.returncode}'."
            )

    def _get_test_exec_info(
        self,
        chart_path: str,
        chart_ver: str,
        chart_config_file: str,
        config: argparse.Namespace,
        release_name: Optional[str] = None,
        deploy_namespace: Optional[str] = None,
        test_extra_info: Optional[Dict[str, str]] = None,
    ) -> TestExecInfo:
        cluster_info = cast(ClusterInfo, self._cluster_info)
        exec_info = TestExecInfo(
            chart_path=chart_path,
            chart_ver=chart_ver,
            app_config_file_path=chart_config_file,
            cluster_type=self._test_cluster_type,
            cluster_version=cluster_info.version,
            kube_config_path=os.path.abspath(cluster_info.kube_config_path),
            test_type=self.test_provided,
            debug=config.debug,
            release_name=release_name,
            deploy_namespace=deploy_namespace,
            test_extra_info=test_extra_info,
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
            "timestamp": datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat(),
        }
        meta_dir = f"{app_name}-{stable_chart_version}.tgz-meta"
        if not os.path.isdir(meta_dir):
            logger.debug(f"Creating '{meta_dir}' directory to store metadata.")
            os.mkdir(meta_dir)
        file_path = os.path.join(meta_dir, f"tested-upgrade-{chart_version}.yaml")
        with open(file_path, "w") as f:
            yaml.dump(metadata, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"Metadata with upgrade test result saved to '{file_path}'.")
