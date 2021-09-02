from typing import cast
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture
from requests import Response
from yaml.parser import ParserError

import app_test_suite
from app_test_suite.cluster_manager import ClusterManager
from app_test_suite.errors import TestError
from app_test_suite.steps.pytest.pytest import PytestUpgradeTestRunner


@pytest.mark.parametrize(
    "resp_code,resp_reason,resp_text,error_type,ver_found",
    [
        (200, "OK", "", None, "0.2.4"),
        (404, "Not found", "", TestError, ""),
        (200, "OK", ": - : not a YAML", ParserError, ""),
        (200, "OK", "yaml: {}", TestError, ""),
        (200, "OK", "entries: {}", TestError, ""),
    ],
    ids=["response OK", "index.yaml not found", "bad YAML", "no 'entries' in YAML", "app entry not found"],
)
def test_find_latest_version(
    mocker: MockerFixture, resp_code: int, resp_reason: str, resp_text: str, error_type: type, ver_found: str
) -> None:
    mock_cluster_manager = mocker.MagicMock(spec=ClusterManager)
    runner = PytestUpgradeTestRunner(mock_cluster_manager)
    with open("tests/assets/test_index.yaml", "r") as file:
        test_index_yaml = file.read()

    requests_get_res = mocker.MagicMock(spec=Response, name="index.yaml get result")
    requests_get_res.ok = 300 > resp_code >= 200
    requests_get_res.status_code = resp_code
    requests_get_res.reason = resp_reason
    requests_get_res.text = test_index_yaml if resp_text == "" else resp_text
    mocker.patch("app_test_suite.steps.pytest.pytest.requests.get", return_value=requests_get_res)

    catalog_url = "http://mock.catalog"
    app_name = "hello-world-app"
    catched_error = None
    ver = ""
    try:
        ver = runner._get_latest_app_version(catalog_url, app_name)
    except Exception as e:
        catched_error = e

    if error_type:
        assert type(catched_error) == error_type
    else:
        assert ver == ver_found
    cast(Mock, app_test_suite.steps.pytest.pytest.requests.get).assert_called_once_with(catalog_url + "/index.yaml")
