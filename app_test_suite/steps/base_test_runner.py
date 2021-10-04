import argparse
import logging
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from typing import Set, Optional, List, cast

import configargparse
import yaml
from pykube import KubeConfig, HTTPClient, ConfigMap
from pytest_helm_charts.giantswarm_app_platform.custom_resources import AppCR
from pytest_helm_charts.giantswarm_app_platform.entities import ConfiguredApp
from pytest_helm_charts.giantswarm_app_platform.utils import (
    delete_app,
    wait_for_app_to_be_deleted,
    create_app,
    wait_for_apps_to_run,
)

from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.cluster_providers.cluster_provider import ClusterInfo, ClusterType
from app_test_suite.errors import TestError
from app_test_suite.steps.repositories import ChartMuseumAppRepository
from app_test_suite.steps.test_types import config_option_cluster_type_for_test_type
from step_exec_lib.errors import ConfigError, ValidationError
from step_exec_lib.steps import BuildStepsFilteringPipeline, BuildStep
from step_exec_lib.types import Context, StepType, STEP_ALL
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option
from step_exec_lib.utils.processes import run_and_log

TEST_APP_CATALOG_NAME: str = "chartmuseum"

context_key_chart_yaml: str = "chart_yaml"
context_key_app_cr: str = "app_cr"
context_key_app_cm_cr: str = "app_cm_cr"

_chart_yaml = "Chart.yaml"
logger = logging.getLogger(__name__)


