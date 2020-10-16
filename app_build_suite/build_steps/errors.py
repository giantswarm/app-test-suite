"""Errors returned by app_build_suite"""


class Error(Exception):
    """
    Basic error class that just returns a message.
    """

    def __init__(self, message: str):
        super().__init__()
        self.msg = message


class ConfigError(Error):
    """
    Error class that shows error in configuration options.
    """

    config_option: str

    def __init__(self, config_option: str, message: str):
        super().__init__(message)
        self.config_option = config_option


class ValidationError(Error):
    """
    ValidationError means some input data (configuration, chart) is impossible to process or fails
    assumptions.
    """

    source: str

    def __init__(self, source: str, message: str):
        super().__init__(message)
        self.source = source


class BuildError(Error):
    """
    BuildError can be raised only during executing actual build process (not configuration or validation).
    """

    source: str

    def __init__(self, source: str, message: str):
        super().__init__(message)
        self.source = source
