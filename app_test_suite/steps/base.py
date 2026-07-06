import argparse
import logging
import os
import shutil
from abc import ABC
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from typing import Set, Optional, List, Dict

import configargparse
import yaml
from step_exec_lib.errors import ConfigError, ValidationError
from step_exec_lib.steps import BuildStepsFilteringPipeline, BuildStep
from step_exec_lib.types import Context, StepType, STEP_ALL
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option

from app_test_suite.errors import ATSTestError
from app_test_suite.cluster_manager import ClusterManager

CONTEXT_KEY_CHART_YAML: str = "chart_yaml"
CONTEXT_KEY_STABLE_CHART_YAML: str = "stable_chart_yaml"

logger = logging.getLogger(__name__)


class BaseTestScenariosFilteringPipeline(BuildStepsFilteringPipeline):
    """
    Pipeline that combines all the steps required to run application tests.
    """

    KEY_CONFIG_GROUP_NAME = "Base app testing options"
    KEY_CONFIG_OPTION_SKIP_DEPLOY_APP = "--app-tests-skip-app-deploy"
    KEY_CONFIG_OPTION_SKIP_DELETE_APP = "--app-tests-skip-app-delete"
    KEY_CONFIG_OPTION_DEPLOY_NAMESPACE = "--app-tests-deploy-namespace"
    KEY_CONFIG_OPTION_DEPLOY_CONFIG_FILE = "--app-tests-app-config-file"
    KEY_CONFIG_OPTION_PRE_HOOK = "--app-tests-pre-hook"
    KEY_CONFIG_OPTION_POST_HOOK = "--app-tests-post-hook"

    def __init__(self, pipeline: List[BuildStep], cluster_manager: ClusterManager):
        super().__init__(pipeline, self.KEY_CONFIG_GROUP_NAME)
        self._cluster_manager = cluster_manager

    def initialize_config(self, config_parser: configargparse.ArgParser) -> None:
        super().initialize_config(config_parser)
        config_parser.add_argument(
            "-c",
            "--chart-file",
            required=True,
            help="Path to the Helm Chart .tgz file to test.",
        )
        if self._config_parser_group is None:
            raise ValueError("'_config_parser_group' can't be None")
        self._config_parser_group.add_argument(
            self.KEY_CONFIG_OPTION_SKIP_DEPLOY_APP,
            required=False,
            action="store_true",
            help="Skip automated app deployment for the test run to the test cluster (via 'helm upgrade --install').",
        )
        self._config_parser_group.add_argument(
            self.KEY_CONFIG_OPTION_SKIP_DELETE_APP,
            required=False,
            action="store_true",
            help="Skip automated teardown of the deployed chart (via 'helm uninstall') after the test run.",
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
        self._config_parser_group.add_argument(
            self.KEY_CONFIG_OPTION_PRE_HOOK,
            required=False,
            help="Executable run after chart install but before tests. ATS_* env vars and KUBECONFIG are set.",
        )
        self._config_parser_group.add_argument(
            self.KEY_CONFIG_OPTION_POST_HOOK,
            required=False,
            help="Executable run after tests complete (pass or skip). ATS_* env vars and KUBECONFIG are set.",
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
                    f"Application config file '{app_config_file}' found, but can't be loaded as a correct YAML document."
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
    debug: bool
    """Should the test engine be run with debug enabled."""
    test_extra_info: Optional[Dict[str, str]] = None
    """Optional dict of key-value pairs that will be passed to the test executor"""
    release_name: Optional[str] = None
    """Name of the Helm release the chart under test was deployed as."""
    deploy_namespace: Optional[str] = None
    """Namespace the chart under test was deployed into."""


class TestExecutor(ABC):
    """
    Base abstract class to implement different test executors.

    Test executors are responsible for running actual tests in a scenario using a specific
    test platform like `pytest` or `go test`.
    """

    _test_dir: str

    def __init__(self) -> None:
        self._test_dir = ""

    def validate(self, config: argparse.Namespace, module_name: str) -> None:
        """Validate any configuration related to the test executor."""
        raise NotImplementedError()

    @staticmethod
    def _resolve_test_dir(chart_file: Optional[str], configured_dir: str, warn: bool = True) -> str:
        """Resolve the directory that holds the test source code.

        Tests are discovered relative to the executing directory (the current working directory),
        which decouples test discovery from the location of the chart archive under test, so the
        chart file can live anywhere (see issue #196). An absolute ``configured_dir`` is honored
        verbatim.

        For backward compatibility, if the directory isn't found relative to the working directory
        but does exist relative to the chart file's directory (the legacy behaviour), that location
        is used and a deprecation warning is logged (unless ``warn`` is ``False``).
        """
        cwd_dir = os.path.join(os.getcwd(), configured_dir)
        if os.path.isdir(cwd_dir):
            return cwd_dir
        if chart_file:
            legacy_dir = os.path.join(os.path.dirname(os.path.abspath(chart_file)), configured_dir)
            if os.path.isdir(legacy_dir):
                if warn:
                    logger.warning(
                        f"Test source directory '{cwd_dir}' was not found relative to the working directory, but "
                        f"'{legacy_dir}' relative to the chart file was; using the latter for backward compatibility. "
                        f"This fallback is deprecated: place your tests relative to the working directory (or pass an "
                        f"absolute test directory) instead."
                    )
                return legacy_dir
        return cwd_dir

    def prepare_test_environment(self, exec_info: TestExecInfo) -> None:
        """Optional step to prepare environment where your tests are executed (ie. installing dependencies)."""
        raise NotImplementedError()

    def execute_test(self, exec_info: TestExecInfo) -> None:
        """Execute test using a specific test executor and information provided as exec_info."""
        raise NotImplementedError()

    def get_test_info_env_variables(self, exec_info: TestExecInfo, append_to_sys_env: bool = True) -> Dict[str, str]:
        env_vars = {
            "ATS_CHART_PATH": exec_info.chart_path,
            "ATS_CHART_VERSION": exec_info.chart_ver,
            "ATS_CLUSTER_TYPE": exec_info.cluster_type,
            "ATS_CLUSTER_VERSION": exec_info.cluster_version,
            "ATS_TEST_TYPE": exec_info.test_type,
            "ATS_TEST_DIR": self._test_dir,
        }
        if append_to_sys_env:
            env_vars.update(os.environ)

        env_vars["KUBECONFIG"] = exec_info.kube_config_path

        if exec_info.app_config_file_path is not None:
            env_vars["ATS_APP_CONFIG_FILE_PATH"] = exec_info.app_config_file_path

        if exec_info.release_name is not None:
            env_vars["ATS_RELEASE_NAME"] = exec_info.release_name

        if exec_info.deploy_namespace is not None:
            env_vars["ATS_RELEASE_NAMESPACE"] = exec_info.deploy_namespace

        if exec_info.test_extra_info:
            env_vars.update({"ATS_EXTRA_" + k.upper(): v for k, v in exec_info.test_extra_info.items()})

        return env_vars


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
        self.extract_chart_info(config.chart_file, CONTEXT_KEY_CHART_YAML, context)

    def extract_chart_info(self, chart_file: str, context_key: str, context: Context) -> None:
        if not os.path.isfile(chart_file):
            raise ValidationError(self.name, f"Chart file '{chart_file}' not found")
        with TemporaryDirectory(prefix="ats-") as tmp_dir:
            shutil.unpack_archive(chart_file, tmp_dir)
            _, sub_dirs, _ = next(os.walk(tmp_dir))
            for sub_dir in sub_dirs:
                chart_yaml_path = os.path.join(tmp_dir, sub_dir, "Chart.yaml")
                if os.path.isfile(chart_yaml_path):
                    with open(chart_yaml_path, "r") as file:
                        chart_yaml = yaml.safe_load(file)
                        logger.debug(f"Loading 'Chart.yaml' from subdirectory '{sub_dir}' in the chart archive.")
                        context[context_key] = chart_yaml
                    break
            else:
                raise ValidationError(
                    self.name,
                    "Couldn't find 'Chart.yaml' in any subdirectory of the chart archive file.",
                )