class BaseTestRunnersFilteringPipeline(BuildStepsFilteringPipeline):
    """
    Pipeline that combines all the steps required to run application tests.
    """

    key_config_group_name = "Base app testing options"
    key_config_option_skip_deploy_app = "--app-tests-skip-app-deploy"
    key_config_option_deploy_namespace = "--app-tests-deploy-namespace"
    key_config_option_deploy_config_file = "--app-tests-app-config-file"

    def __init__(self, pipeline: List[BuildStep], cluster_manager: ClusterManager):
        super().__init__(pipeline, self.key_config_group_name)
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
            self.key_config_option_skip_deploy_app,
            required=False,
            action="store_true",
            help="Skip automated app deployment for the test run to the test cluster (using an App CR).",
        )
        self._config_parser_group.add_argument(
            self.key_config_option_deploy_namespace,
            required=False,
            default="default",
            help="The namespace your app under test should be deployed to for running tests.",
        )
        self._config_parser_group.add_argument(
            self.key_config_option_deploy_config_file,
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
        app_config_file = get_config_value_by_cmd_line_option(config, self.key_config_option_deploy_config_file)
        if app_config_file:
            if not os.path.isfile(app_config_file):
                raise TestError(
                    f"Application test run was configured to use '{app_config_file}' as app"
                    f" config file, but it doesn't exist."
                )
            try:
                with open(app_config_file, "r") as file:
                    yaml.safe_load(file)
            except Exception:
                raise TestError(
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
                        context[context_key_chart_yaml] = chart_yaml
                    break
            else:
                raise ValidationError(
                    self.name, "Couldn't find 'Chart.yaml' in any subdirectory of the chart archive file."
                )


class BaseTestRunner(BuildStep, ABC):
    _apptestctl_bin = "apptestctl"
    _apptestctl_bootstrap_timeout_sec = 180
    _min_apptestctl_version = "0.7.0"
    _max_apptestctl_version = "1.0.0"
    _app_deployment_timeout_sec = 1800
    _app_deletion_timeout_sec = 600

    def __init__(self, cluster_manager: ClusterManager):
        self._cluster_manager = cluster_manager
        self._configured_cluster_type: ClusterType = ClusterType("")
        self._configured_cluster_config_file = ""
        self._kube_client: Optional[HTTPClient] = None
        self._cluster_info: Optional[ClusterInfo] = None
        self._default_app_cr_namespace = "default"
        self._skip_app_deploy = False

    @property
    def steps_provided(self) -> Set[StepType]:
        return {STEP_ALL, self.test_provided}

    @property
    @abstractmethod
    def test_provided(self) -> StepType:
        raise NotImplementedError()

    @abstractmethod
    def run_tests(self, config: argparse.Namespace, context: Context) -> None:
        raise NotImplementedError

    @property
    def _config_cluster_type_attribute_name(self) -> str:
        return config_option_cluster_type_for_test_type(self.test_provided)

    @property
    def _config_cluster_config_file_attribute_name(self) -> str:
        return f"--{self.test_provided}-tests-cluster-config-file"

    @property
    def _test_cluster_type(self) -> str:
        if self._cluster_info is None:
            raise ValueError("_cluster_info can't be None")
        cluster_type = (
            self._cluster_info.overridden_cluster_type
            if self._cluster_info.overridden_cluster_type
            else self._cluster_info.cluster_type
        )
        return cluster_type

    def _ensure_app_platform_ready(self, kube_config_path: str) -> None:
        """
        Ensures that app platform components are already running in the requested cluster.
        This means:
        - app-operator
        - chart-operator
        - some chart repository (chart-museum)
        - AppCatalog CR is created in the API for the chart repository
        :return:

        Args:
            config:
            kubeconfig_path:
        """

        # run the tool
        args = [self._apptestctl_bin, "bootstrap", f"--kubeconfig-path={kube_config_path}", "--wait"]
        logger.info(f"Running {self._apptestctl_bin} tool to ensure app platform components on the target cluster")
        run_res = run_and_log(args)  # nosec, file is either autogenerated or in user's responsibility
        if run_res.returncode != 0:
            raise TestError("Bootstrapping app platform on the target cluster failed")
        logger.info("App platform components bootstrapped and ready to use.")

    def initialize_config(self, config_parser: configargparse.ArgParser) -> None:
        config_parser.add_argument(
            self._config_cluster_type_attribute_name,
            required=False,
            help=f"Cluster type to use for {self.test_provided} tests.",
        )
        config_parser.add_argument(
            self._config_cluster_config_file_attribute_name,
            required=False,
            help=f"Additional configuration file for the cluster used for {self.test_provided} tests.",
        )

    def pre_run(self, config: argparse.Namespace) -> None:
        # verify if binary present
        self._assert_binary_present_in_path(self._apptestctl_bin)
        # verify version
        run_res = run_and_log([self._apptestctl_bin, "version"], capture_output=True)  # nosec
        version_line = run_res.stdout.splitlines()[0]
        version = version_line.split(":")[1].strip()
        self._assert_version_in_range(
            self._apptestctl_bin, version, self._min_apptestctl_version, self._max_apptestctl_version
        )

        cluster_type = ClusterType(
            get_config_value_by_cmd_line_option(config, self._config_cluster_type_attribute_name)
        )
        cluster_config_file: str = get_config_value_by_cmd_line_option(
            config, self._config_cluster_config_file_attribute_name
        )
        known_cluster_types = self._cluster_manager.get_registered_cluster_types()
        if cluster_type not in known_cluster_types:
            raise ConfigError(
                f"--{self.test_provided}-tests-cluster-type",
                f"Unknown cluster type '{cluster_type}' requested for tests of type"
                f" '{self.test_provided}'. Known cluster types are: '{known_cluster_types}'.",
            )
        if cluster_config_file and not os.path.isfile(cluster_config_file):
            raise ConfigError(
                f"--{self.test_provided}-tests-cluster-config-file",
                f"Cluster config file '{cluster_config_file}' for cluster type"
                f" '{cluster_type}' requested for tests of type"
                f" '{self.test_provided}' doesn't exist.",
            )
        self._configured_cluster_type = cluster_type
        self._configured_cluster_config_file = cluster_config_file if cluster_config_file is not None else ""

    def run(self, config: argparse.Namespace, context: Context) -> None:
        # this API might need a change if we need to pass some more information than just type and config file
        logger.info(
            f"Requesting new cluster of type '{self._configured_cluster_type}' using config file"
            f" '{self._configured_cluster_config_file}'."
        )
        self._cluster_info = self._cluster_manager.get_cluster_for_test_type(
            self._configured_cluster_type, self._configured_cluster_config_file, config
        )

        logger.info("Establishing connection to the new cluster.")
        try:
            kube_config = KubeConfig.from_file(self._cluster_info.kube_config_path)
            self._kube_client = HTTPClient(kube_config)
        except Exception:
            raise TestError("Can't establish connection to the new test cluster")

        # prepare app platform and upload artifacts
        self._ensure_app_platform_ready(self._cluster_info.kube_config_path)
        self._upload_chart_to_app_catalog(config, config.chart_file)

        try:
            if (
                not get_config_value_by_cmd_line_option(
                    config, BaseTestRunnersFilteringPipeline.key_config_option_skip_deploy_app
                )
                and not self._skip_app_deploy
            ):
                self._deploy_tested_chart_as_app(config, context)
            self.run_tests(config, context)
        except Exception as e:
            raise TestError(f"Application deployment failed: {e}")
        finally:
            if not get_config_value_by_cmd_line_option(
                config, BaseTestRunnersFilteringPipeline.key_config_option_skip_deploy_app
            ):
                self._delete_app(config, context)

    def _deploy_tested_chart_as_app(self, config: argparse.Namespace, context: Context) -> None:
        app_name = context[context_key_chart_yaml]["name"]
        app_version = context[context_key_chart_yaml]["version"]
        deploy_namespace = get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_deploy_namespace
        )
        app_config_file_path = get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_deploy_config_file
        )

        app_obj = self._deploy_chart(
            app_name, app_version, deploy_namespace, app_config_file_path, TEST_APP_CATALOG_NAME
        )
        context[context_key_app_cr] = app_obj.app
        context[context_key_app_cm_cr] = app_obj.app_cm

    def _deploy_chart(
        self, app_name: str, app_version: str, deploy_namespace: str, app_config_file_path: str, app_catalog_name: str
    ) -> ConfiguredApp:
        config_values = None
        if app_config_file_path:
            with open(app_config_file_path) as f:
                config_values_raw = f.read()
                config_values = yaml.safe_load(config_values_raw)
        logger.info(f"Deploying App CR '{app_name}' into '{self._default_app_cr_namespace}' namespace.")
        app_obj = create_app(
            self._kube_client,
            app_name,
            app_version,
            app_catalog_name,
            self._default_app_cr_namespace,
            deploy_namespace,
            config_values,
        )
        logger.debug(f"Waiting for app '{app_name}' to run...")
        wait_for_apps_to_run(
            self._kube_client, [app_name], self._default_app_cr_namespace, self._app_deployment_timeout_sec
        )
        return app_obj

    def _upload_chart_to_app_catalog(self, config: argparse.Namespace, chart_file_path: str) -> None:
        # in future, if we want to support multiple chart repositories, we need to make this configurable
        # right now, static dependency will do
        ChartMuseumAppRepository(self._kube_client).upload_artifact(config, chart_file_path)

    # noinspection PyMethodMayBeStatic
    def _delete_app(self, config: argparse.Namespace, context: Context) -> None:
        if get_config_value_by_cmd_line_option(
            config, BaseTestRunnersFilteringPipeline.key_config_option_skip_deploy_app
        ):
            return

        app_obj = cast(AppCR, context[context_key_app_cr])
        values_cm = None
        if context_key_app_cm_cr in context:
            values_cm = cast(ConfigMap, context[context_key_app_cm_cr])
        logger.info("Deleting App CR and its values CM")
        delete_app(ConfiguredApp(app_obj, values_cm))
        wait_for_app_to_be_deleted(self._kube_client, app_obj.name, app_obj.namespace, self._app_deletion_timeout_sec)
        logger.info("Application deleted")


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
    def validate(self, config: argparse.Namespace, module_name: str) -> None:
        raise NotImplementedError()

    def execute_test(self, exec_info: TestExecInfo) -> None:
        raise NotImplementedError()

    def prepare_test_environment(self, exec_info: TestExecInfo) -> None:
        raise NotImplementedError()
