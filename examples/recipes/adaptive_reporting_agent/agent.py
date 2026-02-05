class AdaptiveReportingAgent:
    """
    A minimal example agent that intentionally fails once
    to demonstrate Hive's failure and adaptation loop.
    """

    def __init__(self):
        self.has_failed_once = False

    def run(self, input_data: dict):
        # Simulate a failure on the first run
        if not self.has_failed_once:
            self.has_failed_once = True
            raise ValueError("Required reporting data is missing")

        # On retry, succeed
        report = {
            "summary": "Weekly report generated successfully",
            "records_processed": len(input_data),
            "status": "success",
        }

        return report
