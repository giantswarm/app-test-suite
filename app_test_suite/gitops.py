"""GitOps engine support for bundle charts.

A bundle chart renders GitOps CRs (Flux HelmRelease/Kustomization/OCIRepository or
Argo Application) instead of workloads. This module owns the engine model: which
engines exist, how they are detected from a rendered chart, and how per-engine
value overlays are resolved.
"""

import logging
import os
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
