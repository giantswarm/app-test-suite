"""Main module. Loads configuration and executes main control loops."""

import argparse
import logging
import os
import sys
from typing import List, Optional

import configargparse
from step_exec_lib.errors import ConfigError
from step_exec_lib.steps import BuildStepsFilteringPipeline, BuildStep, Runner
from step_exec_lib.types import STEP_ALL

from app_test_suite.config import (
    DEFAULT_TESTS_DIR,
    KEY_CFG_TESTS_DIR,
    KEY_CFG_STABLE_APP_URL,
    KEY_CFG_STABLE_APP_VERSION,
    KEY_CFG_STABLE_APP_CONFIG,
    KEY_CFG_UPGRADE_HOOK,
    KEY_CFG_STABLE_APP_FILE,
    KEY_CFG_UPGRADE_SAVE_METADATA,
)
from app_test_suite.steps.base import TestExecutor
from app_test_suite.steps.executors.gotest import GotestTestFilteringPipeline
from app_test_suite.steps.executors.pytest import PytestScenariosFilteringPipeline
from app_test_suite.steps.test_types import ALL_STEPS

TEST_EXECUTOR_AUTO = "auto"
TEST_EXECUTOR_PYTEST = "pytest"
TEST_EXECUTOR_GOTEST = "gotest"

ver = "v0.0.0-dev"
app_name = "app_test_suite"
logger = logging.getLogger(__name__)


def get_version() -> str:
    try:
        from .version import build_ver

        return build_ver
    except ImportError:
        return ver


def get_pipeline(test_executor: str) -> List[BuildStepsFilteringPipeline]:
    if test_executor == TEST_EXECUTOR_PYTEST:
        return [
            PytestScenariosFilteringPipeline(),
        ]
    elif test_executor == TEST_EXECUTOR_GOTEST:
        return [
            GotestTestFilteringPipeline(),
        ]
    else:
        raise ConfigError("test-executor", f"Unknown executor '{test_executor}'.")


def get_chart_file_from_argv() -> Optional[str]:
    """Best-effort extraction of the chart file path from the raw command line.

    The chart file option ('-c'/'--chart-file') is registered by the test pipeline, not on the
    global-only parser, so it isn't available when the pipeline still has to be selected. It's read
    straight from ``sys.argv`` instead.
    """
    for opt in ("-c", "--chart-file"):
        if opt in sys.argv:
            idx = sys.argv.index(opt)
            if idx + 1 < len(sys.argv):
                return sys.argv[idx + 1]
    return None


def detect_test_executor(tests_dir: str, chart_file: Optional[str]) -> str:
    """Auto-detect which test executor to use based on marker files in the test directory.

    A ``go.mod`` selects the ``gotest`` executor, a ``pyproject.toml`` selects ``pytest``. When the
    detection is inconclusive (neither or both markers present) the historical default ``pytest`` is
    used and the user is advised to set ``--test-executor`` explicitly.
    """
    resolved_dir = TestExecutor._resolve_test_dir(chart_file, tests_dir, warn=False)
    has_gomod = os.path.isfile(os.path.join(resolved_dir, "go.mod"))
    has_pyproject = os.path.isfile(os.path.join(resolved_dir, "pyproject.toml"))
    if has_gomod and not has_pyproject:
        logger.info(f"Auto-detected the '{TEST_EXECUTOR_GOTEST}' test executor ('go.mod' found in '{resolved_dir}').")
        return TEST_EXECUTOR_GOTEST
    if has_pyproject and not has_gomod:
        logger.info(
            f"Auto-detected the '{TEST_EXECUTOR_PYTEST}' test executor ('pyproject.toml' found in '{resolved_dir}')."
        )
        return TEST_EXECUTOR_PYTEST
    if has_gomod and has_pyproject:
        logger.warning(
            f"Both 'go.mod' and 'pyproject.toml' were found in '{resolved_dir}', so the test executor can't be "
            f"auto-detected; defaulting to '{TEST_EXECUTOR_PYTEST}'. Set '--test-executor' explicitly to override."
        )
        return TEST_EXECUTOR_PYTEST
    logger.warning(
        f"Couldn't auto-detect the test executor: neither 'go.mod' nor 'pyproject.toml' was found in "
        f"'{resolved_dir}'; defaulting to '{TEST_EXECUTOR_PYTEST}'. Set '--test-executor' explicitly to override."
    )
    return TEST_EXECUTOR_PYTEST


