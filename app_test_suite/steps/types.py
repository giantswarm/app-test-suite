from step_exec_lib.types import StepType, STEP_ALL

STEP_TEST_SMOKE = StepType("smoke")
STEP_TEST_FUNCTIONAL = StepType("functional")
STEP_TEST_PERFORMANCE = StepType("performance")
STEP_TEST_COMPATIBILITY = StepType("compatibility")
STEP_TEST_UPGRADE = StepType("upgrade")
TEST_TYPE_ALL = {STEP_TEST_SMOKE, STEP_TEST_FUNCTIONAL, STEP_TEST_UPGRADE}
ALL_STEPS = {
    STEP_ALL,
} | TEST_TYPE_ALL


def config_option_cluster_type_for_test_type(test_type: StepType) -> str:
    return f"--{test_type}-tests-cluster-type"
