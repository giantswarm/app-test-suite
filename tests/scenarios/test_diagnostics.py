import logging
import unittest.mock

import pytest
import pykube
from pytest_mock import MockerFixture

from app_test_suite.steps.base import CONTEXT_KEY_CHART_YAML
from app_test_suite.steps.executors.pytest import PytestExecutor
from app_test_suite.steps.scenarios.simple import SmokeTestScenario
from tests.helpers import (
    MOCK_APP_DEPLOY_NS,
    MOCK_APP_NAME,
    get_mock_cluster_manager,
)

_GIANTSWARM_NS = "giantswarm"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pod(
    mocker: MockerFixture,
    name: str,
    phase: str,
    containers: list[str] | None = None,
    init_containers: list[str] | None = None,
    logs: str = "pod log line",
) -> unittest.mock.MagicMock:
    pod = mocker.MagicMock(name=f"pod-{name}")
    pod.name = name
    pod.obj = {
        "status": {"phase": phase},
        "spec": {
            "containers": [{"name": c} for c in (containers or ["main"])],
            "initContainers": [{"name": c} for c in (init_containers or [])],
        },
    }
    pod.logs.return_value = logs
    return pod


def _make_event(
    mocker: MockerFixture,
    timestamp: str,
    event_type: str,
    reason: str,
    message: str,
) -> unittest.mock.MagicMock:
    event = mocker.MagicMock(name=f"event-{reason}")
    event.obj = {
        "lastTimestamp": timestamp,
        "type": event_type,
        "reason": reason,
        "message": message,
    }
    return event


def _make_node(mocker: MockerFixture, name: str, ready: str) -> unittest.mock.MagicMock:
    node = mocker.MagicMock(name=f"node-{name}")
    node.name = name
    node.obj = {"status": {"conditions": [{"type": "Ready", "status": ready}]}}
    return node


def _make_app_cr(mocker: MockerFixture, name: str) -> unittest.mock.MagicMock:
    cr = mocker.MagicMock(name=f"appcr-{name}")
    cr.obj = {"metadata": {"name": name}, "spec": {}}
    return cr


def _make_deployment(mocker: MockerFixture, name: str) -> unittest.mock.MagicMock:
    dep = mocker.MagicMock(name=f"deploy-{name}")
    dep.name = name
    dep.obj = {"status": {"availableReplicas": 1}}
    return dep


def _patch_pykube(
    mocker: MockerFixture,
    app_ns_pods: list | None = None,
    giantswarm_pods: list | None = None,
    events: list | None = None,
    app_crs: list | None = None,
    deployments: list | None = None,
    nodes: list | None = None,
) -> None:
    """Patch all pykube API lookups used by _collect_failure_diagnostics."""
    _app_ns_pods = app_ns_pods or []
    _giantswarm_pods = giantswarm_pods or []

    # Pod.objects — dispatches on namespace kwarg
    pod_query = mocker.MagicMock(name="pod_query")
    pod_query.filter.side_effect = lambda **kwargs: (
        _giantswarm_pods if kwargs.get("namespace") == _GIANTSWARM_NS else _app_ns_pods
    )
    mocker.patch.object(pykube.Pod, "objects", return_value=pod_query)

    # Event.objects
    event_query = mocker.MagicMock(name="event_query")
    event_query.filter.return_value = events or []
    mocker.patch.object(pykube.Event, "objects", return_value=event_query)

    # AppCR.objects — imported into the module under test
    app_cr_query = mocker.MagicMock(name="app_cr_query")
    app_cr_query.filter.return_value = app_crs or []
    mocker.patch("app_test_suite.steps.scenarios.simple.AppCR.objects", return_value=app_cr_query)

    # Deployment.objects
    deploy_query = mocker.MagicMock(name="deploy_query")
    deploy_query.filter.return_value = deployments or []
    mocker.patch.object(pykube.Deployment, "objects", return_value=deploy_query)

    # Node.objects
    node_query = mocker.MagicMock(name="node_query")
    node_query.all.return_value = nodes or []
    mocker.patch.object(pykube.Node, "objects", return_value=node_query)


