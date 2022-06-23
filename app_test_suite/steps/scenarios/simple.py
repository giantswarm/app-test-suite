import argparse
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional, Set, cast

import configargparse
import yaml
from pykube import HTTPClient, KubeConfig, ConfigMap
from pytest_helm_charts.giantswarm_app_platform.app import (
    ConfiguredApp,
    create_app,
    wait_for_apps_to_run,
    AppCR,
    delete_app,
    wait_for_app_to_be_deleted,
)
from step_exec_lib.errors import ConfigError
from step_exec_lib.steps import BuildStep
from step_exec_lib.types import StepType, STEP_ALL, Context
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option
from step_exec_lib.utils.processes import run_and_log

from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.cluster_providers.cluster_provider import ClusterType, ClusterInfo
from app_test_suite.errors import ATSTestError
from app_test_suite.steps.base import (
    TestExecutor,
    BaseTestScenariosFilteringPipeline,
    TestExecInfo,
    CONTEXT_KEY_CHART_YAML,
)
from app_test_suite.steps.repositories import ChartMuseumAppRepository
from app_test_suite.steps.test_types import (
    config_option_cluster_type_for_test_type,
    STEP_TEST_FUNCTIONAL,
    STEP_TEST_SMOKE,
)

TEST_APP_CATALOG_NAME: str = "chartmuseum"
TEST_APP_CATALOG_NAMESPACE: str = "default"
CONTEXT_KEY_APP_CR: str = "app_cr"
CONTEXT_KEY_APP_CM_CR: str = "app_cm_cr"
CHART_YAML = "Chart.yaml"

logger = logging.getLogger(__name__)


