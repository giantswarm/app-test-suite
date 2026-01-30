import argparse
import logging
import os
from typing import Any

import configargparse
from step_exec_lib.errors import ConfigError
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option

from app_test_suite.cluster_providers import cluster_provider

logger = logging.getLogger(__name__)

ClusterTypeExternal = cluster_provider.ClusterType("external")


class ExternalClusterProvider(cluster_provider.ClusterProvider):
    key_config_option_kubeconfig_path = "--external-cluster-kubeconfig-path"
    key_config_option_cluster_type = "--external-cluster-type"
    key_config_option_cluster_version = "--external-cluster-version"

    def __init__(self) -> None:
        self.__kubeconfig_path = ""

    @property
    def provided_cluster_type(self) -> cluster_provider.ClusterType:
        return ClusterTypeExternal

    def initialize_config(self, config_parser: configargparse.ArgParser) -> None:
        config_parser.add_argument(
            self.key_config_option_kubeconfig_path,
            required=False,
            help="A path to the 'kubeconfig' file that provides connection details for external cluster",
        )
        config_parser.add_argument(
            self.key_config_option_cluster_type,
            required=False,
            help="A cluster type that should be used as a value for marking runs on this external cluster.",
        )
        config_parser.add_argument(
            self.key_config_option_cluster_version,
            required=False,
            help="A cluster version that should be used as a value for marking runs on this external cluster.",
        )

    def pre_run(self, config: argparse.Namespace) -> None:
        if not config.external_cluster_kubeconfig_path:
            raise ConfigError(
                self.key_config_option_kubeconfig_path,
                "Kubeconfig file path must be configured",
            )
        if not os.path.isfile(config.external_cluster_kubeconfig_path):
            raise ConfigError(
                self.key_config_option_kubeconfig_path,
                f"Kubeconfig file {config.external_cluster_kubeconfig_path} not found.",
            )
        self.__kubeconfig_path = config.external_cluster_kubeconfig_path

        if not get_config_value_by_cmd_line_option(config, self.key_config_option_cluster_type):
            raise ConfigError(
                self.key_config_option_cluster_type,
                "When using external cluster you must pass an arbitrary 'type' value.",
            )

        if not get_config_value_by_cmd_line_option(config, self.key_config_option_cluster_version):
            raise ConfigError(
                self.key_config_option_cluster_type,
                "When using external cluster you must pass an arbitrary 'version' value.",
            )

    def get_cluster(
        self,
        cluster_type: cluster_provider.ClusterType,
        config: argparse.Namespace,
        **kwargs: Any,
    ) -> cluster_provider.ClusterInfo:
        overridden_cluster_type = get_config_value_by_cmd_line_option(config, self.key_config_option_cluster_type)
        cluster_version = get_config_value_by_cmd_line_option(config, self.key_config_option_cluster_version)
        logger.debug("External cluster manager returning kubeconfig path as configured.")
        return cluster_provider.ClusterInfo(
            cluster_type=self.provided_cluster_type,
            overridden_cluster_type=overridden_cluster_type,
            version=cluster_version,
            cluster_id="unknown",
            kube_config_path=self.__kubeconfig_path,
            managing_provider=self,
            config_file="",
        )

    def delete_cluster(self, cluster_info: cluster_provider.ClusterInfo) -> None:
        logger.debug("External cluster manager ignoring cluster deletion request (as expected).")