def configure_global_options(config_parser: configargparse.ArgParser) -> None:
    config_parser.add_argument(
        "-d",
        "--debug",
        required=False,
        default=False,
        action="store_true",
        help="Enable debug messages.",
    )
    config_parser.add_argument(
        "--test-executor",
        required=False,
        default=TEST_EXECUTOR_AUTO,
        choices=[TEST_EXECUTOR_AUTO, TEST_EXECUTOR_PYTEST, TEST_EXECUTOR_GOTEST],
        help="Type of test executor to use: 'pytest' or 'gotest'. Defaults to 'auto', which detects it from "
        "the test directory ('go.mod' -> gotest, 'pyproject.toml' -> pytest).",
    )
    config_parser.add_argument(
        KEY_CFG_TESTS_DIR,
        required=False,
        default=DEFAULT_TESTS_DIR,
        help="Directory where the test suite source code (pytest or go tests) can be found. Resolved relative "
        "to the working directory unless an absolute path is given.",
    )
    config_parser.add_argument("--version", action="version", version=f"{app_name} {get_version()}")
    config_parser.add_argument(
        "--keep-going",
        required=False,
        default=True,
        action=argparse.BooleanOptionalAction,
        help="Collect all errors before failing instead of stopping on the first failure. Full pipeline support requires step-exec-lib >= 0.5.0. Use --no-keep-going for fail-fast behaviour.",
    )
    steps_group = config_parser.add_mutually_exclusive_group()
    steps_group.add_argument(
        "--steps",
        nargs="+",
        help=f"List of steps to execute. Available steps: {ALL_STEPS}",
        required=False,
        default=["all"],
    )
    steps_group.add_argument(
        "--skip-steps",
        nargs="+",
        help=f"List of steps to skip. Available steps: {ALL_STEPS}",
        required=False,
        default=[],
    )


def configure_test_specific_options(config_parser: configargparse.ArgParser) -> None:
    # FIXME: this should be now part of the UpgradeTestScenario class
    config_parser_group = config_parser.add_argument_group("Upgrade testing options")
    app_source_group = config_parser_group.add_mutually_exclusive_group()
    app_source_group.add_argument(
        KEY_CFG_STABLE_APP_URL,
        required=False,
        help="URL of the catalog where the stable version of the app (the version to test upgrade from) is available. "
        f"Mutually exclusive with '{KEY_CFG_STABLE_APP_FILE}'.",
    )
    app_source_group.add_argument(
        KEY_CFG_STABLE_APP_FILE,
        required=False,
        help="Local file name with the stable version of the app (the version to test upgrade from). "
        f"Mutually exclusive with '{KEY_CFG_STABLE_APP_URL}'.",
    )
    config_parser_group.add_argument(
        KEY_CFG_STABLE_APP_CONFIG,
        required=False,
        help="Path for a configuration file (values file) for your app when it's deployed for testing.",
    )
    config_parser_group.add_argument(
        KEY_CFG_STABLE_APP_VERSION,
        required=False,
        default="stable",
        help=f"Version of the app to test the upgrade from. If not given, the default value of 'stable' is used, which "
        "means the latest stable (non-prerelease) version available is detected and used. Any explicit version "
        f"configured instead must be present in the catalog configured with '{KEY_CFG_STABLE_APP_URL}'. "
        f"Used only if '{KEY_CFG_STABLE_APP_URL} is used.'",
    )
    config_parser_group.add_argument(
        KEY_CFG_UPGRADE_HOOK,
        required=False,
        help="A command (executable) that is run after the tests for the stable version of the app completed"
        " successfully, but before the app is upgraded and tested again.",
    )
    config_parser_group.add_argument(
        KEY_CFG_UPGRADE_SAVE_METADATA,
        default=False,
        action="store_true",
        required=False,
        help="Save upgrade test result to a metadata file.",
    )


