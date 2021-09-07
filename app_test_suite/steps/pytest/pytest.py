import argparse
import logging
import os
import re
import shutil
from abc import ABC
from dataclasses import dataclass
from distutils.version import LooseVersion
from re import Match
from typing import cast, List, Optional, Tuple

import configargparse
import requests
import yaml
from pytest_helm_charts.giantswarm_app_platform.app_catalog import get_app_catalog_obj
from pytest_helm_charts.giantswarm_app_platform.custom_resources import AppCatalogCR
from pytest_helm_charts.giantswarm_app_platform.entities import ConfiguredApp
from pytest_helm_charts.giantswarm_app_platform.utils import delete_app
from requests import RequestException
from validators.url import url as validator_url
from yaml import YAMLError
from yaml.parser import ParserError

from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.cluster_providers.cluster_provider import ClusterInfo
from app_test_suite.config import (
    key_cfg_upgrade_hook,
    key_cfg_stable_app_config,
    key_cfg_stable_app_version,
    key_cfg_stable_app_url,
    key_cfg_stable_app_file,
)
from app_test_suite.errors import TestError
from app_test_suite.steps.base_test_runner import (
    BaseTestRunnersFilteringPipeline,
    TestInfoProvider,
    BaseTestRunner,
    context_key_chart_yaml,
    TEST_APP_CATALOG_NAME,
)
from app_test_suite.steps.types import STEP_TEST_SMOKE, STEP_TEST_FUNCTIONAL, STEP_TEST_UPGRADE
from step_exec_lib.errors import ValidationError, ConfigError
from step_exec_lib.types import Context, StepType
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option, get_config_attribute_from_cmd_line_option
from step_exec_lib.utils.processes import run_and_log

logger = logging.getLogger(__name__)

KEY_PRE_UPGRADE = "pre-upgrade"
KEY_POST_UPGRADE = "post-upgrade"


class PytestTestFilteringPipeline(BaseTestRunnersFilteringPipeline):
    key_config_option_pytest_dir = "--app-tests-pytest-tests-dir"

    def __init__(self) -> None:
        cluster_manager = ClusterManager()
        super().__init__(
            [
                TestInfoProvider(),
                PytestSmokeTestRunner(cluster_manager),
                PytestFunctionalTestRunner(cluster_manager),
                PytestUpgradeTestRunner(cluster_manager),
            ],
            cluster_manager,
        )

    def initialize_config(self, config_parser: configargparse.ArgParser) -> None:
        super().initialize_config(config_parser)
        self._config_parser_group = cast(
            configargparse.ArgParser,
            config_parser.add_argument_group("Pytest specific options"),
        )
        self._config_parser_group.add_argument(
            self.key_config_option_pytest_dir,
            required=False,
            default=os.path.join("tests", "ats"),
            help="Directory, where pytest tests source code can be found.",
        )


@dataclass
class TestExecInfo:
    chart_path: str
    chart_ver: str
    app_config_file_path: Optional[str]
    cluster_type: str
    cluster_version: str
    kube_config_path: str
    test_type: str
    test_dir: str


class TestExecutor(ABC):
    def execute_test(self, exec_info: TestExecInfo) -> None:
        raise NotImplementedError()

    def prepare_test_environment(self, exec_info: TestExecInfo) -> None:
        raise NotImplementedError()


class PytestExecutor(TestExecutor):
    _PIPENV_BIN = "pipenv"
    _PYTEST_BIN = "pytest"

    def prepare_test_environment(self, exec_info: TestExecInfo) -> None:
        args = [self._PIPENV_BIN, "install", "--deploy"]
        logger.info(
            f"Running {self._PIPENV_BIN} tool in '{exec_info.test_dir}' directory to install virtual env "
            f"for running tests."
        )
        run_res = run_and_log(args, cwd=exec_info.test_dir)  # nosec, no user input here
        if run_res.returncode != 0:
            raise TestError(f"Running '{args}' in directory '{exec_info.test_dir}' failed.")

    def execute_test(self, exec_info: TestExecInfo) -> None:
        args = [
            self._PIPENV_BIN,
            "run",
            self._PYTEST_BIN,
            "-m",
            exec_info.test_type,
            "--cluster-type",
            exec_info.cluster_type,
            "--kube-config",
            exec_info.kube_config_path,
            "--chart-path",
            exec_info.chart_path,
            "--chart-version",
            exec_info.chart_ver,
            "--chart-extra-info",
            f"external_cluster_version={exec_info.cluster_version}",
            "--log-cli-level",
            "info",
            f"--junitxml=test_results_{exec_info.test_type}.xml",
        ]
        if exec_info.app_config_file_path:
            args += ["--values-file", exec_info.app_config_file_path]
        logger.info(f"Running {self._PYTEST_BIN} tool in '{exec_info.test_dir}' directory.")
        run_res = run_and_log(args, cwd=exec_info.test_dir)  # nosec, no user input here
        if run_res.returncode != 0:
            raise TestError(f"Pytest tests failed: running '{args}' in directory '{exec_info.test_dir}' failed.")


