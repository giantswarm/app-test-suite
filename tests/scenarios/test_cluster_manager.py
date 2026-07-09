import argparse
from pathlib import Path

import pytest
from step_exec_lib.errors import ConfigError

from app_test_suite.cluster_manager import ClusterInfo, ClusterManager


def _config(
    cluster_kubeconfig: str | None = None,
    cluster_type: str | None = None,
    cluster_version: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        cluster_kubeconfig=cluster_kubeconfig,
        cluster_type=cluster_type,
        cluster_version=cluster_version,
    )


def test_get_cluster_before_pre_run_raises() -> None:
    with pytest.raises(ValueError):
        ClusterManager().get_cluster()


def test_pre_run_missing_kubeconfig_raises() -> None:
    with pytest.raises(ConfigError):
        ClusterManager().pre_run(_config(cluster_kubeconfig=None))


def test_pre_run_nonexistent_kubeconfig_raises(tmp_path: Path) -> None:
    missing = str(tmp_path / "does-not-exist.config")
    with pytest.raises(ConfigError):
        ClusterManager().pre_run(_config(cluster_kubeconfig=missing))


def test_pre_run_populates_cluster_info_with_defaults(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "kube.config"
    kubeconfig.write_text("apiVersion: v1\n")
    manager = ClusterManager()

    manager.pre_run(_config(cluster_kubeconfig=str(kubeconfig)))

    info = manager.get_cluster()
    assert isinstance(info, ClusterInfo)
    assert info.kube_config_path == str(kubeconfig)
    # the type/version labels are optional and default to empty strings
    assert info.cluster_type == ""
    assert info.version == ""
    assert info.dependency_crds_ready is False


def test_pre_run_honors_type_and_version_labels(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "kube.config"
    kubeconfig.write_text("apiVersion: v1\n")
    manager = ClusterManager()

    manager.pre_run(_config(cluster_kubeconfig=str(kubeconfig), cluster_type="kind", cluster_version="1.31"))

    info = manager.get_cluster()
    assert info.cluster_type == "kind"
    assert info.version == "1.31"
