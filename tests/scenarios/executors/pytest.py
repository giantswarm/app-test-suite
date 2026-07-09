import os
import unittest.mock
from typing import cast

from pytest_mock import MockerFixture
from step_exec_lib.types import StepType

import app_test_suite
import app_test_suite.steps.executors.pytest
from tests.helpers import MOCK_KUBE_VERSION, MOCK_APP_NAME, MOCK_APP_DEPLOY_NS


def assert_run_pytest(
    test_provided: StepType, kube_config_path: str, chart_file: str, app_version: str, test_extra_info: str = ""
) -> None:
    # `append_to_sys_env` is enabled by default, so the ambient environment forms the base ...
    env_vars = dict(os.environ)

    # ... and every ATS-derived value is layered on top (see TestExecutor.get_test_info_env_variables),
    # so they override any colliding system env var.
    env_vars.update(
        {
            "ATS_CHART_VERSION": app_version,
            "ATS_CHART_PATH": chart_file,
            "ATS_CLUSTER_TYPE": "mock",
            "ATS_CLUSTER_VERSION": MOCK_KUBE_VERSION,
            "ATS_TEST_TYPE": test_provided,
            "ATS_TEST_DIR": "",
            "KUBECONFIG": kube_config_path,
            "ATS_APP_CONFIG_FILE_PATH": "",
            "ATS_RELEASE_NAME": MOCK_APP_NAME,
            "ATS_RELEASE_NAMESPACE": MOCK_APP_DEPLOY_NS,
        }
    )

    expected_args = [
        "uv",
        "run",
        "pytest",
        "-m",
        test_provided,
        "--log-cli-level",
        "info",
        f"--junitxml=test_results_{test_provided}.xml",
    ]

    if test_extra_info:
        env_vars.update({k.upper(): v for k, v in [p.split("=") for p in test_extra_info.split(",")]})

    cast(unittest.mock.Mock, app_test_suite.steps.executors.pytest.run_and_log).assert_any_call(
        expected_args, cwd="", env=env_vars
    )


def assert_prepare_pytest_test_environment() -> None:
    run_and_log_mock = cast(unittest.mock.Mock, app_test_suite.steps.executors.pytest.run_and_log)
    assert run_and_log_mock.call_args_list[0].args[0] == [
        "uv",
        "sync",
    ]


def assert_prepare_and_run_pytest(
    test_provided: StepType, kube_config_path: str, chart_file: str, app_version: str
) -> None:
    assert_prepare_pytest_test_environment()
    assert_run_pytest(test_provided, kube_config_path, chart_file, app_version)


def patch_pytest_test_runner(mocker: MockerFixture, run_and_log_res: unittest.mock.Mock) -> None:
    mocker.patch("app_test_suite.steps.executors.pytest.run_and_log", return_value=run_and_log_res)
