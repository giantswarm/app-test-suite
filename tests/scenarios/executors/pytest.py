import os
import unittest.mock
from typing import cast

from pytest_mock import MockerFixture
from step_exec_lib.types import StepType

import app_test_suite
import app_test_suite.steps.executors.pytest
from tests.helpers import MOCK_KUBE_VERSION


def assert_run_pytest(
    test_provided: StepType, kube_config_path: str, chart_file: str, app_version: str, test_extra_info: str = ""
) -> None:
    env_vars = {
        "ATS_APP_CONFIG_FILE_PATH": "",
        "ATS_CHART_VERSION": app_version,
        "ATS_CHART_PATH": chart_file,
        "ATS_CLUSTER_TYPE": "mock",
        "ATS_CLUSTER_VERSION": MOCK_KUBE_VERSION,
        "ATS_KUBE_CONFIG_PATH": kube_config_path,
        "ATS_TEST_TYPE": test_provided,
        "ATS_TEST_DIR": "",
        "CGO_ENABLED": "0",
        "GOPATH": os.getenv("GOPATH", ""),
        "HOME": os.getenv("HOME", ""),
        "PATH": os.getenv("PATH", ""),
    }

    expected_args = [
        "pipenv",
        "run",
        "pytest",
        "--log-cli-level",
        "info",
        f"--junitxml=test_results_{test_provided}.xml",
    ]
    if test_extra_info:
        expected_args.append("--test-extra-info")
        expected_args.append(test_extra_info)
    cast(unittest.mock.Mock, app_test_suite.steps.executors.pytest.run_and_log).assert_any_call(
        expected_args, cwd="", env=env_vars
    )


def assert_prepare_pytest_test_environment() -> None:
    run_and_log_mock = cast(unittest.mock.Mock, app_test_suite.steps.executors.pytest.run_and_log)
    assert run_and_log_mock.call_args_list[0].args[0] == [
        "pipenv",
        "install",
        "--deploy",
    ]
    assert run_and_log_mock.call_args_list[1].args[0] == [
        "pipenv",
        "--venv",
    ]


def assert_prepare_and_run_pytest(
    test_provided: StepType, kube_config_path: str, chart_file: str, app_version: str
) -> None:
    assert_prepare_pytest_test_environment()
    assert_run_pytest(test_provided, kube_config_path, chart_file, app_version)


def patch_pytest_test_runner(mocker: MockerFixture, run_and_log_res: unittest.mock.Mock) -> None:
    mocker.patch("app_test_suite.steps.executors.pytest.run_and_log", return_value=run_and_log_res)
