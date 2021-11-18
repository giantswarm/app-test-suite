import argparse
import logging
import os
import shutil
from typing import cast, List

import configargparse
from step_exec_lib.errors import ValidationError
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option
from step_exec_lib.utils.processes import run_and_log

from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.errors import ATSTestError
from app_test_suite.steps.base import (
    BaseTestScenariosFilteringPipeline,
    TestInfoProvider,
    TestExecInfo,
    TestExecutor,
)
from app_test_suite.steps.scenarios.simple import FunctionalTestScenario, SmokeTestScenario
from app_test_suite.steps.scenarios.upgrade import UpgradeTestScenario

logger = logging.getLogger(__name__)


class PytestScenariosFilteringPipeline(BaseTestScenariosFilteringPipeline):
    KEY_CONFIG_OPTION_PYTEST_DIR = "--app-tests-pytest-tests-dir"

    def __init__(self) -> None:
        cluster_manager = ClusterManager()
        test_executor = PytestExecutor()
        super().__init__(
            [
                TestInfoProvider(),
                SmokeTestScenario(cluster_manager, test_executor),
                FunctionalTestScenario(cluster_manager, test_executor),
                UpgradeTestScenario(cluster_manager, test_executor),
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
            self.KEY_CONFIG_OPTION_PYTEST_DIR,
            required=False,
            default=os.path.join("tests", "ats"),
            help="Directory, where pytest tests source code can be found.",
        )


class PytestExecutor(TestExecutor):
    _PIPENV_BIN = "pipenv"
    _PYTEST_BIN = "pytest"

    def prepare_test_environment(self, exec_info: TestExecInfo) -> None:
        args = [self._PIPENV_BIN, "install", "--deploy"]
        if exec_info.debug:
            args.append("--verbose")
        logger.info(
            f"Running {self._PIPENV_BIN} tool in '{self._test_dir}' directory to install virtual env "
            f"for running tests."
        )
        pipenv_env = os.environ
        pipenv_env["PIPENV_IGNORE_VIRTUALENVS"] = "1"
        pipenv_env.pop("VIRTUAL_ENV", "")

        run_res = run_and_log(args, cwd=self._test_dir, env=pipenv_env)  # nosec, no user input here
        if run_res.returncode != 0:
            raise ATSTestError(f"Running '{args}' in directory '{self._test_dir}' failed.")
        run_and_log([self._PIPENV_BIN, "--venv"], cwd=self._test_dir)  # nosec, no user input here

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
            "debug" if exec_info.debug else "info",
            f"--junitxml=test_results_{exec_info.test_type}.xml",
        ]
        if exec_info.app_config_file_path:
            args += ["--values-file", exec_info.app_config_file_path]
        logger.info(f"Running {self._PYTEST_BIN} tool in '{self._test_dir}' directory.")
        run_res = run_and_log(args, cwd=self._test_dir)  # nosec, no user input here
        # exit code 5 from pytest means that no tests matched the selector - it's not an error for us
        if run_res.returncode not in [0, 5]:
            raise ATSTestError(f"Pytest tests failed: running '{args}' in directory '{self._test_dir}' failed.")

    def validate(self, config: argparse.Namespace, module_name: str) -> None:
        pytest_dir = get_config_value_by_cmd_line_option(
            config, PytestScenariosFilteringPipeline.KEY_CONFIG_OPTION_PYTEST_DIR
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
        self._test_dir = pytest_dir
