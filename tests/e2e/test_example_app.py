import pytest
from _pytest.monkeypatch import MonkeyPatch

from app_test_suite.__main__ import main


@pytest.mark.skip(reason="Requires a running cluster")
def test_build_example_app(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "bogus",
            "-c",
            "examples/apps/hello-world-app/hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz",
        ],
    )
    main()
