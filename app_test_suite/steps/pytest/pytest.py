import argparse
import logging
import os
import shutil
from abc import ABC
from typing import cast, List, Optional

import configargparse
import yaml
from pytest_helm_charts.giantswarm_app_platform.app_catalog import get_app_catalog_obj
from pytest_helm_charts.giantswarm_app_platform.entities import ConfiguredApp
from pytest_helm_charts.giantswarm_app_platform.utils import delete_app
from validators.url import url as validator_url

from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.config import (
    key_cfg_stable_app_url,
    key_cfg_stable_app_version,
    key_cfg_stable_app_config,
    key_cfg_upgrade_hook,
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


class PytestTestRunner(BaseTestRunner, ABC):
    _pipenv_bin = "pipenv"
    _pytest_bin = "pytest"

    def __init__(self, cluster_manager: ClusterManager):
        super().__init__(cluster_manager)
        self._skip_tests = False
        self._pytest_dir = ""

    def pre_run(self, config: argparse.Namespace) -> None:
        super().pre_run(config)

        pytest_dir = get_config_value_by_cmd_line_option(
            config, PytestTestFilteringPipeline.key_config_option_pytest_dir
        )
        pytest_dir = os.path.join(os.path.dirname(config.chart_file), pytest_dir)
        if not os.path.isdir(pytest_dir):
            logger.warning(
                f"Pytest tests were requested, but the configured test source code directory '{pytest_dir}'"
                f" doesn't exist. Skipping pytest run."
            )
            self._skip_tests = True
            return
        if not any(f.endswith(".py") for f in cast(List[str], os.listdir(pytest_dir))):
            logger.warning(
                f"Pytest tests were requested, but no python source code file was found in"
                f" directory '{pytest_dir}'. Skipping pytest run."
            )
            self._skip_tests = True
            return
        if shutil.which(self._pipenv_bin) is None:
            raise ValidationError(
                self.name,
                f"In order to install pytest virtual env, you need to have " f"'{self._pipenv_bin}' installed.",
            )
        self._pytest_dir = pytest_dir

    def run_tests(self, config: argparse.Namespace, context: Context) -> None:
        if self._skip_tests:
            logger.warning("Not running any pytest tests, as validation failed in pre_run step.")
            return

        self._create_virtualenv()

        app_config_file_path = get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_deploy_config_file
        )
        self._run_pytest(config.chart_file, context[context_key_chart_yaml]["version"], app_config_file_path)

    def _run_pytest(self, chart_path: str, chart_ver: str, app_config_file_path: Optional[str] = None) -> None:
        if not self._cluster_info:
            raise TestError("Cluster info is missing, can't run tests.")

        cluster_type = (
            self._cluster_info.overridden_cluster_type
            if self._cluster_info.overridden_cluster_type
            else self._cluster_info.cluster_type
        )
        kube_config = os.path.abspath(self._cluster_info.kube_config_path)
        cluster_version = self._cluster_info.version
        args = [
            self._pipenv_bin,
            "run",
            self._pytest_bin,
            "-m",
            self.test_provided,
            "--cluster-type",
            cluster_type,
            "--kube-config",
            kube_config,
            "--chart-path",
            chart_path,
            "--chart-version",
            chart_ver,
            "--chart-extra-info",
            f"external_cluster_version={cluster_version}",
            "--log-cli-level",
            "info",
            f"--junitxml=test_results_{self.test_provided}.xml",
        ]
        if app_config_file_path:
            args += ["--values-file", app_config_file_path]
        logger.info(f"Running {self._pytest_bin} tool in '{self._pytest_dir}' directory.")
        run_res = run_and_log(args, cwd=self._pytest_dir)  # nosec, no user input here
        if run_res.returncode != 0:
            raise TestError(f"Pytest tests failed: running '{args}' in directory '{self._pytest_dir}' failed.")

    def _create_virtualenv(self) -> None:
        args = [self._pipenv_bin, "install", "--deploy"]
        logger.info(
            f"Running {self._pipenv_bin} tool in '{self._pytest_dir}' directory to install virtual env "
            f"for running tests."
        )
        run_res = run_and_log(args, cwd=self._pytest_dir)  # nosec, no user input here
        if run_res.returncode != 0:
            raise TestError(f"Running '{args}' in directory '{self._pytest_dir}' failed.")


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