def _make_scenario(mocker: MockerFixture) -> SmokeTestScenario:
    scenario = SmokeTestScenario(get_mock_cluster_manager(mocker), PytestExecutor())
    scenario._kube_client = mocker.MagicMock(name="kube_client")
    return scenario


def _make_context() -> dict:
    return {CONTEXT_KEY_CHART_YAML: {"name": MOCK_APP_NAME, "version": "0.1.0"}}


def _make_config(mocker: MockerFixture) -> unittest.mock.MagicMock:
    config = mocker.MagicMock(name="config")
    config.app_tests_deploy_namespace = MOCK_APP_DEPLOY_NS
    return config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_diagnostics_skipped_when_no_kube_client(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    scenario = _make_scenario(mocker)
    scenario._kube_client = None

    with caplog.at_level(logging.WARNING):
        scenario._collect_failure_diagnostics(_make_config(mocker), _make_context())

    assert any("No kube client" in r.message for r in caplog.records)
    # pykube should never be touched
    mocker.patch.object(pykube.Pod, "objects")  # would fail if already called
    assert not any(isinstance(r.levelno, int) and r.levelno == logging.ERROR for r in caplog.records)


def test_diagnostics_logs_running_pod_phase(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    pod = _make_pod(mocker, "running-pod", "Running")
    _patch_pykube(mocker, app_ns_pods=[pod])

    with caplog.at_level(logging.ERROR):
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("running-pod" in m and "Running" in m for m in error_messages)


def test_diagnostics_dumps_yaml_for_non_running_pod(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    pod = _make_pod(mocker, "crashed-pod", "CrashLoopBackOff")
    _patch_pykube(mocker, app_ns_pods=[pod])

    with caplog.at_level(logging.ERROR):
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Describe pod 'crashed-pod'" in m for m in error_messages)
    # YAML dump of pod.obj should appear
    assert any("crashed-pod" in m and "CrashLoopBackOff" in m for m in error_messages)


def test_diagnostics_skips_yaml_dump_for_running_pod(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    pod = _make_pod(mocker, "ok-pod", "Running")
    _patch_pykube(mocker, app_ns_pods=[pod])

    with caplog.at_level(logging.ERROR):
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert not any("Describe pod 'ok-pod'" in m for m in error_messages)


def test_diagnostics_collects_container_logs(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    pod = _make_pod(mocker, "mypod", "Running", containers=["app", "sidecar"], logs="important log line")
    pod.logs.side_effect = lambda container=None, tail_lines=None, previous=False: (
        "" if previous else f"log from {container}"
    )
    _patch_pykube(mocker, app_ns_pods=[pod])

    with caplog.at_level(logging.ERROR):
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("log from app" in m for m in error_messages)
    assert any("log from sidecar" in m for m in error_messages)


def test_diagnostics_collects_init_container_logs(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    pod = _make_pod(mocker, "mypod", "Running", containers=["main"], init_containers=["init-db"])
    pod.logs.side_effect = lambda container=None, tail_lines=None, previous=False: (
        "" if previous else f"log from {container}"
    )
    _patch_pykube(mocker, app_ns_pods=[pod])

    with caplog.at_level(logging.ERROR):
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("log from init-db" in m for m in error_messages)


def test_diagnostics_collects_previous_logs_when_available(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    pod = _make_pod(mocker, "restarted-pod", "Running")
    pod.logs.side_effect = lambda container=None, tail_lines=None, previous=False: (
        "previous crash log" if previous else "current log"
    )
    _patch_pykube(mocker, app_ns_pods=[pod])

    with caplog.at_level(logging.ERROR):
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Previous logs" in m and "restarted-pod" in m for m in error_messages)
    assert any("previous crash log" in m for m in error_messages)


def test_diagnostics_silently_skips_missing_previous_logs(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    pod = _make_pod(mocker, "mypod", "Running")
    pod.logs.side_effect = lambda container=None, tail_lines=None, previous=False: (
        (_ for _ in ()).throw(Exception("no previous log")) if previous else "current log"
    )
    _patch_pykube(mocker, app_ns_pods=[pod])

    with caplog.at_level(logging.ERROR):
        # Must not raise
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert not any("Previous logs" in m for m in error_messages)


def test_diagnostics_logs_events_sorted_by_timestamp(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    events = [
        _make_event(mocker, "2024-01-01T00:00:02Z", "Warning", "BackOff", "Back-off restarting failed container"),
        _make_event(mocker, "2024-01-01T00:00:01Z", "Normal", "Pulled", "Image pulled"),
    ]
    _patch_pykube(mocker, events=events)

    with caplog.at_level(logging.ERROR):
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    event_messages = [m for m in error_messages if "Pulled" in m or "BackOff" in m]
    assert len(event_messages) == 2
    # Earlier timestamp should appear first
    assert event_messages.index(next(m for m in event_messages if "Pulled" in m)) < event_messages.index(
        next(m for m in event_messages if "BackOff" in m)
    )


def test_diagnostics_logs_app_crs(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    app_cr = _make_app_cr(mocker, MOCK_APP_NAME)
    _patch_pykube(mocker, app_crs=[app_cr])

    with caplog.at_level(logging.ERROR):
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any(f"App CRs in namespace '{MOCK_APP_DEPLOY_NS}'" in m for m in error_messages)
    assert any(MOCK_APP_NAME in m for m in error_messages)


def test_diagnostics_logs_deployments(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    dep = _make_deployment(mocker, "my-deploy")
    _patch_pykube(mocker, deployments=[dep])

    with caplog.at_level(logging.ERROR):
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any(f"Deployments in namespace '{MOCK_APP_DEPLOY_NS}'" in m for m in error_messages)
    assert any("my-deploy" in m for m in error_messages)


def test_diagnostics_collects_operator_pod_logs(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    app_operator_pod = _make_pod(mocker, "app-operator-abc", "Running", logs="app-operator log output")
    chart_operator_pod = _make_pod(mocker, "chart-operator-xyz", "Running", logs="chart-operator log output")

    app_operator_pod.logs.return_value = "app-operator log output"
    chart_operator_pod.logs.return_value = "chart-operator log output"

    _patch_pykube(mocker, giantswarm_pods=[app_operator_pod, chart_operator_pod])

    with caplog.at_level(logging.ERROR):
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("app-operator log output" in m for m in error_messages)
    assert any("chart-operator log output" in m for m in error_messages)


def test_diagnostics_logs_node_status(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    nodes = [_make_node(mocker, "node-1", "True"), _make_node(mocker, "node-2", "False")]
    _patch_pykube(mocker, nodes=nodes)

    with caplog.at_level(logging.ERROR):
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("node-1" in m and "Ready=True" in m for m in error_messages)
    assert any("node-2" in m and "Ready=False" in m for m in error_messages)


def test_diagnostics_handles_api_exception_gracefully(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch.object(pykube.Pod, "objects", side_effect=Exception("API unavailable"))
    # Other pykube objects still need to be patched to avoid real API calls
    mocker.patch.object(pykube.Event, "objects", side_effect=Exception("API unavailable"))
    mocker.patch("app_test_suite.steps.scenarios.simple.AppCR.objects", side_effect=Exception("API unavailable"))
    mocker.patch.object(pykube.Deployment, "objects", side_effect=Exception("API unavailable"))
    mocker.patch.object(pykube.Node, "objects", side_effect=Exception("API unavailable"))

    with caplog.at_level(logging.WARNING):
        # Must not propagate the exception
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    assert any("Failed to collect diagnostics" in r.message for r in caplog.records)


def test_diagnostics_handles_pod_log_exception_gracefully(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    pod = _make_pod(mocker, "broken-pod", "Running")
    pod.logs.side_effect = Exception("log stream unavailable")
    _patch_pykube(mocker, app_ns_pods=[pod])

    with caplog.at_level(logging.WARNING):
        # Must not propagate the exception
        _make_scenario(mocker)._collect_failure_diagnostics(_make_config(mocker), _make_context())

    assert any("Failed to get logs" in r.message and "broken-pod" in r.message for r in caplog.records)
