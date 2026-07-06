import argparse
import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Set, cast

import configargparse
import yaml
import pykube
from pykube import HTTPClient, KubeConfig
from pytest_helm_charts.k8s.namespace import ensure_namespace_exists
from step_exec_lib.errors import ConfigError
from step_exec_lib.steps import BuildStep
from step_exec_lib.types import StepType, STEP_ALL, Context
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option
from step_exec_lib.utils.processes import run_and_log

from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.cluster_providers.cluster_provider import ClusterType, ClusterInfo
from app_test_suite.errors import ATSTestError
from app_test_suite.gitops import (
    GitOpsEngine,
    detect_engines,
    parse_engines_option,
)
from app_test_suite.steps.base import (
    TestExecutor,
    BaseTestScenariosFilteringPipeline,
    TestExecInfo,
    CONTEXT_KEY_CHART_YAML,
)
from app_test_suite.steps.test_types import (
    config_option_cluster_type_for_test_type,
    STEP_TEST_FUNCTIONAL,
    STEP_TEST_SMOKE,
)

CONTEXT_KEY_RELEASE_NAME: str = "release_name"
CHART_YAML = "Chart.yaml"
_HELM_BIN = "helm"
_KUBECTL_BIN = "kubectl"
_HELM_DEPLOY_TIMEOUT = "30m"

logger = logging.getLogger(__name__)