class PytestUpgradeTestRunner(PytestTestRunner):
    def __init__(self, cluster_manager: ClusterManager):
        super().__init__(cluster_manager)
        self._original_value_skip_deploy = None
        self._stable_app_catalog_name = "stable"

    @property
    def test_provided(self) -> StepType:
        return STEP_TEST_UPGRADE

    def pre_run(self, config: argparse.Namespace) -> None:
        super().pre_run(config)

        catalog_url = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_url)
        url_validation_res = validator_url(catalog_url)
        # FIXME: doesn't correctly validate 'http://chartmuseum-chartmuseum:8080/charts/' - needs at least 1 dot in
        #  the domain name
        if url_validation_res is not True:
            raise ConfigError(key_cfg_stable_app_url, f"Wrong catalog URL: '{url_validation_res.args[1]['value']}'")

        app_ver = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_version)
        if not app_ver:
            raise ConfigError(key_cfg_stable_app_version, "Version of app to upgrade from can't be empty")

        app_cfg_file = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_config)
        if app_cfg_file and not os.path.isfile(app_cfg_file):
            raise ConfigError(
                key_cfg_stable_app_config,
                "Config file for the app to upgrade from was given, " f"but not found. File name: '{app_cfg_file}'.",
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
        # restore original value of it wasn't True
        if not self._original_value_skip_deploy:
            config.__setattr__(
                get_config_attribute_from_cmd_line_option(
                    BaseTestRunnersFilteringPipeline.key_config_option_skip_deploy_app
                ),
                False,
            )

    def run_tests(self, config: argparse.Namespace, context: Context) -> None:
        if self._skip_tests:
            logger.warning("Not running any pytest tests, as validation failed in pre_run step.")
            return

        catalog_url = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_url)
        logger.info(f"Adding new app catalog named '{self._stable_app_catalog_name}' with URL '{catalog_url}'.")
        app_catalog_cr = get_app_catalog_obj(self._stable_app_catalog_name, catalog_url, self._kube_client)
        app_catalog_cr.create()

        app_version = context[context_key_chart_yaml]["version"]
        stable_app_ver = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_version)
        if stable_app_ver == "latest":
            stable_app_ver = self._get_latest_app_version(config)

        app_name = context[context_key_chart_yaml]["name"]
        deploy_namespace = get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_deploy_namespace
        )
        app_cfg_file = get_config_value_by_cmd_line_option(config, key_cfg_stable_app_config)

        # deploy the stable version
        app_cr = self._deploy_chart(
            app_name, stable_app_ver, deploy_namespace, app_cfg_file, self._stable_app_catalog_name
        )

        # run tests
        stable_chart_url = f"{catalog_url}/{app_name}-{stable_app_ver}.tar.gz"
        self._run_pytest(stable_chart_url, stable_app_ver, app_cfg_file)

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
        self._run_pytest(config.chart_file, app_version, app_config_file_path)

        # delete App CR
        delete_app(app_cr)

        # delete Catalog CR
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
        app_cr.app.update()

    def _get_latest_app_version(self, config: argparse.Namespace) -> str:
        # TODO: implement
        raise NotImplementedError()

    def _run_upgrade_hook(
        self, config: argparse.Namespace, stage_name: str, app_name: str, from_version: str, to_version: str
    ) -> None:
        upgrade_hook_exe: str = get_config_value_by_cmd_line_option(config, key_cfg_upgrade_hook)
        if not upgrade_hook_exe:
            logger.info("No upgrade test upgrade hook configured. Moving on.")
            return
        logger.info(f"Executing upgrade hook: '{upgrade_hook_exe}' with stage '{stage_name}'.")
        args = upgrade_hook_exe.split(" ")
        args += [stage_name, app_name, from_version, to_version]
        run_res = run_and_log(args, cwd=self._pytest_dir)  # nosec, no user input here
        if run_res.returncode != 0:
            raise TestError(
                f"Upgrade hook for stage '{stage_name}' returned non-zero exit code: '{run_res.returncode}'."
            )
