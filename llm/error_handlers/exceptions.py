class RateLimitError(Exception):
    def __init__(self, message="Rate limit", cooldown_seconds=3600):
        super().__init__(message)
        self.cooldown_seconds = cooldown_seconds
