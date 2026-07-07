import pytest
from _pytest.monkeypatch import MonkeyPatch

from app_test_suite.__main__ import main


@pytest.mark.skip(reason="Requires a running cluster and the Flux install manifest")
def test_flux_bundle_app(monkeypatch: MonkeyPatch) -> None:
    """Run from examples/apps/flux-bundle-app with a kind cluster's kubeconfig in ./kube.config.

    The chart renders Flux HelmRepository + HelmRelease resources; 'auto' detection turns the
    smoke scenario into a Flux engine iteration that installs Flux, waits for the bundle to converge
    and runs the tests from tests/ats.
    """
    monkeypatch.setattr(
        "sys.argv",
        [
            "bogus",
            "-c",
            "flux-bundle-app-0.1.0.tgz",
        ],
    )
    main()
