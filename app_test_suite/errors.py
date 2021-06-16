class TestError(Error):
    """
    TestError is raised in the test phase only
    """

    def __str__(self) -> str:
        return self.msg
