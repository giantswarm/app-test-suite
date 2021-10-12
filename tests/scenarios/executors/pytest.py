import unittest.mock
from typing import cast

from pytest_mock import MockerFixture
from step_exec_lib.types import StepType

import app_test_suite
import app_test_suite.steps.pytest.pytest
from tests.helpers import MOCK_KUBE_CONFIG_PATH, MOCK_APP_VERSION


def assert_run_pytest(test_provided: StepType, kube_config_path: str, chart_file: str, app_version: str) -> None:
    cast(unittest.mock.Mock, app_test_suite.steps.pytest.pytest.run_and_log).assert_any_call(
        [
            "pipenv",
            "run",
            "pytest",
            "-m",
            test_provided,
            "--cluster-type",
            "mock",
            "--kube-config",
            kube_config_path,
            "--chart-path",
            chart_file,
            "--chart-version",
            app_version,
            "--chart-extra-info",
            "external_cluster_version=1.19.1",
            "--log-cli-level",
            "info",
            f"--junitxml=test_results_{test_provided}.xml",
        ],
        cwd="",
    )


def assert_prepare_pytest_test_environment() -> None:
    run_and_log_mock = cast(unittest.mock.Mock, app_test_suite.steps.pytest.pytest.run_and_log)
    assert run_and_log_mock.call_args_list[0].args[0] == [
        "pipenv",
        "install",
        "--deploy",
    ]
    assert run_and_log_mock.call_args_list[1].args[0] == [
        "pipenv",
        "--venv",
    ]


def assert_prepare_and_run_pytest(test_provided: StepType, chart_file: str) -> None:
    assert_prepare_pytest_test_environment()
    assert_run_pytest(test_provided, MOCK_KUBE_CONFIG_PATH, chart_file, MOCK_APP_VERSION)


def patch_pytest_test_runner(mocker: MockerFixture, run_and_log_res: unittest.mock.Mock) -> None:
    mocker.patch("app_test_suite.steps.pytest.pytest.run_and_log", return_value=run_and_log_res)
