class WaitAndRetryError(Exception):
    def __init__(self, message, suggested_wait_time: int = 60 * 60):
        self.message = message
        self.suggested_wait_time = suggested_wait_time
        super().__init__(self.message)


class HFSpaceIsDownError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class EmptyScriptException(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class InvalidScriptException(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)
