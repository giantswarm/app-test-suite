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


class GotestTestFilteringPipeline(BaseTestRunnersFilteringPipeline):
    key_config_option_gotest_dir = "--app-tests-gotest-tests-dir"

    def __init__(self) -> None:
        cluster_manager = ClusterManager()
        super().__init__(
            [
                TestInfoProvider(),
                GotestSmokeTestRunner(cluster_manager),
                GotestFunctionalTestRunner(cluster_manager),
                GotestUpgradeTestRunner(cluster_manager),
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


class GotestExecutorMixin(TestExecutor):
    _GOTEST_BIN = "go"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # This class is intended to be used as a mixin, that forwards constructor call to any other type
        #  inherited from except the mixin itself.
        super().__init__(*args, **kwargs)  # type: ignore
        self._gotest_dir = ""

    def prepare_test_environment(self, exec_info: TestExecInfo) -> None:
        return

    def execute_test(self, exec_info: TestExecInfo) -> None:
        env_vars = os.environ.copy()
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
        run_res = run_and_log(args, cwd=exec_info.test_dir, env=env_vars)  # nosec, no user input here
        if run_res.returncode != 0:
            raise TestError(f"Gotest tests failed: running '{args}' in directory '{exec_info.test_dir}' failed.")

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


class GotestTestRunner(GotestExecutorMixin, BaseTestRunner, ABC):
    def __init__(self, cluster_manager: ClusterManager):
        super().__init__(cluster_manager)
        self._gotest_dir = ""

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
            test_dir=self._gotest_dir,
        )
        self.prepare_test_environment(exec_info)
        self.execute_test(exec_info)


class GotestFunctionalTestRunner(GotestTestRunner):
    def __init__(self, cluster_manager: ClusterManager):
        super().__init__(cluster_manager)

    @property
    def test_provided(self) -> StepType:
        return STEP_TEST_FUNCTIONAL


class GotestSmokeTestRunner(GotestTestRunner):
    def __init__(self, cluster_manager: ClusterManager):
        super().__init__(cluster_manager)

    @property
    def test_provided(self) -> StepType:
        return STEP_TEST_SMOKE


class GotestUpgradeTestRunner(GotestExecutorMixin, BaseUpgradeTestRunner):
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
            test_dir=self._gotest_dir,
        )
        return exec_info
