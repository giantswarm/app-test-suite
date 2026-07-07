import os
import unittest.mock
from pathlib import Path
from typing import Callable, Type, cast

import app_test_suite.gitops

import pytest
from pytest_mock import MockerFixture
from step_exec_lib.errors import ConfigError
from app_test_suite.cluster_providers.cluster_provider import ClusterType
from app_test_suite.errors import ATSTestError
from app_test_suite.steps.base import CONTEXT_KEY_CHART_YAML, TestExecutor
from step_exec_lib.types import StepType
from app_test_suite.steps.executors.gotest import GotestExecutor
from app_test_suite.steps.executors.pytest import PytestExecutor
from app_test_suite.steps.scenarios.simple import (
    SimpleTestScenario,
    SmokeTestScenario,
    FunctionalTestScenario,
    CONTEXT_KEY_RELEASE_NAME,
)
from tests.helpers import (
    assert_helm_deployed,
    assert_helm_uninstalled,
    assert_cluster_prerequisites_ready,
    assert_cluster_connection_created,
    get_base_config,
    get_run_and_log_result_mock,
    patch_base_test_runner,
    get_mock_cluster_manager,
    MOCK_APP_NAME,
    MOCK_APP_NS,
    MOCK_CHART_FILE_NAME,
    MOCK_CHART_VERSION,
    MOCK_KUBE_CONFIG_PATH,
    MOCK_APP_DEPLOY_NS,
)
from tests.scenarios.executors.gotest import patch_gotest_test_runner, assert_run_gotest
from tests.scenarios.executors.pytest import (
    patch_pytest_test_runner,
    assert_prepare_and_run_pytest,
)

REAL_CHART_APP_NAME = MOCK_APP_NAME
REAL_CHART_VERSION = MOCK_CHART_VERSION
REAL_CHART_FILE = MOCK_CHART_FILE_NAME
REAL_CHART_RELEASE_NAME = MOCK_APP_NAME


@pytest.mark.parametrize(
    "scenario_type,test_executor,patcher,asserter",
    [
        (
            SmokeTestScenario,
            PytestExecutor(),
            patch_pytest_test_runner,
            assert_prepare_and_run_pytest,
        ),
        (
            SmokeTestScenario,
            GotestExecutor(),
            patch_gotest_test_runner,
            assert_run_gotest,
        ),
        (
            FunctionalTestScenario,
            PytestExecutor(),
            patch_pytest_test_runner,
            assert_prepare_and_run_pytest,
        ),
        (
            FunctionalTestScenario,
            GotestExecutor(),
            patch_gotest_test_runner,
            assert_run_gotest,
        ),
    ],
    ids=[
        "smoke-pytest",
        "smoke-gotest",
        "functional-pytest",
        "functional-gotest",
    ],
)
def test_simple_runner_run(
    mocker: MockerFixture,
    scenario_type: Type[SimpleTestScenario],
    test_executor: TestExecutor,
    patcher: Callable[[MockerFixture, unittest.mock.Mock], None],
    asserter: Callable[[StepType, str, str, str], None],
) -> None:
    mock_cluster_manager = get_mock_cluster_manager(mocker)
    run_and_log_call_result_mock = get_run_and_log_result_mock(mocker)

    patch_base_test_runner(mocker, run_and_log_call_result_mock, MOCK_APP_NAME, MOCK_APP_NS)
    patcher(mocker, run_and_log_call_result_mock)

    config = get_base_config(mocker)
    context = {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_CHART_VERSION}}
    runner = scenario_type(mock_cluster_manager, test_executor)
    runner.run(config, context)

    assert_cluster_connection_created(MOCK_KUBE_CONFIG_PATH)
    assert_cluster_prerequisites_ready(MOCK_KUBE_CONFIG_PATH)
    assert_helm_deployed(MOCK_APP_NAME, config.chart_file, MOCK_APP_DEPLOY_NS, MOCK_KUBE_CONFIG_PATH)
    asserter(
        runner.test_provided,
        MOCK_KUBE_CONFIG_PATH,
        config.chart_file,
        MOCK_CHART_VERSION,
    )
    assert_helm_uninstalled(MOCK_APP_NAME, MOCK_APP_DEPLOY_NS, MOCK_KUBE_CONFIG_PATH)


def _make_smoke_runner(mocker: MockerFixture) -> SmokeTestScenario:
    run_and_log_res = get_run_and_log_result_mock(mocker)
    patch_base_test_runner(mocker, run_and_log_res)
    patch_pytest_test_runner(mocker, run_and_log_res)
    return SmokeTestScenario(get_mock_cluster_manager(mocker), PytestExecutor())


