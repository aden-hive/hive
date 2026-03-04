AGENT_NAME = "vendor_onboarding_policy"

REQUIRED_FIELDS = [
    "vendor_name",
    "country",
    "service_type",
    "annual_contract_value"
]

HIGH_RISK_COUNTRIES = [
    "North Korea",
    "Iran",
    "Syria"
]

RISK_THRESHOLDS = {
    "low": 30,
    "medium": 60,
    "high": 80
}
