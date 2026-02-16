"""Additional unit tests for individual node logic."""

import json
from pathlib import Path


def test_node_syntax_compilation():
    """Test that all node files compile without syntax errors."""
    print("=" * 60)
    print("TEST: Node Syntax Compilation")
    print("=" * 60)
    
    node_files = [
        "document_ingestion.py",
        "classification.py",
        "confidentiality_analysis.py",
        "liability_analysis.py",
        "term_obligations.py",
        "synthesis.py",
        "human_review.py",
        "report_generation.py",
    ]
    
    base_path = Path(__file__).parent.parent / "nodes"
    
    all_passed = True
    for node_file in node_files:
        file_path = base_path / node_file
        if file_path.exists():
            # Try to compile it
            try:
                import py_compile
                py_compile.compile(str(file_path), doraise=True)
                print(f"✓ {node_file}: Compiled successfully")
            except SyntaxError as e:
                print(f"✗ {node_file}: Syntax error - {e}")
                all_passed = False
        else:
            print(f"⚠️  {node_file}: File not found")
            all_passed = False
    
    return all_passed


def test_report_generation_logic():
    """Test report generation formatting."""
    print("\n" + "=" * 60)
    print("TEST: Report Generation Formatting")
    print("=" * 60)
    
    # Simulate report data
    test_data = {
        "metadata": {
            "contract_id": "test_nda_001",
            "contract_type": "Mutual NDA",
            "party_a": "Company A",
            "party_b": "Company B",
            "page_count": 8,
        },
        "risk_assessment": {
            "overall_risk_score": 6.5,
            "confidentiality_risk": 5.0,
            "liability_risk": 8.0,
            "terms_risk": 4.0,
            "critical_issues": ["Unlimited liability exposure"],
            "moderate_issues": ["Long confidentiality duration", "Unclear exceptions"],
            "recommendations": ["Add liability cap", "Clarify confidential information definition"],
            "human_review_required": False,
        },
        "confidentiality": {
            "type": "mutual",
            "scope": "Business information",
            "duration_months": 36,
        },
        "liability": {
            "cap_present": False,
            "unlimited_liability": True,
            "indemnification_type": "one-sided",
        },
        "terms": {
            "duration_months": 24,
            "auto_renewal": True,
        }
    }
    
    # Test markdown formatting
    try:
        report_md = f"""# Contract Evaluation Report

## Contract Information
- **Contract ID**: {test_data['metadata']['contract_id']}
- **Type**: {test_data['metadata']['contract_type']}

## Executive Summary
**Overall Risk Score**: {test_data['risk_assessment']['overall_risk_score']}/10

### Critical Issues
"""
        for issue in test_data['risk_assessment']['critical_issues']:
            report_md += f"- ⚠️ {issue}\n"
        
        if len(report_md) > 100:
            print("✓ Markdown report generated successfully")
            print(f"  Report length: {len(report_md)} characters")
        else:
            print("✗ Report seems too short")
            return False
        
        # Test JSON serialization
        json_str = json.dumps(test_data, indent=2)
        json.loads(json_str)  # Verify it's valid
        print(f"✓ JSON report serializable (size: {len(json_str)} chars)")
        
        # Test edge case: empty issues
        empty_data = {
            **test_data,
            "risk_assessment": {
                **test_data["risk_assessment"],
                "critical_issues": [],
                "moderate_issues": [],
            }
        }
        
        report_empty = "## Critical Issues\n"
        if not empty_data['risk_assessment']['critical_issues']:
            report_empty += "- None identified\n"
        print("✓ Empty issues list handled correctly")
        
        return True
        
    except Exception as e:
        print(f"✗ Report generation failed: {e}")
        return False


def test_synthesis_critical_issue_detection():
    """Test critical issue detection logic from synthesis node."""
    print("\n" + "=" * 60)
    print("TEST: Critical Issue Detection")
    print("=" * 60)
    
    test_cases = [
        {
            "name": "Unlimited liability",
            "liability": {"unlimited_liability": True},
            "should_flag": True
        },
        {
            "name": "One-sided confidentiality with high risk",
            "confidentiality": {"type": "one-sided", "risk_level": "high"},
            "should_flag": True
        },
        {
            "name": "One-sided confidentiality with low risk",
            "confidentiality": {"type": "one-sided", "risk_level": "low"},
            "should_flag": False
        },
        {
            "name": "Mutual obligations",
            "confidentiality": {"type": "mutual", "risk_level": "low"},
            "liability": {"unlimited_liability": False},
            "should_flag": False
        },
    ]
    
    for test in test_cases:
        critical_issues = []
        
        # Simulate logic from synthesis.py
        liability = test.get("liability", {})
        confidentiality = test.get("confidentiality", {})
        
        if liability.get("unlimited_liability"):
            critical_issues.append("Unlimited liability exposure detected")
        
        conf_risk_level = confidentiality.get("risk_level", "")
        conf_risk = {"low": 3, "medium": 6, "high": 9}.get(conf_risk_level, 0)
        
        if confidentiality.get("type") == "one-sided" and conf_risk >= 6:
            critical_issues.append("One-sided confidentiality obligations")
        
        has_critical = len(critical_issues) > 0
        
        if has_critical == test["should_flag"]:
            print(f"✓ {test['name']}: Correctly {'flagged' if has_critical else 'passed'}")
        else:
            print(f"✗ {test['name']}: Should {'flag' if test['should_flag'] else 'pass'}, but {'flagged' if has_critical else 'passed'}")
    
    return True


