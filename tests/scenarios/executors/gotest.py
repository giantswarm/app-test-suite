import os
import unittest.mock
from typing import cast

from pytest_mock import MockerFixture
from step_exec_lib.types import StepType

import app_test_suite
import app_test_suite.steps.executors.gotest
from tests.helpers import MOCK_KUBE_VERSION


def assert_run_gotest(
    test_provided: StepType,
    kube_config_path: str,
    chart_file: str,
    app_version: str,
    test_extra_info: str = "",
) -> None:
    env_vars = {
        "KUBECONFIG": kube_config_path,
        "ATS_APP_CONFIG_FILE_PATH": "",
        "ATS_CHART_VERSION": app_version,
        "ATS_CHART_PATH": chart_file,
        "ATS_CLUSTER_TYPE": "mock",
        "ATS_CLUSTER_VERSION": MOCK_KUBE_VERSION,
        "ATS_TEST_TYPE": test_provided,
        "ATS_TEST_DIR": "",
        "CGO_ENABLED": "0",
    }

    # Because `append_to_sys_env` parameter is enabled by default
    env_vars.update(os.environ)

    if test_extra_info:
        env_vars.update(
            {
                k.upper(): v
                for k, v in [p.split("=") for p in test_extra_info.split(",")]
            }
        )

    cast(
        unittest.mock.Mock, app_test_suite.steps.executors.gotest.run_and_handle_error
    ).assert_any_call(
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


def patch_gotest_test_runner(
    mocker: MockerFixture, run_and_handle_error_res: unittest.mock.Mock
) -> None:
    mocker.patch(
        "app_test_suite.steps.executors.gotest.run_and_handle_error",
        return_value=run_and_handle_error_res,
    )
