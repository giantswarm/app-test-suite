from typing import cast

import pykube
import pytest
from pytest_helm_charts.api.deployment import wait_for_deployments_to_run
from pytest_helm_charts.fixtures import Cluster


@pytest.mark.smoke
def test_we_have_environment(kube_cluster: Cluster) -> None:
    assert kube_cluster.kube_client is not None
    assert len(pykube.Node.objects(kube_cluster.kube_client)) >= 1


@pytest.mark.functional
@pytest.mark.upgrade
def test_hello_working(kube_cluster: Cluster) -> None:
    wait_for_deployments_to_run(kube_cluster.kube_client, ["hello-world-app"], "default", 60)
    srv = cast(
        pykube.Service,
        pykube.Service.objects(kube_cluster.kube_client).get_or_none(name="hello-world-app-service"),
    )
    if srv is None:
        raise ValueError("'hello-world-app-service service not found in the 'default' namespace")
    page_res = srv.proxy_http_get("/")
    assert page_res.ok
    assert page_res.text.find("Hello World") > -1


@pytest.mark.integration
def test_hello_world_endpoint_content(kube_cluster: Cluster) -> None:
    wait_for_deployments_to_run(kube_cluster.kube_client, ["hello-world-app"], "default", 120)
    srv = cast(
        pykube.Service,
        pykube.Service.objects(kube_cluster.kube_client).get_or_none(name="hello-world-app-service"),
    )
    assert srv is not None, "hello-world-app-service not found in the 'default' namespace"
    page_res = srv.proxy_http_get("/")
    assert page_res.ok
    assert "Hello World" in page_res.text