def test_pre_and_post_hook_called_with_correct_env(mocker: MockerFixture) -> None:
    runner = _make_smoke_runner(mocker)
    config = get_base_config(mocker)
    config.app_tests_pre_hook = "pre-hook.sh"
    config.app_tests_post_hook = "post-hook.sh"
    context = {
        CONTEXT_KEY_CHART_YAML: {"name": REAL_CHART_APP_NAME, "version": REAL_CHART_VERSION},
        CONTEXT_KEY_RELEASE_NAME: REAL_CHART_APP_NAME,
    }

    runner.run(config, context)

    import app_test_suite.steps.scenarios.simple as simple_mod

    calls = cast(unittest.mock.Mock, simple_mod.run_and_log).call_args_list
    hook_calls = [c for c in calls if c.args[0][0] in ("pre-hook.sh", "post-hook.sh")]
    assert len(hook_calls) == 2, f"expected 2 hook calls, got {len(hook_calls)}"

    pre_call = next(c for c in hook_calls if c.args[0][0] == "pre-hook.sh")
    post_call = next(c for c in hook_calls if c.args[0][0] == "post-hook.sh")

    for call, stage in ((pre_call, "pre"), (post_call, "post")):
        env = call.kwargs["env"]
        assert env["ATS_HOOK_STAGE"] == stage
        assert env["ATS_TEST_TYPE"] == "smoke"
        assert env["ATS_CHART_VERSION"] == REAL_CHART_VERSION
        assert env["ATS_CHART_PATH"] == REAL_CHART_FILE
        assert env["KUBECONFIG"] == os.path.abspath(MOCK_KUBE_CONFIG_PATH)
        assert env["ATS_RELEASE_NAMESPACE"] == MOCK_APP_DEPLOY_NS
        assert env["ATS_RELEASE_NAME"] == REAL_CHART_APP_NAME


def test_pre_hook_skipped_when_not_configured(mocker: MockerFixture) -> None:
    runner = _make_smoke_runner(mocker)
    config = get_base_config(mocker)
    context = {CONTEXT_KEY_CHART_YAML: {"name": REAL_CHART_APP_NAME, "version": REAL_CHART_VERSION}}

    runner.run(config, context)

    import app_test_suite.steps.scenarios.simple as simple_mod

    calls = cast(unittest.mock.Mock, simple_mod.run_and_log).call_args_list
    assert not any(c.args[0][0] in ("pre-hook.sh", "post-hook.sh") for c in calls)


def test_pre_hook_failure_raises(mocker: MockerFixture) -> None:
    run_and_log_res = get_run_and_log_result_mock(mocker)
    patch_base_test_runner(mocker, run_and_log_res)
    patch_pytest_test_runner(mocker, run_and_log_res)

    fail_res = mocker.Mock()
    type(fail_res).returncode = mocker.PropertyMock(return_value=1)

    def side_effect(args: list[str], **kwargs: object) -> unittest.mock.Mock:
        if args[0] == "fail-hook.sh":
            return fail_res
        return run_and_log_res

    mocker.patch("app_test_suite.steps.scenarios.simple.run_and_log", side_effect=side_effect)

    runner = SmokeTestScenario(get_mock_cluster_manager(mocker), PytestExecutor())
    config = get_base_config(mocker)
    config.app_tests_pre_hook = "fail-hook.sh"
    context = {CONTEXT_KEY_CHART_YAML: {"name": REAL_CHART_APP_NAME, "version": REAL_CHART_VERSION}}

    with pytest.raises(ATSTestError, match="Pre-hook"):
        runner.run(config, context)


def test_gitops_engines_config_validation_rejects_unknown_engine(mocker: MockerFixture) -> None:
    runner = _make_smoke_runner(mocker)
    config = get_base_config(mocker)
    config.smoke_tests_gitops_engines = "bogus"

    with pytest.raises(ConfigError, match="Unknown GitOps engine 'bogus'"):
        runner._validate_gitops_config(config)


def test_gitops_values_overlay_must_exist_when_configured(mocker: MockerFixture) -> None:
    runner = _make_smoke_runner(mocker)
    config = get_base_config(mocker)
    config.smoke_tests_gitops_engines = "flux"
    config.smoke_tests_gitops_values_flux = "nonexistent-overlay.yaml"

    with pytest.raises(ConfigError, match="doesn't exist"):
        runner._validate_gitops_config(config)


