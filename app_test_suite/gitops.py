"""GitOps engine support for bundle charts.

A bundle chart renders GitOps CRs (Flux HelmRelease/Kustomization/OCIRepository or
Argo Application) instead of workloads. This module owns the engine model: which
engines exist and how the per-engine value overlay is resolved.
"""

import logging
import os
from enum import Enum
from typing import Optional

ENGINE_HELM = "helm"
OVERLAY_CONVENTION_DIR = "ci"

logger = logging.getLogger(__name__)


class GitOpsEngine(str, Enum):
    FLUX = "flux"
    ARGO = "argo"


def parse_engine_option(value: Optional[str]) -> Optional[GitOpsEngine]:
    """Parse a `--gitops-engine` option value.

    Returns None for `helm` (the default: deploy the chart with plain Helm), or the
    selected engine. Raises ValueError for an unknown name; the caller owns mapping
    that to a ConfigError with the option name.
    """
    normalized = (value or ENGINE_HELM).strip().lower()
    if normalized == ENGINE_HELM:
        return None
    try:
        return GitOpsEngine(normalized)
    except ValueError:
        valid = ", ".join([ENGINE_HELM] + [e.value for e in GitOpsEngine])
        raise ValueError(f"Unknown GitOps engine '{normalized}'. Valid values are: {valid}.")


def resolve_engine_overlay(engine: GitOpsEngine, configured_path: Optional[str]) -> Optional[str]:
    """Resolve the values overlay for the selected engine.

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
