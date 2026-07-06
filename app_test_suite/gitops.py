"""GitOps engine support for bundle charts.

A bundle chart renders GitOps CRs (Flux HelmRelease/Kustomization/OCIRepository or
Argo Application) instead of workloads. This module owns the engine model: which
engines exist, how they are detected from a rendered chart, and how per-engine
value overlays are resolved.
"""

import json
import logging
import os
import re
import time
from enum import Enum
from typing import List, Optional, Set

import yaml
from step_exec_lib.utils.processes import run_and_log

from app_test_suite.errors import ATSTestError

ENGINE_AUTO = "auto"
ENGINE_HELM = "helm"
OVERLAY_CONVENTION_DIR = "ci"

logger = logging.getLogger(__name__)


class GitOpsEngine(str, Enum):
    FLUX = "flux"
    ARGO = "argo"

    def __str__(self) -> str:
        return self.value


_ENGINE_RENDERED_KINDS = {
    GitOpsEngine.FLUX: {
        ("helm.toolkit.fluxcd.io", "HelmRelease"),
        ("kustomize.toolkit.fluxcd.io", "Kustomization"),
        ("source.toolkit.fluxcd.io", "OCIRepository"),
    },
    GitOpsEngine.ARGO: {
        ("argoproj.io", "Application"),
    },
}


def parse_engines_option(value: Optional[str]) -> Optional[List[GitOpsEngine]]:
    """Parse a `*-tests-gitops-engines` option value.

    Returns None for `auto` (detect from the rendered chart), an empty list for
    `helm` (force today's plain Helm behaviour), or the ordered, deduplicated list
    of engines for an explicit comma-separated list. Raises ValueError for unknown
    engine names; the caller owns mapping that to a ConfigError with the option name.
    """
    normalized = (value or ENGINE_AUTO).strip().lower()
    if normalized == ENGINE_AUTO:
        return None
    if normalized == ENGINE_HELM:
        return []
    engines: List[GitOpsEngine] = []
    for name in normalized.split(","):
        engine_name = name.strip()
        try:
            engine = GitOpsEngine(engine_name)
        except ValueError:
            valid = ", ".join([ENGINE_AUTO, ENGINE_HELM] + [e.value for e in GitOpsEngine])
            raise ValueError(f"Unknown GitOps engine '{engine_name}'. Valid values are: {valid}.")
        if engine not in engines:
            engines.append(engine)
    return engines


def detect_engines(chart_path: str, values_paths: List[str]) -> List[GitOpsEngine]:
    """Render the chart with `helm template` and detect GitOps engines from the emitted kinds."""
    args = ["helm", "template", chart_path]
    for values_path in values_paths:
        args += ["--values", values_path]
    run_res = run_and_log(args, capture_output=True)  # nosec, chart file is the user's responsibility
    if run_res.returncode != 0:
        raise ATSTestError(
            f"Rendering chart '{chart_path}' with 'helm template' for GitOps engine detection failed:\n{run_res.stderr}"
        )
    detected: Set[GitOpsEngine] = set()
    for document in yaml.safe_load_all(run_res.stdout):
        if not isinstance(document, dict):
            continue
        api_version = document.get("apiVersion", "")
        group = api_version.split("/")[0] if "/" in api_version else ""
        kind = document.get("kind", "")
        for engine, rendered_kinds in _ENGINE_RENDERED_KINDS.items():
            if (group, kind) in rendered_kinds:
                detected.add(engine)
    engines = sorted(detected, key=lambda e: e.value)
    if engines:
        logger.info(f"Detected GitOps engines from rendered chart: {[e.value for e in engines]}.")
    else:
        logger.info("No GitOps resources detected in the rendered chart.")
    return engines