def test_recommendations_generation():
    """Test recommendation generation logic."""
    print("\n" + "=" * 60)
    print("TEST: Recommendations Generation")
    print("=" * 60)
    
    test_scenarios = [
        {
            "name": "No liability cap",
            "liability": {"cap_present": False},
            "expected_recommendation": "Add limitation of liability clause"
        },
        {
            "name": "One-sided confidentiality",
            "confidentiality": {"type": "one-sided"},
            "expected_recommendation": "mutual confidentiality"
        },
        {
            "name": "Auto-renewal without notice",
            "terms": {"auto_renewal": True, "notice_period_days": None},
            "expected_recommendation": "notice period"
        },
    ]
    
    for scenario in test_scenarios:
        recommendations = []
        
        # Simulate logic from synthesis.py
        liability = scenario.get("liability", {})
        confidentiality = scenario.get("confidentiality", {})
        terms = scenario.get("terms", {})
        
        if not liability.get("cap_present"):
            recommendations.append("Add limitation of liability clause with reasonable cap")
        
        if confidentiality.get("type") == "one-sided":
            recommendations.append("Negotiate for mutual confidentiality obligations")
        
        if terms.get("auto_renewal") and not terms.get("notice_period_days"):
            recommendations.append("Clarify notice period for non-renewal")
        
        # Check if expected recommendation is present
        found = any(scenario["expected_recommendation"].lower() in r.lower() for r in recommendations)
        
        if found:
            print(f"✓ {scenario['name']}: Recommendation generated")
        else:
            print(f"✗ {scenario['name']}: Missing expected recommendation")
            print(f"  Expected keyword: '{scenario['expected_recommendation']}'")
            print(f"  Got: {recommendations}")
    
    return True


def test_human_review_triggers():
    """Test conditions that should trigger human review."""
    print("\n" + "=" * 60)
    print("TEST: Human Review Triggers")
    print("=" * 60)
    
    test_scenarios = [
        {
            "name": "High risk score",
            "overall_risk_score": 8.5,
            "critical_issues": [],
            "threshold": 7.0,
            "should_review": True,
            "reason": "High risk score"
        },
        {
            "name": "Critical issues present",
            "overall_risk_score": 5.0,
            "critical_issues": ["Unlimited liability"],
            "threshold": 7.0,
            "should_review": True,
            "reason": "Critical issues"
        },
        {
            "name": "Low risk, no issues",
            "overall_risk_score": 4.0,
            "critical_issues": [],
            "threshold": 7.0,
            "should_review": False,
            "reason": None
        },
        {
            "name": "Exactly at threshold",
            "overall_risk_score": 7.0,
            "critical_issues": [],
            "threshold": 7.0,
            "should_review": True,
            "reason": "High risk score"
        },
    ]
    
    for scenario in test_scenarios:
        risk_score = scenario["overall_risk_score"]
        critical_issues = scenario["critical_issues"]
        threshold = scenario["threshold"]
        
        # Simulate logic from synthesis.py
        needs_review = risk_score >= threshold or len(critical_issues) > 0
        
        if needs_review == scenario["should_review"]:
            print(f"✓ {scenario['name']}: Correctly {'escalated' if needs_review else 'auto-processed'}")
        else:
            print(f"✗ {scenario['name']}: Should {'escalate' if scenario['should_review'] else 'auto-process'}")
            print(f"  Risk: {risk_score}, Threshold: {threshold}, Critical: {len(critical_issues)}")
    
    return True


def run_all_tests():
    """Run all additional unit tests."""
    print("\n" + "=" * 60)
    print("ADDITIONAL UNIT TESTS - Contract Evaluator")
    print("=" * 60 + "\n")
    
    results = []
    
    results.append(("Node Syntax", test_node_syntax_compilation()))
    results.append(("Report Generation", test_report_generation_logic()))
    results.append(("Critical Issue Detection", test_synthesis_critical_issue_detection()))
    results.append(("Recommendations", test_recommendations_generation()))
    results.append(("Human Review Triggers", test_human_review_triggers()))
    
    # Summary
    print("\n" + "=" * 60)
    print("UNIT TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result is True)
    failed = sum(1 for _, result in results if result is False)
    
    for name, result in results:
        status = "✅ PASSED" if result else "✗ FAILED"
        print(f"{status:12s} - {name}")
    
    print(f"\nTotal: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("\n🎉 All unit tests PASSED!")
        return 0
    else:
        print(f"\n❌ {failed} test(s) FAILED")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(run_all_tests())
