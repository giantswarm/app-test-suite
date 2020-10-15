from typing import Any, Dict

import pytest

from app_build_suite.__main__ import get_global_config_parser
from app_build_suite.build_steps import BuildStep
from app_build_suite.build_steps.build_step import (
    STEP_BUILD,
    STEP_METADATA,
    STEP_TEST_ALL,
)
from app_build_suite.build_steps.errors import ValidationError, Error
from tests.build_steps.dummy_build_step import DummyBuildStep, DummyTwoStepBuildPipeline


class TestBuildStep:
    def test_build_step_is_abstract(self):
        with pytest.raises(TypeError):
            BuildStep()

    def test_build_step_name(self):
        bs = DummyBuildStep("bs1")
        assert bs.name == "DummyBuildStep"

    def test_build_step_raises_own_exception_when_binary_not_found(self, monkeypatch):
        fake_bin = "fake.bin"

        def check_bin(name):
            assert name == fake_bin
            return None

        monkeypatch.setattr("shutil.which", check_bin)
        bs = DummyBuildStep("s1")
        with pytest.raises(ValidationError):
            bs._assert_binary_present_in_path(fake_bin)

    def test_build_step_validates_version_ok(self):
        bs = DummyBuildStep("bs1")
        bs._assert_version_in_range("test", "v0.2.0", "0.2.0", "0.3.0")
        bs._assert_version_in_range("test", "0.2.0", "0.2.0", "0.3.0")
        bs._assert_version_in_range("test", "v0.2.100", "0.2.0", "0.3.0")
        with pytest.raises(ValidationError):
            bs._assert_version_in_range("test", "v0.3.0", "0.2.0", "0.3.0")
        with pytest.raises(ValidationError):
            bs._assert_version_in_range("test", "v0.1.0", "0.2.0", "0.3.0")


class TestBuildStepSuite:
    def test_build_step_suite_combines_step_types_ok(self):
        bsp = DummyTwoStepBuildPipeline()
        assert bsp.steps_provided == {STEP_BUILD, STEP_METADATA, STEP_TEST_ALL}

    def test_build_step_suite_runs_steps_ok(self):
        bsp = DummyTwoStepBuildPipeline()
        config_parser = get_global_config_parser()
        bsp.initialize_config(config_parser)
        config = config_parser.parse_known_args()[0]
        context: Dict[str, Any] = {}
        bsp.pre_run(config)
        bsp.run(config, context)
        bsp.cleanup(config, context, False)

        bsp.step1.assert_run_counters(1, 1, 1, 1)
        bsp.step2.assert_run_counters(1, 1, 1, 1)

    def test_build_step_suite_runs_with_exception(self):
        bsp = DummyTwoStepBuildPipeline(fail_in_pre=True)
        config_parser = get_global_config_parser()
        bsp.initialize_config(config_parser)
        config = config_parser.parse_known_args()[0]
        with pytest.raises(Error):
            bsp.pre_run(config)

        # this fails in pre_run
        bsp.step1.assert_run_counters(1, 1, 0, 0)
        # since step above fails, this won't have even pre_run ran
        bsp.step2.assert_run_counters(1, 0, 0, 0)
