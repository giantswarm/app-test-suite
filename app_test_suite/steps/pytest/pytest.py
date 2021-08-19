import argparse
import logging
import os
import shutil
from abc import ABC
from typing import cast, List

import configargparse
import validators.url

from app_test_suite.__main__ import key_cfg_url_option, key_cfg_from_version_option
from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.errors import TestError
from app_test_suite.steps.base_test_runner import (
    BaseTestRunnersFilteringPipeline,
    TestInfoProvider,
    BaseTestRunner,
    context_key_chart_yaml,
)
from app_test_suite.steps.types import STEP_TEST_SMOKE, STEP_TEST_FUNCTIONAL, STEP_TEST_UPGRADE
from step_exec_lib.errors import ValidationError, ConfigError
from step_exec_lib.types import Context, StepType
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option
from step_exec_lib.utils.processes import run_and_log

logger = logging.getLogger(__name__)


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

        if not self._cluster_info:
            raise TestError("Cluster info is missing, can't run tests.")

        args = [self._pipenv_bin, "install", "--deploy"]
        logger.info(
            f"Running {self._pipenv_bin} tool in '{self._pytest_dir}' directory to install virtual env "
            f"for running tests."
        )
        run_res = run_and_log(args, cwd=self._pytest_dir)  # nosec, no user input here
        if run_res.returncode != 0:
            raise TestError(f"Running '{args}' in directory '{self._pytest_dir}' failed.")

        app_config_file_path = get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_deploy_config_file
        )
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
            config.chart_file,
            "--chart-version",
            context[context_key_chart_yaml]["version"],
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

    @property
    def test_provided(self) -> StepType:
        return STEP_TEST_UPGRADE

    def pre_run(self, config: argparse.Namespace) -> None:
        super().pre_run(config)

        catalog_url = get_config_value_by_cmd_line_option(config, key_cfg_url_option)
        url_validation_res = validators.url.url(catalog_url)
        if url_validation_res is not True:
            raise ConfigError(key_cfg_url_option, f"Wrong catalog URL: '{url_validation_res.args}'")

        app_ver = get_config_value_by_cmd_line_option(config, key_cfg_from_version_option)
        if not app_ver:
            raise ConfigError(key_cfg_from_version_option, "Version of app to upgrade from can't be empty")

        self._original_value_skip_deploy = get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_skip_deploy_app
        )
        # for upgrade testing we need to deploy the stable version of an app first, so we force skipping
        # automated deployment by `PytestTestRunner` here. Original value is restored in `cleanup`.
        if not self._original_value_skip_deploy:
            config.__setattr__(BaseTestRunnersFilteringPipeline.key_config_option_skip_deploy_app, True)

    def cleanup(
        self,
        config: argparse.Namespace,
        context: Context,
        has_build_failed: bool,
    ) -> None:
        super().cleanup(config, context, has_build_failed)
        # restore original value of it wasn't True
        if not self._original_value_skip_deploy:
            config.__setattr__(BaseTestRunnersFilteringPipeline.key_config_option_skip_deploy_app, False)

    def run_tests(self, config: argparse.Namespace, context: Context) -> None:
        catalog_url = get_config_value_by_cmd_line_option(config, key_cfg_url_option)
        logger.info(f"Adding new app catalog named 'stable' with URL '{catalog_url}'.")
        # app_catalog_cr = get_app_catalog_obj("stable", catalog_url, ZONK)
        # app_catalog_cr.create()

        # app_ver = get_config_value_by_cmd_line_option(config, key_cfg_from_version_option)
        # if app_ver == "latest":
        #     app_ver = self._get_latest_app_version()

        # TODO:
        # - check if catalog URL is valid and add AppCatalog object for it
        # - if needed, figure out the 'latest' version
        # - if configured, Deploy the stable version (check original value)
        # - run tests
        # - run the optional upgrade hook
        # - reconfigure App CR to point to version UT
        # - run tests again
        # - delete App CR
        # - delete Catalog CR
        pass