def get_default_config_file_paths() -> List[str]:
    base_dir = os.getcwd()
    # The config file is looked up relative to the executing directory (the current working directory),
    # so it can be provided independently of where the chart archive lives (see issue #196).
    cwd_config_path = os.path.join(base_dir, ".ats", "main.yaml")
    config_paths = [cwd_config_path]
    # Backward compatibility: also look for the config next to the chart file. When both files exist,
    # the chart-file-relative one is parsed last and thus takes precedence, preserving legacy behaviour.
    chart_file = get_chart_file_from_argv()
    if chart_file:
        chart_dir = os.path.dirname(chart_file)
        chart_config_path = os.path.join(base_dir, chart_dir, ".ats", "main.yaml")
        if os.path.normpath(chart_config_path) != os.path.normpath(cwd_config_path):
            config_paths.append(chart_config_path)
    logger.debug(f"Using {config_paths} as configuration file path candidates.")
    return config_paths


def get_global_config_parser(add_help: bool = True) -> configargparse.ArgParser:
    config_file_paths = get_default_config_file_paths()
    config_parser = configargparse.ArgParser(
        prog=app_name,
        add_config_file_help=True,
        default_config_files=config_file_paths,
        description="Test Giant Swarm App Platform app.",
        add_env_var_help=True,
        auto_env_var_prefix="ATS_",
        formatter_class=configargparse.ArgumentDefaultsHelpFormatter,
        add_help=add_help,
    )
    configure_global_options(config_parser)
    configure_test_specific_options(config_parser)
    return config_parser


def validate_global_config(config: configargparse.Namespace) -> None:
    # validate steps; '--steps' and '--skip-steps' can't be used together, but that is already
    # enforced by the argparse library
    if STEP_ALL in config.skip_steps:
        raise ConfigError("skip-steps", f"'{STEP_ALL}' is not a reasonable step kind to skip.")
    for step in config.steps + config.skip_steps:
        if step not in ALL_STEPS:
            raise ConfigError("steps", f"Unknown step '{step}'. Valid steps are: {ALL_STEPS}.")


def get_config(steps: List[BuildStep]) -> configargparse.Namespace:
    # initialize config, setup arg parsers
    try:
        config_parser = get_global_config_parser()
        for step in steps:
            step.initialize_config(config_parser)
        config = config_parser.parse_args()
        validate_global_config(config)
    except ConfigError as e:
        logger.error(f"Error when checking config option '{e.config_option}': {e.msg}")
        sys.exit(1)

    logger.info(f"{app_name} {get_version()}")
    logger.info("Starting test with the following options")
    logger.info(f"\n{config_parser.format_values()}")
    return config


def main() -> None:
    log_format = "%(asctime)s %(name)s %(levelname)s: %(message)s"
    logging.basicConfig(format=log_format)
    logging.getLogger().setLevel(logging.INFO)

    global_only_config_parser = get_global_config_parser(add_help=False)
    global_only_config = global_only_config_parser.parse_known_args()[0]
    if global_only_config.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    test_executor = global_only_config.test_executor
    if test_executor == TEST_EXECUTOR_AUTO:
        test_executor = detect_test_executor(global_only_config.tests_dir, get_chart_file_from_argv())

    steps = get_pipeline(test_executor)
    config = get_config(steps)
    runner = Runner(config, steps)
    runner.run()


if __name__ == "__main__":
    main()