def test_pre_run_resolves_engines_before_any_cluster(mocker: MockerFixture) -> None:
    runner = _make_smoke_runner(mocker)
    mocker.patch.object(runner._test_executor, "validate")
    cluster_manager = cast(unittest.mock.Mock, runner._cluster_manager)
    cluster_manager.get_registered_cluster_types.return_value = [ClusterType("mock")]
    config = get_base_config(mocker)
    config.smoke_tests_cluster_type = "mock"
    config.smoke_tests_cluster_config_file = ""

    runner.pre_run(config)

    # auto-detection (a local `helm template`) ran during validation, so a render failure would
    # abort here instead of after a cluster spin-up in run()
    cast(unittest.mock.Mock, app_test_suite.gitops.run_and_log).assert_any_call(
        ["helm", "template", MOCK_CHART_FILE_NAME], capture_output=True
    )
    assert runner._resolved_gitops_engines == []
    cluster_manager.get_cluster_for_test_type.assert_not_called()


def test_run_detects_gitops_engines_when_auto(mocker: MockerFixture) -> None:
    runner = _make_smoke_runner(mocker)
    config = get_base_config(mocker)
    context = {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_CHART_VERSION}}

    runner.run(config, context)

    cast(unittest.mock.Mock, app_test_suite.gitops.run_and_log).assert_any_call(
        ["helm", "template", MOCK_CHART_FILE_NAME], capture_output=True
    )


def test_run_skips_gitops_detection_when_engines_explicit(mocker: MockerFixture) -> None:
    runner = _make_smoke_runner(mocker)
    config = get_base_config(mocker)
    config.smoke_tests_gitops_engines = "helm"
    runner._validate_gitops_config(config)
    context = {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_CHART_VERSION}}

    runner.run(config, context)

    cast(unittest.mock.Mock, app_test_suite.gitops.run_and_log).assert_not_called()


def _patch_gitops_leg(mocker: MockerFixture) -> dict:
    return {
        "install_engine": mocker.patch("app_test_suite.steps.scenarios.simple.install_engine"),
        "wait_for_bundle_ready": mocker.patch("app_test_suite.steps.scenarios.simple.wait_for_bundle_ready"),
        "wait_for_bundle_drained": mocker.patch("app_test_suite.steps.scenarios.simple.wait_for_bundle_drained"),
    }


@pytest.mark.parametrize(
    "engine,manifest_default",
    [
        ("flux", "/etc/ats/gitops/flux.yaml"),
        ("argo", "/etc/ats/gitops/argo.yaml"),
    ],
    ids=["flux", "argo"],
)
def test_engine_leg_installs_engine_and_waits_for_bundle(
    mocker: MockerFixture, tmp_path: Path, engine: str, manifest_default: str
) -> None:
    runner = _make_smoke_runner(mocker)
    gitops_mocks = _patch_gitops_leg(mocker)
    overlay = tmp_path / f"gitops-values-{engine}.yaml"
    overlay.write_text(f"gitops:\n  engine: {engine}\n")
    config = get_base_config(mocker)
    config.smoke_tests_gitops_engines = engine
    setattr(config, f"smoke_tests_gitops_values_{engine}", str(overlay))
    runner._validate_gitops_config(config)
    context = {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_CHART_VERSION}}

    runner.run(config, context)

    engine_namespace = f"{MOCK_APP_DEPLOY_NS}-{engine}"
    gitops_mocks["install_engine"].assert_called_once()
    assert gitops_mocks["install_engine"].call_args.args[0].value == engine
    assert gitops_mocks["install_engine"].call_args.args[2] == manifest_default
    assert_helm_deployed(
        MOCK_APP_NAME, config.chart_file, engine_namespace, MOCK_KUBE_CONFIG_PATH, values_file=str(overlay)
    )
    gitops_mocks["wait_for_bundle_ready"].assert_called_once_with(MOCK_KUBE_CONFIG_PATH, mocker.ANY, 600)
    assert_helm_uninstalled(MOCK_APP_NAME, engine_namespace, MOCK_KUBE_CONFIG_PATH)
    gitops_mocks["wait_for_bundle_drained"].assert_called_once_with(
        MOCK_KUBE_CONFIG_PATH, mocker.ANY, engine_namespace, 600
    )


