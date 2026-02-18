"""
Customer Support Agent Template for Hive

A production-ready self-evolving agent that handles customer support inquiries
by matching questions to a knowledge base, detecting sentiment, and escalating
when necessary.

Author: Habeeb Jimoh
Date: February 16, 2026
"""

from typing import Dict, List, Optional, Tuple
import json
from datetime import datetime


class CustomerSupportAgent:
    """
    A self-evolving customer support agent built on Hive.
    
    This agent:
    1. Classifies customer inquiry intent
    2. Matches to knowledge base articles  
    3. Detects customer sentiment
    4. Decides whether to respond or escalate
    5. Learns from resolution outcomes to improve over time
    """
    
    def __init__(self, config: Dict):
        """
        Initialize the Customer Support Agent.
        
        Args:
            config: Configuration dictionary containing:
                - knowledge_base_path: Path to FAQ/knowledge base JSON
                - escalation_threshold: Confidence threshold for escalation (0-1)
                - tone: Response tone (formal/casual/friendly)
                - max_response_length: Maximum words in response
        """
        self.config = config
        self.knowledge_base = self._load_knowledge_base(
            config.get('knowledge_base_path', 'knowledge_base.json')
        )
        self.escalation_threshold = config.get('escalation_threshold', 0.7)
        self.tone = config.get('tone', 'friendly')
        self.max_response_length = config.get('max_response_length', 150)
        
        # Evolution tracking
        self.interaction_history = []
        self.resolution_outcomes = {
            'resolved': 0,
            'escalated': 0,
            'customer_satisfied': 0,
            'customer_dissatisfied': 0
        }
        
    def _load_knowledge_base(self, path: str) -> List[Dict]:
        """Load knowledge base from JSON file."""
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            # Return default knowledge base for demo purposes
            return [
                {
                    "id": "kb_001",
                    "category": "billing",
                    "question": "How do I update my payment method?",
                    "answer": "You can update your payment method by going to Settings > Billing > Payment Methods. Click 'Add Payment Method' and follow the prompts.",
                    "keywords": ["payment", "billing", "credit card", "update payment"]
                },
                {
                    "id": "kb_002",
                    "category": "account",
                    "question": "How do I reset my password?",
                    "answer": "Click 'Forgot Password' on the login page. Enter your email address and we'll send you a reset link. The link is valid for 24 hours.",
                    "keywords": ["password", "reset", "forgot password", "login"]
                },
                {
                    "id": "kb_003",
                    "category": "features",
                    "question": "How do I export my data?",
                    "answer": "Navigate to Settings > Data & Privacy > Export Data. Select the data you want to export and click 'Start Export'. You'll receive an email when your export is ready.",
                    "keywords": ["export", "data", "download", "backup"]
                }
            ]
    
    def handle_inquiry(self, customer_message: str, customer_id: Optional[str] = None) -> Dict:
        """
        Main method to handle a customer support inquiry.
        
        Args:
            customer_message: The customer's question or message
            customer_id: Optional customer identifier for tracking
            
        Returns:
            Dictionary containing:
                - action: 'respond' or 'escalate'
                - response: Agent's response (if action is 'respond')
                - escalation_reason: Reason for escalation (if action is 'escalate')
                - confidence: Confidence score (0-1)
                - matched_article: KB article that was matched (if any)
        """
        # Step 1: Classify intent
        intent = self._classify_intent(customer_message)
        
        # Step 2: Detect sentiment
        sentiment = self._detect_sentiment(customer_message)
        
        # Step 3: Match to knowledge base
        matched_article, confidence = self._match_knowledge_base(customer_message)
        
        # Step 4: Decide action
        if sentiment['is_frustrated'] and sentiment['frustration_level'] > 0.7:
            # Escalate frustrated customers immediately
            return {
                'action': 'escalate',
                'escalation_reason': 'Customer shows high frustration',
                'confidence': 1.0,
                'sentiment': sentiment,
                'intent': intent
            }
        
        if confidence < self.escalation_threshold:
            # Low confidence - escalate
            return {
                'action': 'escalate',
                'escalation_reason': f'Low confidence match ({confidence:.2f})',
                'confidence': confidence,
                'sentiment': sentiment,
                'intent': intent
            }
        
        # Step 5: Generate response
        response = self._generate_response(
            matched_article=matched_article,
            sentiment=sentiment,
            intent=intent
        )
        
        # Track interaction for evolution
        interaction = {
            'timestamp': datetime.now().isoformat(),
            'customer_id': customer_id,
            'message': customer_message,
            'action': 'respond',
            'confidence': confidence,
            'matched_article_id': matched_article['id'] if matched_article else None
        }
        self.interaction_history.append(interaction)
        
        return {
            'action': 'respond',
            'response': response,
            'confidence': confidence,
            'matched_article': matched_article,
            'sentiment': sentiment,
            'intent': intent
        }
    
    def _classify_intent(self, message: str) -> Dict:
        """Classify the intent of the customer message."""
        message_lower = message.lower()
        
        # Simple keyword-based classification
        if any(word in message_lower for word in ['bill', 'charge', 'payment', 'credit card', 'invoice']):
            return {'category': 'billing', 'confidence': 0.85}
        elif any(word in message_lower for word in ['password', 'login', 'account', 'access', 'sign in']):
            return {'category': 'account', 'confidence': 0.85}
        elif any(word in message_lower for word in ['how do i', 'how to', 'can i', 'feature', 'export']):
            return {'category': 'features', 'confidence': 0.80}
        elif any(word in message_lower for word in ['bug', 'error', 'broken', 'not working', "doesn't work"]):
            return {'category': 'technical_issue', 'confidence': 0.85}
        else:
            return {'category': 'general', 'confidence': 0.50}
    
    def _detect_sentiment(self, message: str) -> Dict:
        """Detect customer sentiment and frustration level."""
        message_lower = message.lower()
        
        frustration_keywords = [
            'frustrated', 'angry', 'unacceptable', 'terrible', 'awful',
            'worst', 'horrible', 'useless', 'ridiculous', 'pathetic',
            'urgent', 'immediately', 'asap', 'now', 'waiting forever'
        ]
        
        positive_keywords = [
            'thanks', 'thank you', 'appreciate', 'helpful', 'great',
            'excellent', 'perfect', 'wonderful', 'love', 'amazing'
        ]
        
        frustration_count = sum(1 for keyword in frustration_keywords if keyword in message_lower)
        positive_count = sum(1 for keyword in positive_keywords if keyword in message_lower)
        
        has_exclamation = '!' in message
        has_caps = any(word.isupper() and len(word) > 3 for word in message.split())
        
        frustration_level = min(1.0, (frustration_count * 0.3) + (0.2 if has_exclamation else 0) + (0.3 if has_caps else 0))
        
        return {
            'is_frustrated': frustration_level > 0.5,
            'frustration_level': frustration_level,
            'is_positive': positive_count > 0,
            'sentiment_score': positive_count - frustration_count
        }
    
    def _match_knowledge_base(self, message: str) -> Tuple[Optional[Dict], float]:
        """Match customer message to knowledge base articles."""
        message_lower = message.lower()
        best_match = None
        best_score = 0.0
        
        for article in self.knowledge_base:
            keyword_matches = sum(
                1 for keyword in article['keywords']
                if keyword.lower() in message_lower
            )
            
            score = keyword_matches / len(article['keywords']) if article['keywords'] else 0
            
            if score > best_score:
                best_score = score
                best_match = article
        
        return best_match, best_score
    
    def _generate_response(self, matched_article: Optional[Dict], sentiment: Dict, intent: Dict) -> str:
        """Generate a response based on matched article, sentiment, and intent."""
        if not matched_article:
            return self._generate_fallback_response(sentiment)
        
        response_parts = []
        
        if sentiment['is_frustrated']:
            response_parts.append("I understand this is frustrating.")
        
        answer = matched_article['answer']
        
        if self.tone == 'formal':
            response_parts.append(answer)
        elif self.tone == 'casual':
            response_parts.append(f"Here's what you need to do: {answer}")
        else:  # friendly
            response_parts.append(f"I can help with that! {answer}")
        
        if not sentiment['is_frustrated']:
            response_parts.append("Let me know if you need anything else!")
        else:
            response_parts.append("Is there anything else I can help clarify?")
        
        full_response = " ".join(response_parts)
        
        words = full_response.split()
        if len(words) > self.max_response_length:
            full_response = " ".join(words[:self.max_response_length]) + "..."
        
        return full_response
    
    def _generate_fallback_response(self, sentiment: Dict) -> str:
        """Generate a fallback response when no good match is found."""
        if sentiment['is_frustrated']:
            return "I understand your frustration. Let me connect you with a team member who can help you right away."
        else:
            return "I want to make sure I give you the right information. Let me connect you with a team member who specializes in this area."
    
    def record_outcome(self, interaction_id: str, outcome: str, customer_satisfied: bool = True):
        """Record the outcome of an interaction for self-evolution."""
        self.resolution_outcomes[outcome] = self.resolution_outcomes.get(outcome, 0) + 1
        
        if customer_satisfied:
            self.resolution_outcomes['customer_satisfied'] += 1
        else:
            self.resolution_outcomes['customer_dissatisfied'] += 1
        
        if len(self.interaction_history) % 10 == 0:
            self._evolve()
    
    def _evolve(self):
        """Self-evolution logic: Analyze outcomes and adjust thresholds."""
        total_interactions = sum(self.resolution_outcomes.values())
        
        if total_interactions < 10:
            return
        
        resolved_rate = self.resolution_outcomes['resolved'] / total_interactions
        escalation_rate = self.resolution_outcomes['escalated'] / total_interactions
        satisfaction_rate = self.resolution_outcomes['customer_satisfied'] / total_interactions
        
        if escalation_rate > 0.4 and satisfaction_rate > 0.8:
            self.escalation_threshold = max(0.5, self.escalation_threshold - 0.05)
            print(f"[EVOLUTION] Lowered escalation threshold to {self.escalation_threshold:.2f}")
        
        elif satisfaction_rate < 0.6:
            self.escalation_threshold = min(0.9, self.escalation_threshold + 0.05)
            print(f"[EVOLUTION] Raised escalation threshold to {self.escalation_threshold:.2f}")
    
    def get_metrics(self) -> Dict:
        """Get performance metrics for this agent."""
        total = sum(self.resolution_outcomes.values())
        
        if total == 0:
            return {
                'total_interactions': 0,
                'resolution_rate': 0,
                'escalation_rate': 0,
                'satisfaction_rate': 0
            }
        
        return {
            'total_interactions': total,
            'resolution_rate': self.resolution_outcomes['resolved'] / total,
            'escalation_rate': self.resolution_outcomes['escalated'] / total,
            'satisfaction_rate': self.resolution_outcomes['customer_satisfied'] / total,
            'current_escalation_threshold': self.escalation_threshold
        }


