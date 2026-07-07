import pytest
from _pytest.monkeypatch import MonkeyPatch

from app_test_suite.__main__ import main


@pytest.mark.skip(reason="Requires a running cluster and the Argo CD install manifest")
def test_argo_bundle_app(monkeypatch: MonkeyPatch) -> None:
    """Run from examples/apps/argo-bundle-app with a kind cluster's kubeconfig in ./kube.config.

    The chart renders an Argo CD Application; 'auto' detection turns the smoke scenario into an
    Argo engine iteration that installs Argo CD, waits for the bundle to converge and runs the
    tests from tests/ats.
    """
    monkeypatch.setattr(
        "sys.argv",
        [
            "bogus",
            "-c",
            "argo-bundle-app-0.1.0.tgz",
        ],
    )
    main()