class SimpleTestScenario(BuildStep, ABC):
    """
    BaseTestRunner is a base class that can be used to implement a specific test scenario.
    It provides basic methods that are test-executor independent.

    Do a mixin of this class and a test executor mixin derived from TestExecutor class to get a provider specific
    test scenario.
    """

    _APPTESTCTL_BIN = "apptestctl"
    _APPTESTCTL_BOOTSTRAP_TIMEOUT_SEC = 180
    _MIN_APPTESTCTL_VERSION = "0.12.0"
    _MAX_APPTESTCTL_VERSION = "1.0.0"
    _APP_DEPLOYMENT_TIMEOUT_SEC = 1800
    _APP_DELETION_TIMEOUT_SEC = 600

    def __init__(self, cluster_manager: ClusterManager, test_executor: TestExecutor):
        self._cluster_manager = cluster_manager
        self._configured_cluster_type: ClusterType = ClusterType("")
        self._configured_cluster_config_file = ""
        self._kube_client: Optional[HTTPClient] = None
        self._cluster_info: Optional[ClusterInfo] = None
        self._default_app_cr_namespace = "default"
        self._skip_app_deploy = False
        self._test_executor = test_executor

    @property
    def steps_provided(self) -> Set[StepType]:
        return {STEP_ALL, self.test_provided}

    @property
    @abstractmethod
    def test_provided(self) -> StepType:
        raise NotImplementedError()

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

    def run_tests(self, config: argparse.Namespace, context: Context) -> None:
        app_config_file_path = get_config_value_by_cmd_line_option(
            config, BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_CONFIG_FILE
        )
        cluster_info = cast(ClusterInfo, self._cluster_info)
        exec_info = TestExecInfo(
            chart_path=config.chart_file,
            chart_ver=context[CONTEXT_KEY_CHART_YAML]["version"],
            app_config_file_path=app_config_file_path,
            cluster_type=self._test_cluster_type,
            cluster_version=cluster_info.version,
            kube_config_path=os.path.abspath(cluster_info.kube_config_path),
            test_type=self.test_provided,
            debug=config.debug,
        )
        self._test_executor.prepare_test_environment(exec_info)
        self._test_executor.execute_test(exec_info)

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
        args = [self._APPTESTCTL_BIN, "bootstrap", f"--kubeconfig-path={kube_config_path}", "--wait"]
        logger.info(f"Running {self._APPTESTCTL_BIN} tool to ensure app platform components on the target cluster")
        run_res = run_and_log(args)  # nosec, file is either autogenerated or in user's responsibility
        if run_res.returncode != 0:
            raise ATSTestError("Bootstrapping app platform on the target cluster failed")
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
        self._assert_binary_present_in_path(self._APPTESTCTL_BIN)
        # verify version
        run_res = run_and_log([self._APPTESTCTL_BIN, "version"], capture_output=True)  # nosec
        version_line = run_res.stdout.splitlines()[0]
        version = version_line.split(":")[1].strip()
        self._assert_version_in_range(
            self._APPTESTCTL_BIN, version, self._MIN_APPTESTCTL_VERSION, self._MAX_APPTESTCTL_VERSION
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
        self._test_executor.validate(config, self.name)

    def run(self, config: argparse.Namespace, context: Context) -> None:
        # this API might need a change if we need to pass some more information than just type and config file
        logger.info(
            f"Requesting new cluster of type '{self._configured_cluster_type}' using config file"
            f" '{self._configured_cluster_config_file}'."
        )
        self._cluster_info = self._cluster_manager.get_cluster_for_test_type(
            self._configured_cluster_type, self._configured_cluster_config_file, config
        )
        if not self._cluster_info:
            raise ATSTestError("Didn't get cluster info from cluster manager")

        logger.info("Establishing connection to the new cluster.")
        try:
            kube_config = KubeConfig.from_file(self._cluster_info.kube_config_path)
            self._kube_client = HTTPClient(kube_config)
        except Exception:
            raise ATSTestError("Can't establish connection to the new test cluster")

        # prepare app platform and upload artifacts
        if not self._cluster_info.app_platform_ready:
            logger.debug("App Platform not initialized, running `apptestctl`")
            self._ensure_app_platform_ready(self._cluster_info.kube_config_path)
            self._cluster_info.app_platform_ready = True
        else:
            logger.debug("App Platform already initialized, not running `apptestctl`")
        self._upload_chart_to_app_catalog(config, config.chart_file)

        try:
            if (
                not get_config_value_by_cmd_line_option(
                    config, BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_SKIP_DEPLOY_APP
                )
                and not self._skip_app_deploy
            ):
                self._deploy_tested_chart_as_app(config, context)
            self.run_tests(config, context)
        except Exception as e:
            raise ATSTestError(f"Application deployment failed: {e}")
        finally:
            if not get_config_value_by_cmd_line_option(
                config, BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_SKIP_DEPLOY_APP
            ) or not get_config_value_by_cmd_line_option(
                config, BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_SKIP_DELETE_APP
            ):
                self._delete_app(config, context)

    def _deploy_tested_chart_as_app(self, config: argparse.Namespace, context: Context) -> None:
        app_name = context[CONTEXT_KEY_CHART_YAML]["name"]
        app_version = context[CONTEXT_KEY_CHART_YAML]["version"]
        deploy_namespace = get_config_value_by_cmd_line_option(
            config, BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_NAMESPACE
        )
        app_config_file_path = get_config_value_by_cmd_line_option(
            config, BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_CONFIG_FILE
        )

        app_obj = self._deploy_chart(
            app_name,
            app_version,
            deploy_namespace,
            app_config_file_path,
            TEST_APP_CATALOG_NAME,
            TEST_APP_CATALOG_NAMESPACE,
        )
        context[CONTEXT_KEY_APP_CR] = app_obj.app
        context[CONTEXT_KEY_APP_CM_CR] = app_obj.app_cm

    def _deploy_chart(
        self,
        app_name: str,
        app_version: str,
        deploy_namespace: str,
        app_config_file_path: str,
        app_catalog_name: str,
        app_catalog_namespace: str,
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
            app_catalog_namespace,
            self._default_app_cr_namespace,
            deploy_namespace,
            config_values,
        )
        logger.debug(f"Waiting for app '{app_name}' to run...")
        wait_for_apps_to_run(
            self._kube_client, [app_name], self._default_app_cr_namespace, self._APP_DEPLOYMENT_TIMEOUT_SEC
        )
        return app_obj

    def _upload_chart_to_app_catalog(self, config: argparse.Namespace, chart_file_path: str) -> None:
        # in future, if we want to support multiple chart repositories, we need to make this configurable
        # right now, static dependency will do
        ChartMuseumAppRepository(self._kube_client).upload_artifact(config, chart_file_path)

    # noinspection PyMethodMayBeStatic
    def _delete_app(self, config: argparse.Namespace, context: Context) -> None:
        if get_config_value_by_cmd_line_option(
            config, BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_SKIP_DEPLOY_APP
        ):
            return

        # if the key is not in the context, it means the app was never deployed
        if CONTEXT_KEY_APP_CR not in context:
            return
        app_obj = cast(AppCR, context[CONTEXT_KEY_APP_CR])
        values_cm = None
        if CONTEXT_KEY_APP_CM_CR in context:
            values_cm = cast(ConfigMap, context[CONTEXT_KEY_APP_CM_CR])
        logger.info("Deleting App CR and its values CM")
        delete_app(ConfiguredApp(app_obj, values_cm))
        wait_for_app_to_be_deleted(self._kube_client, app_obj.name, app_obj.namespace, self._APP_DELETION_TIMEOUT_SEC)
        logger.info("Application deleted")


class FunctionalTestScenario(SimpleTestScenario):
    def __init__(self, cluster_manager: ClusterManager, test_executor: TestExecutor):
        super().__init__(cluster_manager, test_executor)

    @property
    def test_provided(self) -> StepType:
        return STEP_TEST_FUNCTIONAL


class SmokeTestScenario(SimpleTestScenario):
    def __init__(self, cluster_manager: ClusterManager, test_executor: TestExecutor):
        super().__init__(cluster_manager, test_executor)

    @property
    def test_provided(self) -> StepType:
        return STEP_TEST_SMOKE
