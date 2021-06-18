import argparse
import logging
from abc import ABC, abstractmethod
from typing import cast

from pykube import HTTPClient, Service
from step_exec_lib.types import Context

from app_test_suite.errors import TestError

logger = logging.getLogger(__name__)


class AppRepository(ABC):
    @abstractmethod
    def upload_artifacts(self, config: argparse.Namespace, context: Context) -> None:
        raise NotImplementedError()


class ChartMuseumAppRepository(AppRepository):
    _cm_service_name = "chartmuseum-chartmuseum"
    _cm_service_namespace = "giantswarm"

    def __init__(self, kube_client: HTTPClient):
        self._kube_client = kube_client

    def upload_artifacts(self, config: argparse.Namespace, context: Context) -> None:
        cm_srv = cast(
            Service,
            Service.objects(self._kube_client)
            .filter(namespace=self._cm_service_namespace)
            .get_or_none(name=self._cm_service_name),
        )
        if cm_srv is None:
            raise TestError(
                f"Repository service '{self._cm_service_name}' not found in namespace"
                f" '{self._cm_service_namespace}'. Can't upload chart."
            )
        chart_filename = config.chart_file
        logger.info(f"Uploading file '{chart_filename}' to chart-museum.")
        with open(chart_filename, "rb") as f:
            resp = cm_srv.proxy_http_post("/api/charts/", data=f.read())
            if not resp.ok:
                raise TestError("Error uploading chart to chartmuseum")