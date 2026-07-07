import argparse
import logging
import os
from dataclasses import dataclass

import configargparse
from step_exec_lib.errors import ConfigError
from step_exec_lib.utils.config import get_config_value_by_cmd_line_option

logger = logging.getLogger(__name__)


@dataclass
class ClusterInfo:
    # path to the kubeconfig file used to connect to the cluster
    kube_config_path: str
    # free-text label identifying the cluster type; exported to tests as ATS_CLUSTER_TYPE
    cluster_type: str
    # free-text label identifying the cluster version; exported to tests as ATS_CLUSTER_VERSION
    version: str
    # a flag indicating if the App Platform was already initialized on this cluster
    app_platform_ready: bool = False


class ClusterManager:
    """
    Provides connection details for the single, pre-existing cluster that ATS runs tests on.

    ATS does not create or destroy clusters: the user must provide a kubeconfig for an existing
    cluster via '--cluster-kubeconfig'. The same cluster is shared across all test scenarios
    (smoke, functional, upgrade), so the App Platform prerequisites are bootstrapped only once.
    """

    KEY_CONFIG_OPTION_KUBECONFIG = "--cluster-kubeconfig"
    KEY_CONFIG_OPTION_CLUSTER_TYPE = "--cluster-type"
    KEY_CONFIG_OPTION_CLUSTER_VERSION = "--cluster-version"

    def __init__(self) -> None:
        self._cluster_info: ClusterInfo | None = None

    def initialize_config(self, config_parser: configargparse.ArgParser) -> None:
        config_parser.add_argument(
            self.KEY_CONFIG_OPTION_KUBECONFIG,
            required=False,
            help="Path to the 'kubeconfig' file of the cluster to run the tests on.",
        )
        config_parser.add_argument(
            self.KEY_CONFIG_OPTION_CLUSTER_TYPE,
            required=False,
            help="An optional free-text label identifying the cluster type. Exported to tests as "
            "'ATS_CLUSTER_TYPE' and saved in upgrade test metadata.",
        )
        config_parser.add_argument(
            self.KEY_CONFIG_OPTION_CLUSTER_VERSION,
            required=False,
            help="An optional free-text label identifying the cluster version. Exported to tests as "
            "'ATS_CLUSTER_VERSION' and saved in upgrade test metadata.",
        )

    def pre_run(self, config: argparse.Namespace) -> None:
        kube_config_path = get_config_value_by_cmd_line_option(config, self.KEY_CONFIG_OPTION_KUBECONFIG)
        if not kube_config_path:
            raise ConfigError(
                self.KEY_CONFIG_OPTION_KUBECONFIG,
                "Path to the cluster 'kubeconfig' file must be configured.",
            )
        if not os.path.isfile(kube_config_path):
            raise ConfigError(
                self.KEY_CONFIG_OPTION_KUBECONFIG,
                f"Kubeconfig file '{kube_config_path}' not found.",
            )
        cluster_type = get_config_value_by_cmd_line_option(config, self.KEY_CONFIG_OPTION_CLUSTER_TYPE) or ""
        cluster_version = get_config_value_by_cmd_line_option(config, self.KEY_CONFIG_OPTION_CLUSTER_VERSION) or ""
        self._cluster_info = ClusterInfo(
            kube_config_path=kube_config_path,
            cluster_type=cluster_type,
            version=cluster_version,
        )

    def get_cluster(self) -> ClusterInfo:
        if self._cluster_info is None:
            raise ValueError("Cluster info was requested before it was initialized in 'pre_run'.")
        return self._cluster_info
