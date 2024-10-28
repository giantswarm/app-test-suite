"""Main module. Loads configuration and executes main control loops."""

import logging
import os
import sys
from typing import List

import configargparse
from step_exec_lib.errors import ConfigError
from step_exec_lib.steps import BuildStepsFilteringPipeline, BuildStep, Runner
from step_exec_lib.types import STEP_ALL

from app_test_suite.config import (
    KEY_CFG_STABLE_APP_URL,
    KEY_CFG_STABLE_APP_VERSION,
    KEY_CFG_STABLE_APP_CONFIG,
    KEY_CFG_UPGRADE_HOOK,
    KEY_CFG_STABLE_APP_FILE,
    KEY_CFG_UPGRADE_SAVE_METADATA,
)
from app_test_suite.steps.executors.gotest import GotestTestFilteringPipeline
from app_test_suite.steps.executors.pytest import PytestScenariosFilteringPipeline
from app_test_suite.steps.test_types import ALL_STEPS

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
    if test_executor == "pytest":
        return [
            PytestScenariosFilteringPipeline(),
        ]
    elif test_executor == "gotest":
        return [
            GotestTestFilteringPipeline(),
        ]
    else:
        raise ConfigError("test-executor", f"Unknown executor '{test_executor}'.")


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
        default="pytest",
        help="Type of test executor. Either pytest or gotest.",
    )
    config_parser.add_argument("--version", action="version", version=f"{app_name} {get_version()}")
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
    config_parser.add_argument(
        "--kind-cluster-image",
        required=False,
        default="kindest/node:v1.29.2",
        help="The container image to use for booting a kind cluster",
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
        default="latest",
        help=f"Version of the app to test the upgrade from. If not given, the default value of 'latest' is used, which "
        "means latest version available will be detected and used. The version configured must be present "
        f"in the catalog configured with '{KEY_CFG_STABLE_APP_URL}'. "
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


def get_default_config_file_path() -> str:
    base_dir = os.getcwd()
    short_opt = "-c"
    long_opt = "--chart-file"
    if short_opt in sys.argv or long_opt in sys.argv:
        opt = short_opt if short_opt in sys.argv else long_opt
        c_ind = sys.argv.index(opt)
        chart_dir = os.path.dirname(sys.argv[c_ind + 1])
        config_path = os.path.join(base_dir, chart_dir, ".ats", "main.yaml")
    else:
        config_path = os.path.join(base_dir, ".ats", "main.yaml")
    logger.debug(f"Using {config_path} as configuration file path.")
    return config_path


def get_global_config_parser(add_help: bool = True) -> configargparse.ArgParser:
    config_file_path = get_default_config_file_path()
    config_parser = configargparse.ArgParser(
        prog=app_name,
        add_config_file_help=True,
        default_config_files=[config_file_path],
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

    steps = get_pipeline(global_only_config.test_executor)
    config = get_config(steps)
    runner = Runner(config, steps)
    runner.run()


if __name__ == "__main__":
    main()
