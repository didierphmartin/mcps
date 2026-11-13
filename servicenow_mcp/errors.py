"""The one failure type the tools report."""


class ConnectorError(Exception):
    """A failure reported to the MCP client as "<code>: <message>". Messages never contain secrets."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
