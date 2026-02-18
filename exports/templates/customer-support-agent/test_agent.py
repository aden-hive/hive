"""
Test suite for Customer Support Agent template

Run with: python test_agent.py
"""

import json
from agent import CustomerSupportAgent


def test_intent_classification():
    """Test that intent classification works correctly."""
    config = {'escalation_threshold': 0.7, 'tone': 'friendly'}
    agent = CustomerSupportAgent(config)
    
    test_cases = [
        ("How do I reset my password?", "account"),
        ("I need to update my credit card", "billing"),
        ("Can I export my data?", "features"),
        ("This is broken and not working!", "technical_issue"),
    ]
    
    print("Testing Intent Classification...")
    for message, expected_category in test_cases:
        intent = agent._classify_intent(message)
        status = "✓" if intent['category'] == expected_category else "✗"
        print(f"  {status} '{message}' → {intent['category']} (expected: {expected_category})")


def test_sentiment_detection():
    """Test sentiment detection and frustration levels."""
    config = {'escalation_threshold': 0.7, 'tone': 'friendly'}
    agent = CustomerSupportAgent(config)
    
    test_cases = [
        ("How do I reset my password?", False),
        ("I'm REALLY frustrated! This is UNACCEPTABLE!", True),
        ("Thanks for your help!", False),
        ("This is urgent and I need help NOW!", True),
    ]
    
    print("\nTesting Sentiment Detection...")
    for message, should_be_frustrated in test_cases:
        sentiment = agent._detect_sentiment(message)
        is_frustrated = sentiment['is_frustrated']
        status = "✓" if is_frustrated == should_be_frustrated else "✗"
        level = sentiment['frustration_level']
        print(f"  {status} '{message}' → Frustrated: {is_frustrated} (level: {level:.2f})")


def test_knowledge_base_matching():
    """Test knowledge base matching accuracy."""
    config = {'escalation_threshold': 0.7, 'tone': 'friendly'}
    agent = CustomerSupportAgent(config)
    
    test_cases = [
        ("How do I reset my password?", "kb_002", True),
        ("I need to change my credit card info", "kb_001", True),
        ("Can I download my data?", "kb_003", True),
        ("Why is the sky blue?", None, False),
    ]
    
    print("\nTesting Knowledge Base Matching...")
    for message, expected_id, should_match in test_cases:
        matched_article, confidence = agent._match_knowledge_base(message)
        
        if should_match:
            matched_id = matched_article['id'] if matched_article else None
            status = "✓" if matched_id == expected_id else "✗"
            print(f"  {status} '{message}' → {matched_id} (confidence: {confidence:.2f})")
        else:
            status = "✓" if confidence < 0.5 else "✗"
            print(f"  {status} '{message}' → No match (confidence: {confidence:.2f})")


def test_escalation_logic():
    """Test that escalation logic works correctly."""
    config = {'escalation_threshold': 0.7, 'tone': 'friendly'}
    agent = CustomerSupportAgent(config)
    
    test_cases = [
        ("How do I reset my password?", "respond"),
        ("I'm FURIOUS about this!", "escalate"),
        ("Something isn't working", "escalate"),
        ("Thanks, how do I export data?", "respond"),
    ]
    
    print("\nTesting Escalation Logic...")
    for message, expected_action in test_cases:
        result = agent.handle_inquiry(message)
        actual_action = result['action']
        status = "✓" if actual_action == expected_action else "✗"
        print(f"  {status} '{message}' → {actual_action} (expected: {expected_action})")


def test_evolution_behavior():
    """Test that evolution adjusts thresholds correctly."""
    config = {'escalation_threshold': 0.7, 'tone': 'friendly'}
    agent = CustomerSupportAgent(config)
    
    print("\nTesting Evolution Behavior...")
    initial_threshold = agent.escalation_threshold
    print(f"  Initial threshold: {initial_threshold:.2f}")
    
    for i in range(15):
        agent.record_outcome(f"int_{i}", 'resolved', customer_satisfied=True)
    
    new_threshold = agent.escalation_threshold
    print(f"  After 15 successful resolutions: {new_threshold:.2f}")
    
    if new_threshold < initial_threshold:
        print("  ✓ Threshold decreased (agent is more autonomous)")
    else:
        print("  ✗ Threshold should have decreased")
    
    agent = CustomerSupportAgent(config)
    for i in range(15):
        agent.record_outcome(f"int_{i}", 'resolved', customer_satisfied=False)
    
    new_threshold_2 = agent.escalation_threshold
    print(f"  After 15 low-satisfaction interactions: {new_threshold_2:.2f}")
    
    if new_threshold_2 > initial_threshold:
        print("  ✓ Threshold increased (agent is more conservative)")
    else:
        print("  ✗ Threshold should have increased")


def test_with_example_conversations():
    """Test agent with the provided example conversations."""
    config = {'escalation_threshold': 0.7, 'tone': 'friendly'}
    agent = CustomerSupportAgent(config)
    
    print("\nTesting with Example Conversations...")
    
    try:
        with open('example_conversations.json', 'r') as f:
            data = json.load(f)
        
        passed = 0
        failed = 0
        
        for example in data['examples']:
            message = example['customer_message']
            expected_action = example['expected_action']
            
            result = agent.handle_inquiry(message)
            actual_action = result['action']
            
            if actual_action == expected_action:
                print(f"  ✓ {example['id']}: {example['scenario']}")
                passed += 1
            else:
                print(f"  ✗ {example['id']}: {example['scenario']}")
                print(f"    Expected: {expected_action}, Got: {actual_action}")
                failed += 1
        
        print(f"\n  Results: {passed} passed, {failed} failed")
    except FileNotFoundError:
        print("  ⚠ example_conversations.json not found - skipping this test")


def run_all_tests():
    """Run all test suites."""
    print("=" * 60)
    print("Customer Support Agent - Test Suite")
    print("=" * 60)
    
    test_intent_classification()
    test_sentiment_detection()
    test_knowledge_base_matching()
    test_escalation_logic()
    test_evolution_behavior()
    test_with_example_conversations()
    
    print("\n" + "=" * 60)
    print("Tests Complete")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()