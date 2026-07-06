import os
import subprocess

import pytest
from pytest_helm_charts.api.deployment import wait_for_deployments_to_run
from pytest_helm_charts.fixtures import Cluster


@pytest.mark.smoke
def test_gitops_engine_leg(kube_cluster: Cluster) -> None:
    assert os.environ.get("ATS_EXTRA_GITOPS_ENGINE") == "flux"


@pytest.mark.smoke
def test_helmrelease_reconciled(kube_cluster: Cluster) -> None:
    namespace = os.environ["ATS_RELEASE_NAMESPACE"]
    subprocess.run(
        [
            "kubectl",
            f"--kubeconfig={os.environ['KUBECONFIG']}",
            "wait",
            "--for=condition=Ready",
            "helmrelease/podinfo",
            "--namespace",
            namespace,
            "--timeout=60s",
        ],
        check=True,
    )
    wait_for_deployments_to_run(kube_cluster.kube_client, ["podinfo"], namespace, 60)
