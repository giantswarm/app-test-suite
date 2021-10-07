import argparse
import logging
import os
from typing import cast, List

import configargparse
from step_exec_lib.errors import ValidationError
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option
from step_exec_lib.utils.processes import run_and_handle_error

from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.errors import ATSTestError
from app_test_suite.steps.base_test_runner import (
    TestInfoProvider,
    TestExecInfo,
    TestExecutor,
    BaseTestScenariosFilteringPipeline,
    SmokeTestScenario,
    FunctionalTestScenario,
)
from steps.upgrade_test_runner import UpgradeTestScenario

logger = logging.getLogger(__name__)


class GotestTestFilteringPipeline(BaseTestScenariosFilteringPipeline):
    key_config_option_gotest_dir = "--app-tests-gotest-tests-dir"

    def __init__(self) -> None:
        cluster_manager = ClusterManager()
        test_executor = GotestExecutor()
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
            config_parser.add_argument_group("Gotest specific options"),
        )
        self._config_parser_group.add_argument(
            self.key_config_option_gotest_dir,
            required=False,
            default=os.path.join("tests", "ats"),
            help="Directory, where go tests source code can be found.",
        )


class GotestExecutor(TestExecutor):
    _GOTEST_BIN = "go"

    def __init__(self) -> None:
        self._gotest_dir = ""

    def prepare_test_environment(self, exec_info: TestExecInfo) -> None:
        return

    def execute_test(self, exec_info: TestExecInfo) -> None:
        env_vars = {}
        env_vars["ATS_CHART_PATH"] = exec_info.chart_path
        env_vars["ATS_CHART_VERSION"] = exec_info.chart_ver
        env_vars["ATS_CLUSTER_TYPE"] = exec_info.cluster_type
        env_vars["ATS_CLUSTER_VERSION"] = exec_info.cluster_version
        env_vars["ATS_KUBE_CONFIG_PATH"] = exec_info.kube_config_path
        env_vars["ATS_TEST_TYPE"] = exec_info.test_type
        env_vars["ATS_TEST_DIR"] = exec_info.test_dir

        if exec_info.app_config_file_path is not None:
            env_vars["ATS_APP_CONFIG_FILE_PATH"] = exec_info.app_config_file_path

        args = [
            self._GOTEST_BIN,
            "test",
            "-v",
            "-tags",
            exec_info.test_type,
        ]
        logger.info(f"Running {self._GOTEST_BIN} tool in '{exec_info.test_dir}' directory.")

        # If there are no Go tests with build tags for this test type we handle the error.
        run_res = run_and_handle_error(
            args, "build constraints exclude all Go files", cwd=exec_info.test_dir, env=env_vars
        )  # nosec, no user input here
        if run_res.returncode != 0:
            raise ATSTestError(f"Gotest tests failed: running '{args}' in directory '{exec_info.test_dir}' failed.")

    def validate(self, config: argparse.Namespace, module_name: str) -> None:
        gotest_dir = get_config_value_by_cmd_line_option(
            config, GotestTestFilteringPipeline.key_config_option_gotest_dir
        )
        gotest_dir = os.path.join(os.path.dirname(config.chart_file), gotest_dir)
        if not os.path.isdir(gotest_dir):
            raise ValidationError(
                module_name,
                f"Gotest tests were requested, but the configured test source code directory '{gotest_dir}'"
                f" doesn't exist.",
            )
        if not any(f.endswith(".go") for f in cast(List[str], os.listdir(gotest_dir))):
            raise ValidationError(
                module_name,
                f"Gotest tests were requested, but no go source code file was found in directory '{gotest_dir}'.",
            )
        self._gotest_dir = gotest_dir
