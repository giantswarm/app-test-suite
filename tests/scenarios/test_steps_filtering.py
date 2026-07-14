"""Regression tests for '--steps'/'--skip-steps' filtering (giantswarm/giantswarm#19871).

Chart info extraction must run for every step selection, otherwise scenario steps
crash on the missing 'chart_yaml' context entry when run with '--steps <type>'.
"""

import shutil
from pathlib import Path
from typing import List, Set

import pytest
import yaml
from pytest_mock import MockerFixture

from app_test_suite.steps.base import (
    CONTEXT_KEY_CHART_YAML,
    BaseTestScenariosFilteringPipeline,
    TestExecutor,
)
from app_test_suite.steps.scenarios.simple import FunctionalTestScenario, SmokeTestScenario
from step_exec_lib.types import Context
from tests.helpers import (
    MOCK_APP_NAME,
    MOCK_APP_NS,
    MOCK_CHART_VERSION,
    get_base_config,
    get_mock_cluster_manager,
    get_run_and_log_result_mock,
    patch_base_test_runner,
)


def _make_chart_archive(tmp_path: Path) -> str:
    chart_dir = tmp_path / "chart" / MOCK_APP_NAME
    chart_dir.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(yaml.dump({"name": MOCK_APP_NAME, "version": MOCK_CHART_VERSION}))
    return shutil.make_archive(str(tmp_path / f"{MOCK_APP_NAME}-{MOCK_CHART_VERSION}"), "gztar", tmp_path / "chart")


@pytest.mark.parametrize(
    "steps,skip_steps,expected_test_types",
    [
        (["all"], [], {"smoke", "functional"}),
        (["smoke"], [], {"smoke"}),
        (["functional"], [], {"functional"}),
        (["all"], ["functional"], {"smoke"}),
    ],
    ids=["all", "steps-smoke", "steps-functional", "skip-functional"],
)
def test_chart_info_extracted_for_any_steps_selection(
    mocker: MockerFixture,
    tmp_path: Path,
    steps: List[str],
    skip_steps: List[str],
    expected_test_types: Set[str],
) -> None:
    run_and_log_res = get_run_and_log_result_mock(mocker)
    patch_base_test_runner(mocker, run_and_log_res, MOCK_APP_NAME, MOCK_APP_NS)
    mocker.patch("app_test_suite.steps.scenarios.simple.SimpleTestScenario._assert_binary_present_in_path")

    mock_cluster_manager = get_mock_cluster_manager(mocker)
    test_executor = mocker.MagicMock(spec=TestExecutor)
    pipeline = BaseTestScenariosFilteringPipeline(
        [
            SmokeTestScenario(mock_cluster_manager, test_executor),
            FunctionalTestScenario(mock_cluster_manager, test_executor),
        ],
        mock_cluster_manager,
    )

    config = get_base_config(mocker)
    config.chart_file = _make_chart_archive(tmp_path)
    config.steps = steps
    config.skip_steps = skip_steps
    config.keep_going = False
    config.cluster_crds = "/etc/ats/crds"
    context: Context = {}

    pipeline.pre_run(config)
    pipeline.run(config, context)

    assert context[CONTEXT_KEY_CHART_YAML] == {"name": MOCK_APP_NAME, "version": MOCK_CHART_VERSION}
    exec_infos = [call.args[0] for call in test_executor.execute_test.call_args_list]
    assert {exec_info.test_type for exec_info in exec_infos} == expected_test_types
    assert all(exec_info.chart_ver == MOCK_CHART_VERSION for exec_info in exec_infos)
