class PipelineExit(Exception):
    """Exception raised to exit the pipeline gracefully with a specific outcome code.
    Controls whether the pipeline run sends a webhook alert."""
    def __init__(self, outcome: str, should_alert: bool = False, message: str = ""):
        super().__init__(message or outcome)
        self.outcome = outcome
        self.should_alert = should_alert
