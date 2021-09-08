import argparse
import logging
import os
import shutil
from abc import ABC
from typing import cast, List, Any

import configargparse

from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.cluster_providers.cluster_provider import ClusterInfo
from app_test_suite.errors import TestError
from app_test_suite.steps.base_test_runner import (
    BaseTestRunnersFilteringPipeline,
    TestInfoProvider,
    BaseTestRunner,
    context_key_chart_yaml,
    TestExecInfo,
    TestExecutor,
)
from app_test_suite.steps.test_types import STEP_TEST_SMOKE, STEP_TEST_FUNCTIONAL
from app_test_suite.steps.upgrade_test_runner import BaseUpgradeTestRunner
from step_exec_lib.errors import ValidationError
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


class PytestExecutorMixin(TestExecutor):
    _PIPENV_BIN = "pipenv"
    _PYTEST_BIN = "pytest"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # This class is intended to be used as a mixin, that forwards constructor call to any other type
        #  inherited from except the mixin itself.
        super().__init__(*args, **kwargs)  # type: ignore
        self._pytest_dir = ""

    def prepare_test_environment(self, exec_info: TestExecInfo) -> None:
        args = [self._PIPENV_BIN, "install", "--deploy"]
        logger.info(
            f"Running {self._PIPENV_BIN} tool in '{exec_info.test_dir}' directory to install virtual env "
            f"for running tests."
        )
        pipenv_env = os.environ
        pipenv_env["PIPENV_IGNORE_VIRTUALENVS"] = "1"

        run_res = run_and_log(args, cwd=exec_info.test_dir, env=pipenv_env)  # nosec, no user input here
        if run_res.returncode != 0:
            raise TestError(f"Running '{args}' in directory '{exec_info.test_dir}' failed.")
        run_and_log([self._PIPENV_BIN, "--venv"], cwd=exec_info.test_dir)  # nosec, no user input here

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
        run_and_log([self._PIPENV_BIN, "--venv"], cwd=exec_info.test_dir)  # nosec, no user input here
        run_res = run_and_log(args, cwd=exec_info.test_dir)  # nosec, no user input here
        if run_res.returncode != 0:
            raise TestError(f"Pytest tests failed: running '{args}' in directory '{exec_info.test_dir}' failed.")

    def validate(self, config: argparse.Namespace, module_name: str) -> None:
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
        if shutil.which(self._PIPENV_BIN) is None:
            raise ValidationError(
                module_name,
                f"In order to install pytest virtual env, you need to have " f"'{self._PIPENV_BIN}' installed.",
            )
        self._pytest_dir = pytest_dir


class PytestTestRunner(PytestExecutorMixin, BaseTestRunner, ABC):
    _pipenv_bin = "pipenv"
    _pytest_bin = "pytest"

    def __init__(self, cluster_manager: ClusterManager):
        super().__init__(cluster_manager)
        self._pytest_dir = ""

    def pre_run(self, config: argparse.Namespace) -> None:
        super().pre_run(config)
        self.validate(config, self.name)

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
        self.prepare_test_environment(exec_info)
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


class PytestUpgradeTestRunner(PytestExecutorMixin, BaseUpgradeTestRunner):
    def __init__(self, cluster_manager: ClusterManager):
        super().__init__(cluster_manager)

    def pre_run(self, config: argparse.Namespace) -> None:
        super().pre_run(config)
        self.validate(config, self.name)

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