def resolve_engine_overlay(engine: GitOpsEngine, configured_path: Optional[str]) -> Optional[str]:
    """Resolve the values overlay for an engine leg.

    An explicitly configured path wins; otherwise the conventional
    `ci/gitops-values-<engine>.yaml` is used when it exists (relative to the
    working directory, like test discovery).
    """
    if configured_path:
        return configured_path
    conventional_path = os.path.join(OVERLAY_CONVENTION_DIR, f"gitops-values-{engine.value}.yaml")
    if os.path.isfile(conventional_path):
        logger.info(f"Using conventional GitOps values overlay '{conventional_path}' for engine '{engine.value}'.")
        return conventional_path
    return None


_KUBECTL_BIN = "kubectl"
_ENGINE_INSTALL_WAIT_TIMEOUT = "5m"
_ENGINE_NAMESPACES = {
    GitOpsEngine.FLUX: "flux-system",
}
_ENGINE_CR_RESOURCES = {
    GitOpsEngine.FLUX: [
        "helmreleases.helm.toolkit.fluxcd.io",
        "kustomizations.kustomize.toolkit.fluxcd.io",
        "ocirepositories.source.toolkit.fluxcd.io",
    ],
    GitOpsEngine.ARGO: [
        "applications.argoproj.io",
    ],
}
POLL_INTERVAL_SEC = 10


def parse_timeout_to_seconds(value: str) -> int:
    match = re.fullmatch(r"(\d+)([smh]?)", value.strip())
    if not match:
        raise ValueError(f"Invalid timeout '{value}'; use a number with an optional s/m/h suffix, e.g. '10m'.")
    return int(match.group(1)) * {"s": 1, "m": 60, "h": 3600}[match.group(2) or "s"]


def install_engine(engine: GitOpsEngine, kube_config_path: str, manifest_source: str) -> None:
    """Install a GitOps engine on the test cluster and wait for its controllers to be available.

    The manifest source is a local path (the manifest vendored in the container image by
    default) or a URL, both handled by `kubectl apply`.
    """
    if engine not in _ENGINE_NAMESPACES:
        raise ATSTestError(f"GitOps engine '{engine.value}' is not implemented yet.")
    if "://" not in manifest_source and not os.path.isfile(manifest_source):
        raise ATSTestError(
            f"Install manifest '{manifest_source}' for GitOps engine '{engine.value}' doesn't exist."
            f" The manifest is bundled in the ats container image; when running ats outside the container,"
            f" generate it with 'hack/sync-gitops-manifests.sh' or point --gitops-{engine.value}-install-manifest"
            f" at a manifest path or URL."
        )
    logger.info(f"Installing GitOps engine '{engine.value}' from '{manifest_source}'.")
    run_res = run_and_log(
        [_KUBECTL_BIN, f"--kubeconfig={kube_config_path}", "apply", "--server-side", "-f", manifest_source],
        capture_output=True,
    )  # nosec
    if run_res.returncode != 0:
        raise ATSTestError(f"Installing GitOps engine '{engine.value}' failed:\n{run_res.stderr}")
    namespace = _ENGINE_NAMESPACES[engine]
    run_res = run_and_log(
        [
            _KUBECTL_BIN,
            f"--kubeconfig={kube_config_path}",
            "--namespace",
            namespace,
            "wait",
            "--for=condition=Available",
            "deployment",
            "--all",
            f"--timeout={_ENGINE_INSTALL_WAIT_TIMEOUT}",
        ],
        capture_output=True,
    )  # nosec
    if run_res.returncode != 0:
        raise ATSTestError(
            f"Waiting for GitOps engine '{engine.value}' controllers to become available failed:\n{run_res.stderr}"
        )
    logger.info(f"GitOps engine '{engine.value}' installed and ready.")


