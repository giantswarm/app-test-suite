"""The CRD bundle shipped with ats (app_test_suite/crds/*.yaml, applied with
`kubectl apply --server-side -f /etc/ats/crds` on every run) must consist of
Kubernetes objects only. A stray document, such as helm's "Pulled:"/"Digest:"
chatter captured from stdout while syncing, makes kubectl reject the whole
directory and every ATS run fail at CRD bootstrap (1.0.0 shipped that way)."""

from pathlib import Path
from typing import Any, List

import pytest
import yaml
from pytest_mock import MockerFixture

from app_test_suite.steps.base import (
    IMAGE_CLUSTER_CRDS_DIR,
    PACKAGED_CLUSTER_CRDS_DIR,
    default_cluster_crds_dir,
)

BUNDLE_DIR = Path(__file__).resolve().parents[1] / "app_test_suite" / "crds"
BUNDLE_FILES = sorted(BUNDLE_DIR.glob("*.yaml"))


def _documents(path: Path) -> List[Any]:
    with path.open() as f:
        return [doc for doc in yaml.safe_load_all(f) if doc is not None]


def test_bundle_is_not_empty() -> None:
    assert BUNDLE_FILES, f"no CRD files in {BUNDLE_DIR}"


@pytest.mark.parametrize("path", BUNDLE_FILES, ids=lambda p: p.name)
def test_every_document_is_a_kubernetes_object(path: Path) -> None:
    docs = _documents(path)
    assert docs, f"{path.name} contains no documents"
    for i, doc in enumerate(docs):
        assert isinstance(doc, dict), f"{path.name}: document {i} is a {type(doc).__name__}, not a mapping"
        missing = [k for k in ("apiVersion", "kind", "metadata") if k not in doc]
        assert not missing, f"{path.name}: document {i} lacks {missing}: keys are {sorted(doc)[:6]}"
        assert isinstance(doc["metadata"], dict) and doc["metadata"].get("name"), (
            f"{path.name}: document {i} ({doc['kind']}) has no metadata.name"
        )


def test_packaged_crds_dir_is_the_bundle() -> None:
    # `uv tool install` gets the CRDs only if they ship inside the package.
    assert Path(PACKAGED_CLUSTER_CRDS_DIR) == BUNDLE_DIR
    assert BUNDLE_FILES


@pytest.mark.parametrize(
    "image_dir_exists,expected",
    [(True, IMAGE_CLUSTER_CRDS_DIR), (False, PACKAGED_CLUSTER_CRDS_DIR)],
    ids=["docker image", "outside the image"],
)
def test_default_cluster_crds_dir(image_dir_exists: bool, expected: str, mocker: MockerFixture) -> None:
    mock_isdir = mocker.patch("app_test_suite.steps.base.os.path.isdir", return_value=image_dir_exists)

    assert default_cluster_crds_dir() == expected
    mock_isdir.assert_called_once_with(IMAGE_CLUSTER_CRDS_DIR)
