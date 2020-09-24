"""Main module."""
import logging
from typing import List

import configargparse

from app_build_suite.build_steps import (
    BuildStep,
    HelmBuilderValidator,
    HelmGitVersionSetter,
    Error,
)

version = "0.0.1"
app_name = "app_build_suite"
logger = logging.getLogger(__name__)


def get_pipeline() -> List[BuildStep]:
    return [HelmBuilderValidator(), HelmGitVersionSetter()]


def configure_global_options(config_parser: configargparse.ArgParser):
    config_parser.add_argument(
        "-d",
        "--debug",
        required=False,
        default=False,
        action="store_true",
        help="Enable debug messages.",
    )
    config_parser.add_argument(
        "--version", action="version", version=f"{app_name} v{version}"
    )


def configure(steps: List[BuildStep]) -> configargparse.Namespace:
    # initialize config, setup arg parsers
    config_parser = configargparse.ArgParser(
        prog=app_name,
        add_config_file_help=True,
        default_config_files=[".abs.yaml"],
        description="Build and test Giant Swarm App Platform app.",
        add_env_var_help=True,
        auto_env_var_prefix="ABS_",
    )
    configure_global_options(config_parser)
    for step in steps:
        step.initialize_config(config_parser)
    config = config_parser.parse_args()
    logger.info("Starting build with the following options")
    logger.info(f"\n{config_parser.format_values()}")
    return config


def run_cleanup(config: configargparse.Namespace, steps: List[BuildStep]) -> None:
    for step in steps:
        logger.info(f"Running cleanup for {step.name}")
        try:
            step.cleanup(config)
        except Error as e:
            logger.error(f"Error when running cleanup for {step.name}: {e.msg}")


def run_build_steps(config: configargparse.Namespace, steps: List[BuildStep]) -> None:
    for step in steps:
        logger.info(f"Running build step for {step.name}")
        try:
            step.run(config)
        except Error as e:
            logger.error(f"Error when running build step for {step.name}: {e.msg}")


def run_pre_steps(config: configargparse.Namespace, steps: List[BuildStep]) -> None:
    for step in steps:
        logger.info(f"Running pre-run step for {step.name}")
        try:
            step.pre_run(config)
        except Error as e:
            logger.error(f"Error when running pre-run step for {step.name}: {e.msg}")


def main():
    log_format = "%(asctime)s %(name)s %(levelname)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=log_format)

    steps = get_pipeline()
    config = configure(steps)

    if config.debug:
        logging.basicConfig(level=logging.DEBUG, format=log_format)

    run_pre_steps(config, steps)
    run_build_steps(config, steps)
    run_cleanup(config, steps)


if __name__ == "__main__":
    main()