def _list_engine_crs(kube_config_path: str, engine: GitOpsEngine, namespace: Optional[str] = None) -> List[dict]:
    items: List[dict] = []
    for resource in _ENGINE_CR_RESOURCES[engine]:
        args = [_KUBECTL_BIN, f"--kubeconfig={kube_config_path}", "get", resource, "-o", "json"]
        args += ["--namespace", namespace] if namespace else ["--all-namespaces"]
        run_res = run_and_log(args, capture_output=True)  # nosec
        if run_res.returncode != 0:
            raise ATSTestError(f"Listing '{resource}' resources failed:\n{run_res.stderr}")
        items.extend(json.loads(run_res.stdout).get("items", []))
    return items


def _cr_ready(engine: GitOpsEngine, item: dict) -> bool:
    if engine is GitOpsEngine.ARGO:
        status = item.get("status", {})
        return status.get("health", {}).get("status") == "Healthy" and status.get("sync", {}).get("status") == "Synced"
    conditions = item.get("status", {}).get("conditions", [])
    return any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)


def _cr_display_name(item: dict) -> str:
    metadata = item.get("metadata", {})
    return f"{item.get('kind', 'Unknown')}/{metadata.get('namespace', '')}/{metadata.get('name', '')}"


def _log_not_ready_diagnostics(engine: GitOpsEngine, not_ready: List[dict]) -> None:
    for item in not_ready:
        logger.error(f"--- GitOps resource not ready: {_cr_display_name(item)} ---")
        status = item.get("status", {})
        if engine is GitOpsEngine.ARGO:
            logger.error(yaml.dump({"health": status.get("health", {}), "sync": status.get("sync", {})}))
        else:
            logger.error(yaml.dump(status.get("conditions", [])))


def wait_for_bundle_ready(kube_config_path: str, engine: GitOpsEngine, timeout_seconds: int) -> None:
    """Wait until the bundle's deploy cascade converged.

    Convergence is a fixpoint: every GitOps CR in the cluster reports ready AND the CR set is
    stable between two consecutive polls, so CRs that create more CRs (nested bundles) are
    covered. On timeout, the conditions of every non-ready CR are dumped as diagnostics.
    """
    logger.info(
        f"Waiting up to {timeout_seconds}s for all '{engine.value}' GitOps resources to become ready and stable."
    )
    deadline = time.monotonic() + timeout_seconds
    previous_uids: Optional[Set[str]] = None
    while True:
        items = _list_engine_crs(kube_config_path, engine)
        uids = {item["metadata"]["uid"] for item in items}
        not_ready = [item for item in items if not _cr_ready(engine, item)]
        if not not_ready and uids == previous_uids:
            logger.info(f"Bundle ready: all {len(items)} GitOps resources are ready and the resource set is stable.")
            return
        if time.monotonic() >= deadline:
            _log_not_ready_diagnostics(engine, not_ready)
            raise ATSTestError(
                f"Timed out waiting for the bundle to become ready: {len(not_ready)} of {len(items)}"
                f" '{engine.value}' GitOps resources are not ready after {timeout_seconds}s."
            )
        previous_uids = uids
        time.sleep(POLL_INTERVAL_SEC)


def wait_for_bundle_drained(kube_config_path: str, engine: GitOpsEngine, namespace: str, timeout_seconds: int) -> None:
    """Wait until the entry's GitOps CRs are fully deleted (finalizers included) after teardown."""
    logger.info(f"Waiting up to {timeout_seconds}s for '{engine.value}' GitOps resources in '{namespace}' to drain.")
    deadline = time.monotonic() + timeout_seconds
    while True:
        items = _list_engine_crs(kube_config_path, engine, namespace=namespace)
        if not items:
            logger.info(f"Namespace '{namespace}' drained of '{engine.value}' GitOps resources.")
            return
        if time.monotonic() >= deadline:
            remaining = ", ".join(_cr_display_name(item) for item in items)
            raise ATSTestError(
                f"Timed out waiting for GitOps resources to drain from namespace '{namespace}'"
                f" after {timeout_seconds}s; still present: {remaining}."
            )
        time.sleep(POLL_INTERVAL_SEC)