class SimpleTestScenario(BuildStep, ABC):
    """
    BaseTestRunner is a base class that can be used to implement a specific test scenario.
    It provides basic methods that are test-executor independent.

    Do a mixin of this class and a test executor mixin derived from TestExecutor class to get a provider specific
    test scenario.
    """

    _CRD_DIR = "/etc/ats/crds"

    def __init__(self, cluster_manager: ClusterManager, test_executor: TestExecutor):
        self._cluster_manager = cluster_manager
        self._configured_cluster_type: ClusterType = ClusterType("")
        self._configured_cluster_config_file = ""
        self._kube_client: Optional[HTTPClient] = None
        self._cluster_info: Optional[ClusterInfo] = None
        self._skip_app_deploy = False
        self._test_executor = test_executor
        # None means 'auto': detect engines from the rendered chart at run time
        self._configured_gitops_engines: Optional[List[GitOpsEngine]] = None

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
    def _config_gitops_engines_attribute_name(self) -> str:
        return f"--{self.test_provided}-tests-gitops-engines"

    def _config_gitops_values_attribute_name(self, engine: GitOpsEngine) -> str:
        return f"--{self.test_provided}-tests-gitops-values-{engine.value}"

    @property
    def _config_gitops_bundle_ready_timeout_attribute_name(self) -> str:
        return f"--{self.test_provided}-tests-gitops-bundle-ready-timeout"

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
            config,
            BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_CONFIG_FILE,
        )
        deploy_namespace = get_config_value_by_cmd_line_option(
            config,
            BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_NAMESPACE,
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
            release_name=context.get(CONTEXT_KEY_RELEASE_NAME),
            deploy_namespace=deploy_namespace,
        )
        self._test_executor.prepare_test_environment(exec_info)
        self._test_executor.execute_test(exec_info)

    def _run_hook(self, config: argparse.Namespace, context: Context, stage: str) -> None:
        key = (
            BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_PRE_HOOK
            if stage == "pre"
            else BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_POST_HOOK
        )
        hook_cmd = get_config_value_by_cmd_line_option(config, key)
        if not hook_cmd:
            return
        logger.info(f"Running {stage}-hook '{hook_cmd}'")
        cluster_info = cast(ClusterInfo, self._cluster_info)
        env = os.environ.copy()
        env["KUBECONFIG"] = os.path.abspath(cluster_info.kube_config_path)
        env["ATS_HOOK_STAGE"] = stage
        env["ATS_TEST_TYPE"] = str(self.test_provided)
        env["ATS_CHART_PATH"] = config.chart_file
        env["ATS_CHART_VERSION"] = context[CONTEXT_KEY_CHART_YAML]["version"]
        deploy_namespace = get_config_value_by_cmd_line_option(
            config, BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_NAMESPACE
        )
        if deploy_namespace:
            env["ATS_RELEASE_NAMESPACE"] = deploy_namespace
        release_name = context.get(CONTEXT_KEY_RELEASE_NAME)
        if release_name:
            env["ATS_RELEASE_NAME"] = str(release_name)
        run_res = run_and_log([hook_cmd], env=env)  # nosec
        if run_res.returncode != 0:
            raise ATSTestError(f"{stage.capitalize()}-hook '{hook_cmd}' failed with exit code {run_res.returncode}")

    def _ensure_cluster_prerequisites(self, kube_config_path: str) -> None:
        logger.info(f"Applying cluster CRDs from {self._CRD_DIR}")
        run_res = run_and_log(
            ["kubectl", f"--kubeconfig={kube_config_path}", "apply", "--server-side", "-f", self._CRD_DIR],
            capture_output=True,
        )  # nosec
        if run_res.returncode != 0:
            raise ATSTestError(
                f"Bootstrapping CRDs on the target cluster failed:\n{run_res.stderr.decode(errors='replace')}"
            )
        logger.info("Cluster CRDs bootstrapped and ready.")

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
        config_parser.add_argument(
            self._config_gitops_engines_attribute_name,
            required=False,
            default="auto",
            help=f"GitOps engine(s) to test the bundle chart under for {self.test_provided} tests:"
            f" 'auto' (detect from the rendered chart), 'helm' (force plain Helm deploy),"
            f" or a comma-separated list of engines ('flux', 'argo').",
        )
        for engine in GitOpsEngine:
            config_parser.add_argument(
                self._config_gitops_values_attribute_name(engine),
                required=False,
                help=f"Path to a values overlay stacked on the app config file when deploying the bundle"
                f" chart for the '{engine.value}' engine in {self.test_provided} tests."
                f" Defaults to 'ci/gitops-values-{engine.value}.yaml' when that file exists.",
            )
        config_parser.add_argument(
            self._config_gitops_bundle_ready_timeout_attribute_name,
            required=False,
            default="10m",
            help=f"How long to wait for the GitOps resources emitted by the bundle chart to become"
            f" ready (and to drain on teardown) in {self.test_provided} tests.",
        )

    def pre_run(self, config: argparse.Namespace) -> None:
        self._assert_binary_present_in_path(_HELM_BIN)
        self._assert_binary_present_in_path(_KUBECTL_BIN)

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
        self._validate_gitops_config(config)
        self._test_executor.validate(config, self.name)

    def _validate_gitops_config(self, config: argparse.Namespace) -> None:
        engines_option = get_config_value_by_cmd_line_option(config, self._config_gitops_engines_attribute_name)
        try:
            self._configured_gitops_engines = parse_engines_option(engines_option)
        except ValueError as e:
            raise ConfigError(self._config_gitops_engines_attribute_name, str(e))
        if self._configured_gitops_engines and GitOpsEngine.ARGO in self._configured_gitops_engines:
            raise ConfigError(
                self._config_gitops_engines_attribute_name,
                "The 'argo' engine is not implemented yet; use 'flux', 'helm' or 'auto'.",
            )
        for engine in GitOpsEngine:
            overlay_path = get_config_value_by_cmd_line_option(
                config, self._config_gitops_values_attribute_name(engine)
            )
            if overlay_path and not os.path.isfile(overlay_path):
                raise ConfigError(
                    self._config_gitops_values_attribute_name(engine),
                    f"GitOps values overlay '{overlay_path}' for engine '{engine.value}' doesn't exist.",
                )

    def run(self, config: argparse.Namespace, context: Context) -> None:
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

        if not self._cluster_info.app_platform_ready:
            self._ensure_cluster_prerequisites(self._cluster_info.kube_config_path)
            self._cluster_info.app_platform_ready = True

        gitops_engines = self._resolve_gitops_engines(config)
        if gitops_engines:
            logger.info(f"GitOps engine matrix for this scenario: {[e.value for e in gitops_engines]}.")

        try:
            if (
                not get_config_value_by_cmd_line_option(
                    config,
                    BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_SKIP_DEPLOY_APP,
                )
                and not self._skip_app_deploy
            ):
                self._deploy_tested_chart_as_app(config, context)
            self._run_hook(config, context, "pre")
            self.run_tests(config, context)
            self._run_hook(config, context, "post")
        except Exception as e:
            self._collect_failure_diagnostics(config, context)
            raise ATSTestError(f"Application test run failed: {e}") from e
        finally:
            # honor --app-tests-skip-app-delete; both delete helpers no-op when nothing was deployed
            if not get_config_value_by_cmd_line_option(
                config,
                BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_SKIP_DELETE_APP,
            ):
                self._delete_release(config, context)

    def _resolve_gitops_engines(self, config: argparse.Namespace) -> List[GitOpsEngine]:
        if self._configured_gitops_engines is not None:
            return self._configured_gitops_engines
        app_config_file_path = get_config_value_by_cmd_line_option(
            config,
            BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_CONFIG_FILE,
        )
        values_paths = [app_config_file_path] if app_config_file_path else []
        return detect_engines(config.chart_file, values_paths)

    def _deploy_tested_chart_as_app(self, config: argparse.Namespace, context: Context) -> None:
        release_name = context[CONTEXT_KEY_CHART_YAML]["name"]
        deploy_namespace = get_config_value_by_cmd_line_option(
            config,
            BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_NAMESPACE,
        )
        app_config_file_path = get_config_value_by_cmd_line_option(
            config,
            BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_CONFIG_FILE,
        )
        self._helm_deploy(release_name, config.chart_file, deploy_namespace, app_config_file_path)
        context[CONTEXT_KEY_RELEASE_NAME] = release_name

    def _helm_deploy(
        self,
        release_name: str,
        chart_file: str,
        deploy_namespace: str,
        app_config_file_path: Optional[str],
    ) -> None:
        # Giant Swarm charts may ship PolicyException resources in the policy-exceptions namespace;
        # ensure it exists so the install does not fail on a cluster that lacks it.
        logger.info("Ensuring namespace 'policy-exceptions'.")
        ensure_namespace_exists(self._kube_client, "policy-exceptions")

        args = [
            _HELM_BIN,
            "upgrade",
            "--install",
            release_name,
            chart_file,
            "--namespace",
            deploy_namespace,
            "--create-namespace",
            "--reset-values",
            "--wait",
            "--timeout",
            _HELM_DEPLOY_TIMEOUT,
        ]
        if app_config_file_path:
            args += ["--values", app_config_file_path]
        logger.info(f"Installing chart as Helm release '{release_name}' into namespace '{deploy_namespace}'.")
        run_res = run_and_log(args, env=self._helm_env())  # nosec, chart file is the user's responsibility
        if run_res.returncode != 0:
            raise ATSTestError(f"Installing Helm release '{release_name}' failed")

    def _collect_failure_diagnostics(self, config: argparse.Namespace, context: Context) -> None:
        """Collect cluster diagnostics after a test failure, before cleanup destroys the evidence."""
        if self._kube_client is None:
            logger.warning("No kube client available, skipping diagnostics collection.")
            return

        deploy_namespace = get_config_value_by_cmd_line_option(
            config,
            BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_NAMESPACE,
        )
        release_name = context.get(
            CONTEXT_KEY_RELEASE_NAME, context.get(CONTEXT_KEY_CHART_YAML, {}).get("name", "unknown")
        )
        separator = "=" * 80

        logger.error(f"{separator}")
        logger.error(f"FAILURE DIAGNOSTICS for release '{release_name}' in namespace '{deploy_namespace}'")
        logger.error(f"{separator}")

        try:
            # Pod status and logs
            pods = list(pykube.Pod.objects(self._kube_client).filter(namespace=deploy_namespace))
            if pods:
                logger.error(f"--- Pods in namespace '{deploy_namespace}' ---")
                for pod in pods:
                    phase = pod.obj.get("status", {}).get("phase", "Unknown")
                    logger.error(f"  {pod.name}: {phase}")

            # Full spec/status for non-Running pods (shows conditions, events, image pull errors)
            for pod in pods:
                if pod.obj.get("status", {}).get("phase") != "Running":
                    logger.error(f"--- Describe pod '{pod.name}' ---")
                    logger.error(yaml.dump(pod.obj))

            # Container logs from all pods in the namespace
            for pod in pods:
                all_containers = [c["name"] for c in pod.obj.get("spec", {}).get("containers", [])]
                all_containers += [c["name"] for c in pod.obj.get("spec", {}).get("initContainers", [])]
                for container in all_containers:
                    try:
                        logs = pod.logs(container=container, tail_lines=100)
                        if logs:
                            logger.error(f"--- Logs from pod '{pod.name}' container '{container}' (last 100 lines) ---")
                            logger.error(logs)
                    except Exception as ex:
                        logger.warning(f"Failed to get logs for pod '{pod.name}' container '{container}': {ex}")
                    try:
                        prev_logs = pod.logs(container=container, previous=True, tail_lines=50)
                        if prev_logs:
                            logger.error(
                                f"--- Previous logs from pod '{pod.name}' container '{container}' (last 50 lines) ---"
                            )
                            logger.error(prev_logs)
                    except Exception:
                        pass  # Previous logs don't exist if the container hasn't restarted

            # Events in the app namespace
            events = sorted(
                pykube.Event.objects(self._kube_client).filter(namespace=deploy_namespace),
                key=lambda e: e.obj.get("lastTimestamp") or "",
            )
            if events:
                logger.error(f"--- Events in namespace '{deploy_namespace}' ---")
                for event in events:
                    logger.error(
                        f"  {event.obj.get('lastTimestamp', '')} {event.obj.get('type', '')} "
                        f"{event.obj.get('reason', '')} {event.obj.get('message', '')}"
                    )

            # Helm release status
            helm_env = self._helm_env()
            for helm_cmd, label in [
                ([_HELM_BIN, "status", release_name, "-n", deploy_namespace], "helm status"),
                ([_HELM_BIN, "get", "values", release_name, "-n", deploy_namespace], "helm get values"),
            ]:
                res = run_and_log(helm_cmd, env=helm_env)  # nosec
                if res.returncode == 0 and res.stdout:
                    logger.error(f"--- {label} '{release_name}' ---")
                    logger.error(res.stdout)

            # Deployments status
            deployments = list(pykube.Deployment.objects(self._kube_client).filter(namespace=deploy_namespace))
            if deployments:
                logger.error(f"--- Deployments in namespace '{deploy_namespace}' ---")
                for deployment in deployments:
                    logger.error(f"  {deployment.name}: {yaml.dump(deployment.obj.get('status', {}))}")

            # Node status (useful for Kind clusters with resource issues)
            nodes = list(pykube.Node.objects(self._kube_client).all())
            if nodes:
                logger.error("--- Cluster nodes ---")
                for node in nodes:
                    conditions = node.obj.get("status", {}).get("conditions", [])
                    ready_cond = next((c for c in conditions if c.get("type") == "Ready"), None)
                    ready_status = ready_cond.get("status", "Unknown") if ready_cond else "Unknown"
                    logger.error(f"  {node.name}: Ready={ready_status}")

        except Exception as ex:
            logger.warning(f"Failed to collect diagnostics: {ex}")

        logger.error(f"{separator}")
        logger.error("END OF FAILURE DIAGNOSTICS")
        logger.error(f"{separator}")

    def _delete_release(self, config: argparse.Namespace, context: Context) -> None:
        release_name = context.get(CONTEXT_KEY_RELEASE_NAME)
        if release_name is None:
            return
        deploy_namespace = get_config_value_by_cmd_line_option(
            config,
            BaseTestScenariosFilteringPipeline.KEY_CONFIG_OPTION_DEPLOY_NAMESPACE,
        )
        logger.info(f"Uninstalling Helm release '{release_name}' from namespace '{deploy_namespace}'.")
        run_res = run_and_log(
            [_HELM_BIN, "uninstall", release_name, "--namespace", deploy_namespace, "--wait"],
            env=self._helm_env(),
        )  # nosec
        if run_res.returncode != 0:
            logger.warning(f"Uninstalling Helm release '{release_name}' failed; continuing.")

    def _helm_env(self) -> Dict[str, str]:
        kube_config_path = cast(ClusterInfo, self._cluster_info).kube_config_path
        return {**os.environ, "KUBECONFIG": kube_config_path}


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