class PytestTestRunnerConfigAndValidationMixin:
    _pipenv_bin = "pipenv"

    def validate_pytest(self, config: argparse.Namespace, module_name: str) -> str:
        pytest_dir = get_config_value_by_cmd_line_option(
            config, PytestTestFilteringPipeline.key_config_option_pytest_dir
        )
        pytest_dir = os.path.join(os.path.dirname(config.chart_file), pytest_dir)
        if not os.path.isdir(pytest_dir):
            raise ValidationError(
                module_name,
                f"Pytest tests were requested, but the configured test source code directory '{pytest_dir}'"
                f" doesn't exist.",
            )
        if not any(f.endswith(".py") for f in cast(List[str], os.listdir(pytest_dir))):
            raise ValidationError(
                module_name,
                f"Pytest tests were requested, but no python source code file was found in"
                f" directory '{pytest_dir}'.",
            )
        if shutil.which(self._pipenv_bin) is None:
            raise ValidationError(
                module_name,
                f"In order to install pytest virtual env, you need to have " f"'{self._pipenv_bin}' installed.",
            )
        return pytest_dir


class PytestTestRunner(PytestTestRunnerConfigAndValidationMixin, BaseTestRunner, ABC):
    _pipenv_bin = "pipenv"
    _pytest_bin = "pytest"

    def __init__(self, cluster_manager: ClusterManager):
        super().__init__(cluster_manager)
        self._test_executor = PytestExecutor()
        self._pytest_dir = ""

    def pre_run(self, config: argparse.Namespace) -> None:
        super().pre_run(config)
        self._pytest_dir = self.validate_pytest(config, self.name)

    def run_tests(self, config: argparse.Namespace, context: Context) -> None:
        app_config_file_path = get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_deploy_config_file
        )
        cluster_info = cast(ClusterInfo, self._cluster_info)
        exec_info = TestExecInfo(
            chart_path=config.chart_file,
            chart_ver=context[context_key_chart_yaml]["version"],
            app_config_file_path=app_config_file_path,
            cluster_type=self._test_cluster_type,
            cluster_version=cluster_info.version,
            kube_config_path=os.path.abspath(cluster_info.kube_config_path),
            test_type=self.test_provided,
            test_dir=self._pytest_dir,
        )
        # self._create_virtualenv()
        self.prepare_test_environment(exec_info)
        # self._run_pytest(config.chart_file, context[context_key_chart_yaml]["version"], app_config_file_path)
        self.execute_test(exec_info)


class PytestFunctionalTestRunner(PytestTestRunner):
    def __init__(self, cluster_manager: ClusterManager):
        super().__init__(cluster_manager)

    @property
    def test_provided(self) -> StepType:
        return STEP_TEST_FUNCTIONAL


class PytestSmokeTestRunner(PytestTestRunner):
    def __init__(self, cluster_manager: ClusterManager):
        super().__init__(cluster_manager)

    @property
    def test_provided(self) -> StepType:
        return STEP_TEST_SMOKE


