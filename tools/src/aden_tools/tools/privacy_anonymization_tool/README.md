# Privacy Anonymization Tool

A privacy-preserving data anonymization MCP tool for the Hive agent framework.

## Features

- **K-Anonymity**: Generalization and suppression techniques to ensure records are indistinguishable within equivalence classes
- **Pseudonymization**: Replace sensitive values with consistent pseudonyms using SHA-256 hashing
- **Differential Privacy**: Add calibrated noise to numeric values for statistical privacy
- **PII Detection**: Automatically detect potential PII fields in your data
- **Compliance Checking**: Verify k-anonymity requirements and assess re-identification risk

## Installation

No additional dependencies required beyond the core Hive framework (uses standard Python libraries).

## Tools

### `anonymize_data`

Anonymize sensitive data using various privacy-preserving methods.

```python
# Example: Anonymize patient records with k-anonymity
result = anonymize_data(
    data={
        "name": "John Doe",
        "age": 35,
        "diagnosis": "Flu",
        "zip": "12345"
    },
    sensitive_fields=["name", "diagnosis"],
    method="k_anonymity",
    quasi_identifiers=["age", "zip"]
)
```

**Methods:**
- `k_anonymity`: Generalizes quasi-identifiers and suppresses sensitive fields
- `pseudonymization`: Replaces values with consistent hashed pseudonyms
- `differential_privacy`: Adds calibrated noise to numeric values

### `check_privacy_compliance`

Check if data satisfies k-anonymity privacy requirements.

```python
result = check_privacy_compliance(
    data=[
        {"age": "30-35", "zip": "123**", "gender": "M"},
        {"age": "30-35", "zip": "123**", "gender": "M"},
        {"age": "30-35", "zip": "123**", "gender": "M"},
    ],
    quasi_identifiers=["age", "zip", "gender"],
    k=3
)
```

### `detect_pii_fields`

Automatically detect potential PII fields in data.

```python
result = detect_pii_fields({
    "email": "user@example.com",
    "ssn": "123-45-6789",
    "name": "John Doe"
})
```

## Regulatory Compliance

### GDPR (General Data Protection Regulation - EU)

This tool supports GDPR compliance by:

- **Data Minimization** (Art. 5(1)(c)): Anonymization reduces data to what's necessary
- **Pseudonymization** (Art. 4(5)): Built-in pseudonymization support for processing
- **Privacy by Design** (Art. 25): Integrated anonymization in data workflows

**Note**: Fully anonymized data falls outside GDPR scope. Pseudonymized data remains subject to GDPR.

### HIPAA (Health Insurance Portability and Accountability Act - US)

Supports HIPAA Safe Harbor method by removing or generalizing:

- Names
- Geographic data (ZIP codes generalized to 3 digits)
- Dates (generalized to year)
- Other direct identifiers

**Note**: This tool assists with de-identification but does not guarantee HIPAA compliance. Consult legal experts for compliance validation.

### CCPA (California Consumer Privacy Act)

Supports CCPA compliance through:

- Data anonymization for analytics and sharing
- De-identification of consumer data
- PII detection for data inventory

## Best Practices

1. **Identify Quasi-Identifiers**: Fields like age, ZIP, gender can identify individuals when combined
2. **Choose Appropriate k**: Higher k values provide more privacy but reduce data utility
3. **Validate Compliance**: Always run `check_privacy_compliance` after anonymization
4. **Consider Context**: Different use cases may require different anonymization methods
5. **Document Process**: Keep records of anonymization methods used for audit purposes

## Example Workflows

### Healthcare Data Processing

```python
# 1. Detect PII fields
pii_result = detect_pii_fields(patient_records)

# 2. Anonymize with k-anonymity
anon_result = anonymize_data(
    data=patient_records,
    sensitive_fields=["name", "ssn", "diagnosis"],
    method="k_anonymity",
    quasi_identifiers=["age", "zip", "gender"],
    k=5
)

# 3. Verify compliance
compliance = check_privacy_compliance(
    data=anon_result["anonymized_data"],
    quasi_identifiers=["age", "zip", "gender"],
    k=5
)
```

### Customer Data Analytics

```python
# Pseudonymize customer identifiers for analytics
result = anonymize_data(
    data=customer_data,
    sensitive_fields=["email", "customer_id", "phone"],
    method="pseudonymization",
    salt="unique_analytics_salt_2024"
)
```

## Limitations

- K-anonymity is susceptible to homogeneity and background knowledge attacks
- Differential privacy noise may affect numeric accuracy
- Pseudonymization is reversible with the salt value
- Consider l-diversity or t-closeness for stronger privacy guarantees

## References

- [k-Anonymity: A Model for Protecting Privacy](https://dataprivacylab.org/dataprivacy/projects/kanonymity/kanonymity.pdf)
- [Differential Privacy](https://www.cis.upenn.edu/~aaroth/Papers/privacybook.pdf)
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html)
- [GDPR Official Text](https://gdpr.eu/)
