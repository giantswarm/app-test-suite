import argparse
import logging
from abc import ABC, abstractmethod
from typing import cast

from pykube import HTTPClient, Service

from app_test_suite.errors import ATSTestError

logger = logging.getLogger(__name__)


class AppRepository(ABC):
    @abstractmethod
    def upload_artifact(self, config: argparse.Namespace, chart_file_path: str) -> None:
        raise NotImplementedError()


class ChartMuseumAppRepository(AppRepository):
    _CM_SERVICE_NAME = "chartmuseum-chartmuseum"
    _CM_SERVICE_NAMESPACE = "giantswarm"

    def __init__(self, kube_client: HTTPClient):
        self._kube_client = kube_client

    def upload_artifact(self, config: argparse.Namespace, chart_file_path: str) -> None:
        cm_srv = cast(
            Service,
            Service.objects(self._kube_client)
            .filter(namespace=self._CM_SERVICE_NAMESPACE)
            .get_or_none(name=self._CM_SERVICE_NAME),
        )
        if cm_srv is None:
            raise ATSTestError(
                f"Repository service '{self._CM_SERVICE_NAME}' not found in namespace"
                f" '{self._CM_SERVICE_NAMESPACE}'. Can't upload chart."
            )
        logger.info(f"Uploading file '{chart_file_path}' to chart-museum.")
        with open(chart_file_path, "rb") as f:
            resp = cm_srv.proxy_http_post("/api/charts/", data=f.read())
            if not resp.ok:
                raise ATSTestError("Error uploading chart to chartmuseum")