@pytest.mark.parametrize("engine", ["flux", "argo"])
def test_engine_leg_skips_engine_install_when_cluster_has_it(mocker: MockerFixture, engine: str) -> None:
    runner = _make_smoke_runner(mocker)
    gitops_mocks = _patch_gitops_leg(mocker)
    cluster_info = cast(unittest.mock.Mock, runner._cluster_manager).get_cluster_for_test_type.return_value
    cluster_info.gitops_engines_ready.add(engine)
    config = get_base_config(mocker)
    config.smoke_tests_gitops_engines = engine
    runner._validate_gitops_config(config)
    context = {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_CHART_VERSION}}

    runner.run(config, context)

    gitops_mocks["install_engine"].assert_not_called()
    gitops_mocks["wait_for_bundle_ready"].assert_called_once()


def test_detected_argo_engine_runs_a_leg(mocker: MockerFixture) -> None:
    runner = _make_smoke_runner(mocker)
    gitops_mocks = _patch_gitops_leg(mocker)
    mocker.patch(
        "app_test_suite.steps.scenarios.simple.detect_engines",
        return_value=[app_test_suite.gitops.GitOpsEngine.ARGO],
    )
    config = get_base_config(mocker)
    context = {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_CHART_VERSION}}

    runner.run(config, context)

    gitops_mocks["install_engine"].assert_called_once()
    assert gitops_mocks["install_engine"].call_args.args[0] is app_test_suite.gitops.GitOpsEngine.ARGO
    assert_helm_deployed(MOCK_APP_NAME, config.chart_file, f"{MOCK_APP_DEPLOY_NS}-argo", MOCK_KUBE_CONFIG_PATH)


def test_plain_path_untouched_by_gitops_machinery(mocker: MockerFixture) -> None:
    runner = _make_smoke_runner(mocker)
    gitops_mocks = _patch_gitops_leg(mocker)
    config = get_base_config(mocker)
    config.smoke_tests_gitops_engines = "helm"
    runner._validate_gitops_config(config)
    context = {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_CHART_VERSION}}

    runner.run(config, context)

    for mock in gitops_mocks.values():
        mock.assert_not_called()
    assert_helm_deployed(MOCK_APP_NAME, config.chart_file, MOCK_APP_DEPLOY_NS, MOCK_KUBE_CONFIG_PATH)
    assert_helm_uninstalled(MOCK_APP_NAME, MOCK_APP_DEPLOY_NS, MOCK_KUBE_CONFIG_PATH)


def test_flux_leg_drains_after_a_failed_run(mocker: MockerFixture) -> None:
    run_and_log_res = get_run_and_log_result_mock(mocker)
    patch_base_test_runner(mocker, run_and_log_res)
    patch_pytest_test_runner(mocker, run_and_log_res)

    fail_res = mocker.Mock()
    type(fail_res).returncode = mocker.PropertyMock(return_value=1)

    def side_effect(args: list[str], **kwargs: object) -> unittest.mock.Mock:
        if args[0] == "fail-hook.sh":
            return fail_res
        return run_and_log_res

    mocker.patch("app_test_suite.steps.scenarios.simple.run_and_log", side_effect=side_effect)
    gitops_mocks = _patch_gitops_leg(mocker)

    runner = SmokeTestScenario(get_mock_cluster_manager(mocker), PytestExecutor())
    config = get_base_config(mocker)
    config.smoke_tests_gitops_engines = "flux"
    config.app_tests_pre_hook = "fail-hook.sh"
    runner._validate_gitops_config(config)
    context = {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": MOCK_CHART_VERSION}}

    with pytest.raises(ATSTestError, match="Pre-hook"):
        runner.run(config, context)

    # the leg deployed the release before failing, so teardown must still drain the engine namespace
    gitops_mocks["wait_for_bundle_ready"].assert_called_once()
    assert_helm_uninstalled(MOCK_APP_NAME, f"{MOCK_APP_DEPLOY_NS}-flux", MOCK_KUBE_CONFIG_PATH)
    gitops_mocks["wait_for_bundle_drained"].assert_called_once()


def test_bundle_ready_timeout_option_is_parsed(mocker: MockerFixture) -> None:
    runner = _make_smoke_runner(mocker)
    config = get_base_config(mocker)
    config.smoke_tests_gitops_bundle_ready_timeout = "3m"

    runner._validate_gitops_config(config)

    assert runner._gitops_bundle_ready_timeout_sec == 180


def test_bundle_ready_timeout_option_rejects_garbage(mocker: MockerFixture) -> None:
    runner = _make_smoke_runner(mocker)
    config = get_base_config(mocker)
    config.smoke_tests_gitops_bundle_ready_timeout = "soon"

    with pytest.raises(ConfigError, match="Invalid timeout"):
        runner._validate_gitops_config(config)