if __name__ == "__main__":
    config = {
        'escalation_threshold': 0.7,
        'tone': 'friendly',
        'max_response_length': 150
    }
    
    agent = CustomerSupportAgent(config)
    
    test_messages = [
        "How do I reset my password?",
        "I'm REALLY frustrated! My payment isn't going through and I need access NOW!",
        "Can you help me export my data?",
        "Your service is terrible and nothing works!",
        "Thanks for your help earlier, one more question - how do I update my credit card?"
    ]
    
    print("Customer Support Agent Demo")
    print("=" * 60)
    
    for i, message in enumerate(test_messages, 1):
        print(f"\n[Customer {i}]: {message}")
        result = agent.handle_inquiry(message, customer_id=f"cust_{i}")
        
        print(f"[Action]: {result['action']}")
        print(f"[Confidence]: {result['confidence']:.2f}")
        
        if result['action'] == 'respond':
            print(f"[Agent]: {result['response']}")
        else:
            print(f"[Escalation Reason]: {result['escalation_reason']}")
        
        if result['action'] == 'respond':
            agent.record_outcome(f"interaction_{i}", 'resolved', customer_satisfied=True)
        else:
            agent.record_outcome(f"interaction_{i}", 'escalated', customer_satisfied=True)
    
    print("\n" + "=" * 60)
    print("Agent Metrics:")
    metrics = agent.get_metrics()
    for key, value in metrics.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.2%}" if value <= 1 else f"  {key}: {value:.2f}")
        else:
            print(f"  {key}: {value}")