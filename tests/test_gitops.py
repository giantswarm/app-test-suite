from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from app_test_suite.gitops import (
    GitOpsEngine,
    parse_engine_option,
    resolve_engine_overlay,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("helm", None),
        ("HELM", None),
        ("flux", GitOpsEngine.FLUX),
        (" Flux ", GitOpsEngine.FLUX),
        ("argo", GitOpsEngine.ARGO),
    ],
    ids=["none", "empty", "helm", "helm-case", "flux", "flux-spaces-case", "argo"],
)
def test_parse_engine_option(value: str, expected: GitOpsEngine) -> None:
    assert parse_engine_option(value) == expected


def test_parse_engine_option_rejects_unknown_engine() -> None:
    with pytest.raises(ValueError, match="Unknown GitOps engine 'bogus'"):
        parse_engine_option("bogus")


def test_resolve_engine_overlay_configured_path_wins(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "gitops-values-flux.yaml").write_text("gitops: {}")

    assert resolve_engine_overlay(GitOpsEngine.FLUX, "custom.yaml") == "custom.yaml"


def test_resolve_engine_overlay_uses_convention(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "gitops-values-flux.yaml").write_text("gitops: {}")

    assert resolve_engine_overlay(GitOpsEngine.FLUX, None) == "ci/gitops-values-flux.yaml"
    assert resolve_engine_overlay(GitOpsEngine.ARGO, None) is None
