import argparse
import logging
import os
import shutil
from abc import ABC
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from typing import Set, Optional, List

import configargparse
import yaml
from step_exec_lib.errors import ConfigError, ValidationError
from step_exec_lib.steps import BuildStepsFilteringPipeline, BuildStep
from step_exec_lib.types import Context, StepType, STEP_ALL
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option

from app_test_suite.errors import ATSTestError
from cluster_manager import ClusterManager

CONTEXT_KEY_CHART_YAML: str = "chart_yaml"

logger = logging.getLogger(__name__)


class BaseTestScenariosFilteringPipeline(BuildStepsFilteringPipeline):
    """
    Pipeline that combines all the steps required to run application tests.
    """

    KEY_CONFIG_GROUP_NAME = "Base app testing options"
    KEY_CONFIG_OPTION_SKIP_DEPLOY_APP = "--app-tests-skip-app-deploy"
    KEY_CONFIG_OPTION_DEPLOY_NAMESPACE = "--app-tests-deploy-namespace"
    KEY_CONFIG_OPTION_DEPLOY_CONFIG_FILE = "--app-tests-app-config-file"

    def __init__(self, pipeline: List[BuildStep], cluster_manager: ClusterManager):
        super().__init__(pipeline, self.KEY_CONFIG_GROUP_NAME)
        self._cluster_manager = cluster_manager

    def initialize_config(self, config_parser: configargparse.ArgParser) -> None:
        super().initialize_config(config_parser)
        config_parser.add_argument(
            "-c",
            "--chart-file",
            required=True,
            help="Path to the Helm Chart tar.gz file to test.",
        )
        if self._config_parser_group is None:
            raise ValueError("'_config_parser_group' can't be None")
        self._config_parser_group.add_argument(
            self.KEY_CONFIG_OPTION_SKIP_DEPLOY_APP,
            required=False,
            action="store_true",
            help="Skip automated app deployment for the test run to the test cluster (using an App CR).",
        )
        self._config_parser_group.add_argument(
            self.KEY_CONFIG_OPTION_DEPLOY_NAMESPACE,
            required=False,
            default="default",
            help="The namespace your app under test should be deployed to for running tests.",
        )
        self._config_parser_group.add_argument(
            self.KEY_CONFIG_OPTION_DEPLOY_CONFIG_FILE,
            required=False,
            help="Path for a configuration file (values file) for your app when it's deployed for testing.",
        )
        self._cluster_manager.initialize_config(self._config_parser_group)

    def pre_run(self, config: argparse.Namespace) -> None:
        super().pre_run(config)
        if self._all_pre_runs_skipped:
            return

        if not config.chart_file or not os.path.isfile(config.chart_file):
            raise ConfigError("chart-file", f"The file '{config.chart_file}' can't be found.")

        self._cluster_manager.pre_run(config)
        app_config_file = get_config_value_by_cmd_line_option(config, self.KEY_CONFIG_OPTION_DEPLOY_CONFIG_FILE)
        if app_config_file:
            if not os.path.isfile(app_config_file):
                raise ATSTestError(
                    f"Application test run was configured to use '{app_config_file}' as app"
                    f" config file, but it doesn't exist."
                )
            try:
                with open(app_config_file, "r") as file:
                    yaml.safe_load(file)
            except Exception:
                raise ATSTestError(
                    f"Application config file '{app_config_file}' found, but can't be loaded"
                    f"as a correct YAML document."
                )

    def cleanup(
        self,
        config: argparse.Namespace,
        context: Context,
        has_build_failed: bool,
    ) -> None:
        self._cluster_manager.cleanup()


@dataclass
class TestExecInfo:
    """
    TestExecInfo provides all the information that is passed from a test scenario to test executor.
    """

    chart_path: str
    """Path to the chart file under test."""
    chart_ver: str
    """Chart version detected from the chart."""
    app_config_file_path: Optional[str]
    """Path to an optional Helm values file used to configure the chart under test."""
    cluster_type: str
    """A string representing a cluster type that the test scenario is running on."""
    cluster_version: str
    """Kubernetes cluster version of a cluster the test scenario is running on."""
    kube_config_path: str
    """Path to kube.config to connect to the cluster."""
    test_type: str
    """Type of test to execute by the test executor."""
    test_dir: str
    """Path to a directory where test code is available."""


class TestExecutor(ABC):
    """
    Base abstract class to implement different test executors.

    Test executors are responsible for running actual tests in a scenario using a specific
    test platform like `pytest` or `go test`.
    """

    def validate(self, config: argparse.Namespace, module_name: str) -> None:
        """Validate any configuration related to the test executor."""
        raise NotImplementedError()

    def prepare_test_environment(self, exec_info: TestExecInfo) -> None:
        """Optional step to prepare environment where your tests are executed (ie. installing dependencies)."""
        raise NotImplementedError()

    def execute_test(self, exec_info: TestExecInfo) -> None:
        """Execute test using a specific test executor and information provided as exec_info."""
        raise NotImplementedError()


class TestInfoProvider(BuildStep):
    """
    Since the whole build pipeline can change Chart.yaml file multiple times, this
    class loads the Chart.yaml as dict into context at the beginning of testing
    pipeline.
    """

    @property
    def steps_provided(self) -> Set[StepType]:
        return {STEP_ALL}

    def run(self, config: argparse.Namespace, context: Context) -> None:
        with TemporaryDirectory(prefix="ats-") as tmp_dir:
            shutil.unpack_archive(config.chart_file, tmp_dir)
            _, sub_dirs, _ = next(os.walk(tmp_dir))
            for sub_dir in sub_dirs:
                chart_yaml_path = os.path.join(tmp_dir, sub_dir, "Chart.yaml")
                if os.path.isfile(chart_yaml_path):
                    with open(chart_yaml_path, "r") as file:
                        chart_yaml = yaml.safe_load(file)
                        logger.debug(f"Loading 'Chart.yaml' from subdirectory '{sub_dir}' in the chart archive.")
                        context[CONTEXT_KEY_CHART_YAML] = chart_yaml
                    break
            else:
                raise ValidationError(
                    self.name, "Couldn't find 'Chart.yaml' in any subdirectory of the chart archive file."
                )