class BaseUpgradeTestRunner(BaseTestRunner):
    _STABLE_APP_CATALOG_NAME = "stable"

    def __init__(self, cluster_manager: ClusterManager, test_executor: TestExecutor):
        super().__init__(cluster_manager)
        self._test_executor = test_executor
        self._original_value_skip_deploy = None
        self._stable_from_local_file = False
        self._semver_regex_match = re.compile(r"^.+((0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*).*\.tgz)$")

    @property
    def test_provided(self) -> StepType:
        return STEP_TEST_UPGRADE

    def pre_run(self, config: argparse.Namespace) -> None:
        super().pre_run(config)

        catalog_url = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_url)
        stable_chart_file = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_file)
        if catalog_url:
            url_validation_res = validator_url(catalog_url)
            # FIXME: doesn't correctly validate 'http://chartmuseum-chartmuseum:8080/charts/' - needs at least 1 dot in
            #  the domain name
            if url_validation_res is not True:
                raise ConfigError(key_cfg_stable_app_url, f"Wrong catalog URL: '{url_validation_res.args[1]['value']}'")

            app_ver = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_version)
            if not app_ver:
                raise ConfigError(key_cfg_stable_app_version, "Version of app to upgrade from can't be empty")
        elif stable_chart_file:
            if not os.path.isfile(stable_chart_file):
                raise ConfigError(
                    key_cfg_stable_app_file,
                    f"Upgrade test from a stable chart in file '{stable_chart_file}' was requested, but "
                    "the file doesn't exist.",
                )
            self._stable_from_local_file = True
        else:
            raise ConfigError(
                f"{key_cfg_stable_app_url},{key_cfg_stable_app_file}",
                "Exactly one of these options must be configured.",
            )

        app_cfg_file = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_config)
        if app_cfg_file and not os.path.isfile(app_cfg_file):
            raise ConfigError(
                key_cfg_stable_app_config,
                "Config file for the app to upgrade from was given, " f"but not found. File name: '{app_cfg_file}'.",
            )

        upgrade_hook_exe: str = get_config_value_by_cmd_line_option(config, key_cfg_upgrade_hook)
        if upgrade_hook_exe:
            cmd = upgrade_hook_exe.split(" ")[0]
            if not shutil.which(cmd):
                raise ConfigError(
                    key_cfg_upgrade_hook,
                    f"Upgrade hook was configured, but '{cmd}' was not " f"found to be a valid executable.",
                )

        self._original_value_skip_deploy = get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_skip_deploy_app
        )
        # for upgrade testing we need to deploy the stable version of an app first, so we force skipping
        # automated deployment by `PytestTestRunner` here. Original value is restored in `cleanup`.
        if not self._original_value_skip_deploy:
            config.__setattr__(
                get_config_attribute_from_cmd_line_option(
                    BaseTestRunnersFilteringPipeline.key_config_option_skip_deploy_app
                ),
                True,
            )

    def cleanup(
        self,
        config: argparse.Namespace,
        context: Context,
        has_build_failed: bool,
    ) -> None:
        super().cleanup(config, context, has_build_failed)
        # restore original value of it wasn't True (see comment in pre_run)
        if not self._original_value_skip_deploy:
            config.__setattr__(
                get_config_attribute_from_cmd_line_option(
                    BaseTestRunnersFilteringPipeline.key_config_option_skip_deploy_app
                ),
                False,
            )

    def _prepare_stable_app(self, config: argparse.Namespace, app_name: str) -> Tuple[str, str, str]:
        if self._stable_from_local_file:
            # upload file to existing catalog
            stable_chart_file_path = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_file)
            self._upload_chart_to_app_catalog(config, stable_chart_file_path)
            app_catalog_cr = AppCatalogCR.objects(self._kube_client).get_by_name(TEST_APP_CATALOG_NAME)
            stable_ver_match = self._semver_regex_match.fullmatch(stable_chart_file_path)
            stable_app_version = cast(Match, stable_ver_match).group(0)
            return stable_app_version, TEST_APP_CATALOG_NAME, app_catalog_cr.obj["spec"]["storage"]["URL"]

        catalog_url = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_url)
        logger.info(f"Adding new app catalog named '{self._STABLE_APP_CATALOG_NAME}' with URL '{catalog_url}'.")
        app_catalog_cr = get_app_catalog_obj(self._STABLE_APP_CATALOG_NAME, catalog_url, self._kube_client)
        logger.debug(f"Creating AppCatalog '{app_catalog_cr.name}' with the stable app version.")
        app_catalog_cr.create()

        stable_app_ver = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_version)
        if stable_app_ver == "latest":
            stable_app_ver = self._get_latest_app_version(catalog_url, app_name)

        return stable_app_ver, self._STABLE_APP_CATALOG_NAME, catalog_url

    def run_tests(self, config: argparse.Namespace, context: Context) -> None:
        app_name = context[context_key_chart_yaml]["name"]
        app_version = context[context_key_chart_yaml]["version"]

        stable_app_ver, stable_app_catalog_name, stable_app_catalog_url = self._prepare_stable_app(config, app_name)

        deploy_namespace = get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_deploy_namespace
        )
        app_cfg_file = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_config)

        # deploy the stable version
        app_cr = self._deploy_chart(
            app_name, stable_app_ver, deploy_namespace, app_cfg_file, self._STABLE_APP_CATALOG_NAME
        )

        # run tests
        stable_chart_url = f"{stable_app_catalog_url}/{app_name}-{stable_app_ver}.tar.gz"
        exec_info = self._get_test_exec_info(stable_chart_url, stable_app_ver, app_cfg_file)
        self._test_executor.prepare_test_environment(exec_info)
        self._test_executor.execute_test(exec_info)

        # run the optional upgrade hook
        self._run_upgrade_hook(config, KEY_PRE_UPGRADE, app_name, stable_app_ver, app_version)

        # reconfigure App CR to point to the new version UT
        app_config_file_path = get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_deploy_config_file
        )
        self._upgrade_app_cr(app_cr, app_version, app_config_file_path)

        # run the optional upgrade hook
        self._run_upgrade_hook(config, KEY_POST_UPGRADE, app_name, stable_app_ver, app_version)

        # run tests again
        exec_info.chart_path = config.chart_file
        exec_info.chart_ver = app_version
        exec_info.app_config_file_path = app_config_file_path
        self._test_executor.execute_test(exec_info)

        # delete App CR
        logger.info(f"Deleting App CR '{app_cr.app.name}'.")
        delete_app(app_cr)

        # delete Catalog CR, if it was created
        app_catalog_cr = AppCatalogCR.objects(self._kube_client).get_or_none(self._STABLE_APP_CATALOG_NAME)
        if app_catalog_cr:
            logger.debug(f"Deleting AppCatalog '{app_catalog_cr.name}'.")
            app_catalog_cr.delete()

        # TODO: save upgrade metadata

    def _upgrade_app_cr(self, app_cr: ConfiguredApp, app_version: str, app_config_file_path: Optional[str]) -> None:
        app_cr.app.reload()

        app_cr.app.obj["spec"]["catalog"] = TEST_APP_CATALOG_NAME
        app_cr.app.obj["spec"]["version"] = app_version
        if app_config_file_path:
            with open(app_config_file_path) as f:
                config_values_raw = f.read()
                config_values = yaml.safe_load(config_values_raw)
            app_cr.app_cm.reload()
            if app_cr.app_cm.obj["data"]["values"] != config_values:
                app_cr.app_cm.obj["data"]["values"] = config_values
                app_cr.app_cm.update()
        logger.info("Updating App CR to point to the newer version.")
        app_cr.app.update()

    def _get_latest_app_version(self, stable_app_catalog_url: str, app_name: str) -> str:
        logger.info("Trying to detect latest app version available in the catalog.")
        catalog_index_url = stable_app_catalog_url + "/index.yaml"
        logger.debug(f"Trying to download catalog index '{catalog_index_url}'.")
        try:
            index_response = requests.get(catalog_index_url)
            if not index_response.ok:
                raise TestError(
                    f"Couldn't get the 'index.yaml' fetched from '{catalog_index_url}'. "
                    f"Reason: [{index_response.status_code}] {index_response.reason}."
                )
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
            raise TestError(f"'entries' field was not found in the 'index.yaml' fetched from '{catalog_index_url}'.")
        if app_name not in index["entries"]:
            raise TestError(f"App '{app_name}' was not found in the 'index.yaml' fetched from '{catalog_index_url}'.")
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
        upgrade_hook_exe: str = get_config_value_by_cmd_line_option(config, key_cfg_upgrade_hook)
        if not upgrade_hook_exe:
            logger.info("No upgrade test upgrade hook configured. Moving on.")
            return

        logger.info(f"Executing upgrade hook: '{upgrade_hook_exe}' with stage '{stage_name}'.")
        deploy_namespace = get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_deploy_namespace
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
            raise TestError(
                f"Upgrade hook for stage '{stage_name}' returned non-zero exit code: '{run_res.returncode}'."
            )

    def _get_test_exec_info(self, chart_path: str, chart_ver: str, chart_config_file: str) -> TestExecInfo:
        raise NotImplementedError()


class PytestUpgradeTestRunner(BaseUpgradeTestRunner, PytestExecutor):
    def __init__(self, cluster_manager: ClusterManager):
        test_executor = PytestExecutor()
        super().__init__(cluster_manager, test_executor)
        self._pytest_dir = ""

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
            test_dir=self._pytest_dir,
        )
        return exec_info
