from step_exec_lib.errors import Error


class ATSTestError(Error):
    """
    TestError is raised in the test phase only
    """

    def __str__(self) -> str:
        return self.msg
