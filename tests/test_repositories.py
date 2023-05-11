import pykube
from pytest_mock import MockerFixture

import app_test_suite
from app_test_suite.steps.repositories import ChartMuseumAppRepository


class TestChartMuseumRepository:
    def test_calls_upload_ok(self, mocker: MockerFixture) -> None:
        config = mocker.MagicMock(name="config")
        config.chart_file = "my_chart.tgz"

        cm_srv_mock = mocker.Mock(name="cm_srv")
        cm_srv_mock.proxy_http_post.return_value = mocker.Mock(name="cm_srv_res", ok=True)
        mocker.patch("app_test_suite.steps.repositories.Service")
        get_or_none_mock = mocker.MagicMock(name="cm_get_or_none")
        get_or_none_mock.get_or_none.return_value = cm_srv_mock
        filter_mock = mocker.MagicMock(name="cm_filter")
        filter_mock.filter.return_value = get_or_none_mock
        app_test_suite.steps.repositories.Service.objects.return_value = filter_mock
        mock_client = mocker.MagicMock(spec=pykube.http.HTTPClient, autospec=True)

        cmr = ChartMuseumAppRepository(mock_client)
        mocker.patch("builtins.open", mocker.mock_open(read_data="test"))
        cmr.upload_artifact(config, "")

        app_test_suite.steps.repositories.Service.objects.called_once_with(mock_client)
        filter_mock.filter.assert_called_once_with(namespace="giantswarm")
        get_or_none_mock.get_or_none.assert_called_once_with(name="chartmuseum")
        cm_srv_mock.proxy_http_post.assert_called_once_with("/api/charts/", data="test")
