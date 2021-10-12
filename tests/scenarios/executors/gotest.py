import os
import unittest.mock
from typing import cast

from pytest_mock import MockerFixture
from step_exec_lib.types import StepType

import app_test_suite
import app_test_suite.steps.gotest.gotest
from tests.helpers import MOCK_KUBE_VERSION, MOCK_KUBE_CONFIG_PATH, MOCK_APP_VERSION


def assert_run_gotest(test_provided: StepType, chart_file: str) -> None:
    env_vars = {
        "ATS_APP_CONFIG_FILE_PATH": "",
        "ATS_CHART_PATH": chart_file,
        "ATS_CHART_VERSION": MOCK_APP_VERSION,
        "ATS_CLUSTER_TYPE": "mock",
        "ATS_CLUSTER_VERSION": MOCK_KUBE_VERSION,
        "ATS_KUBE_CONFIG_PATH": MOCK_KUBE_CONFIG_PATH,
        "ATS_TEST_TYPE": test_provided,
        "ATS_TEST_DIR": "",
        "GOPATH": os.getenv("GOPATH", ""),
        "HOME": os.getenv("HOME", ""),
        "PATH": os.getenv("PATH", ""),
    }

    # Set env vars needed for Go.

    cast(unittest.mock.Mock, app_test_suite.steps.gotest.gotest.run_and_handle_error).assert_any_call(
        [
            "go",
            "test",
            "-v",
            f"-tags={test_provided}",
        ],
        "build constraints exclude all Go files",
        cwd="",
        env=env_vars,
    )


def patch_gotest_test_runner(mocker: MockerFixture, run_and_handle_error_res: unittest.mock.Mock) -> None:
    mocker.patch("app_test_suite.steps.gotest.gotest.run_and_handle_error", return_value=run_and_handle_error_res)
