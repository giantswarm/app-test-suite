import os
import subprocess

import pytest
from pytest_helm_charts.fixtures import Cluster


@pytest.mark.smoke
def test_gitops_engine_leg(kube_cluster: Cluster) -> None:
    assert os.environ.get("ATS_EXTRA_GITOPS_ENGINE") == "flux"


@pytest.mark.smoke
def test_helmrelease_reconciled(kube_cluster: Cluster) -> None:
    namespace = os.environ["ATS_RELEASE_NAMESPACE"]
    kubectl = ["kubectl", f"--kubeconfig={os.environ['KUBECONFIG']}", "--namespace", namespace]
    subprocess.run(
        kubectl + ["wait", "--for=condition=Ready", "helmrelease/podinfo", "--timeout=60s"],
        check=True,
    )
    subprocess.run(
        kubectl + ["rollout", "status", "deployment/podinfo", "--timeout=60s"],
        check=True,
    )
