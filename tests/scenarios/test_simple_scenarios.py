import os
import unittest.mock
from typing import Callable, Type, cast

import pytest
from pytest_mock import MockerFixture
from app_test_suite.errors import ATSTestError
from app_test_suite.steps.base import CONTEXT_KEY_CHART_YAML, TestExecutor
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
        assert env["ATS_DEPLOY_NAMESPACE"] == MOCK_APP_DEPLOY_NS
        assert env["ATS_APP_RELEASE_NAME"] == REAL_CHART_APP_NAME


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

    def side_effect(args, **kwargs):
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
