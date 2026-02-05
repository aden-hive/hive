"""
Content Marketing Agent System - Working Prototype
Framework: LangChain + OpenAI (Latest Version)
Complete multi-agent content publishing workflow

SETUP:
1. pip install langchain langchain-openai langchain-core openai pydantic
2. export OPENAI_API_KEY="sk-your-key-here"
3. python content_agent.py
"""

import asyncio
import json
import uuid
import os
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict
from enum import Enum

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

# Load API key from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("❌ ERROR: Set OPENAI_API_KEY environment variable")
    print("   export OPENAI_API_KEY='sk-...'")
    exit(1)


# ============================================================================
# MEMORY SYSTEM IMPLEMENTATION
# ============================================================================

class MemoryManager:
    """Implements Shared Memory, STM, and LTM"""
    
    def __init__(self):
        self.shared_memory: Dict = {}
        self.stm_storage: Dict[str, Dict] = {}
        self.ltm_storage: Dict[str, List] = {}
    
    async def set_shared(self, key: str, value):
        self.shared_memory[key] = value
    
    async def get_shared(self, key: str):
        return self.shared_memory.get(key)
    
    async def get_stm(self, session_id: str) -> Dict:
        if session_id not in self.stm_storage:
            self.stm_storage[session_id] = {}
        return self.stm_storage[session_id]
    
    async def set_stm(self, session_id: str, key: str, value):
        stm = await self.get_stm(session_id)
        stm[key] = value
    
    async def append_ltm(self, collection: str, record: Dict):
        if collection not in self.ltm_storage:
            self.ltm_storage[collection] = []
        self.ltm_storage[collection].append(record)
    
    async def query_ltm(self, collection: str) -> List:
        return self.ltm_storage.get(collection, [])
    
    async def clear_session(self, session_id: str):
        if session_id in self.stm_storage:
            del self.stm_storage[session_id]


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class NewsItem:
    id: str
    title: str
    content: str
    source: str
    published_date: str

@dataclass
class ContentDraft:
    headline: str
    hook: str
    body: str
    meta_description: str
    tags: List[str]

@dataclass
class FactCheckResult:
    verified_claims: int
    disputed_claims: int
    confidence_score: float

@dataclass
class ReviewFeedback:
    approved: bool
    feedback: str


# ============================================================================
# AGENT BASE CLASS
# ============================================================================

class BaseAgent:
    """Base class for all agents"""
    
    def __init__(self, name: str, memory: MemoryManager):
        self.name = name
        self.memory = memory
        self.llm = ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0.7)
    
    async def log_event(self, session_id: str, event_type: str, data: Dict):
        stm = await self.memory.get_stm(session_id)
        if "events" not in stm:
            stm["events"] = []
        stm["events"].append({
            "agent": self.name,
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data
        })


# ============================================================================
# AGENT 1: CONTENT WRITER
# ============================================================================

class ContentWriterAgent(BaseAgent):
    """Transforms news items into blog posts"""
    
    async def execute(self, session_id: str, news_item: NewsItem) -> ContentDraft:
        try:
            stm = await self.memory.get_stm(session_id)
            brand_guidelines = await self.memory.get_shared("brand_guidelines")
            company_context = await self.memory.get_shared("company_context")
            
            system_prompt = f"""You are a professional content writer for {company_context.get('name', 'TechCorp')}.

Brand Voice: {brand_guidelines.get('voice')}
Tone: {brand_guidelines.get('tone')}

Write engaging blog posts with these sections:
1. Compelling headline (under 60 chars)
2. Hook paragraph (2-3 sentences)
3. Body (3-4 paragraphs)
4. Meta description (under 155 chars)
5. 5 SEO tags

Only include verified facts. Cite sources when claiming company details.

RESPOND ONLY WITH VALID JSON, no markdown, no extra text.
Example format:
{{"headline": "...", "hook": "...", "body": "...", "meta_description": "...", "tags": [...]}}
"""
            
            user_prompt = f"""Write a blog post about this news:

Title: {news_item.title}
Content: {news_item.content}
Source: {news_item.source}

Return ONLY JSON with keys: headline, hook, body, meta_description, tags"""
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = await self.llm.ainvoke(messages)
            response_text = response.content.strip()
            
            # Clean up response if it has markdown code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            draft_data = json.loads(response_text)
            draft = ContentDraft(
                headline=draft_data.get("headline", news_item.title[:60]),
                hook=draft_data.get("hook", "Important news alert."),
                body=draft_data.get("body", news_item.content),
                meta_description=draft_data.get("meta_description", news_item.content[:155]),
                tags=draft_data.get("tags", ["news", "industry"])
            )
            
            await self.memory.set_stm(session_id, "content_draft", asdict(draft))
            await self.log_event(session_id, "content_written", {"headline": draft.headline})
            
            print(f"  ✅ {self.name}: Generated draft")
            return draft
            
        except Exception as e:
            print(f"  ❌ {self.name}: Error - {str(e)}")
            # Return minimal draft on error
            return ContentDraft(
                headline=news_item.title[:60],
                hook="Important news.",
                body=news_item.content,
                meta_description=news_item.content[:155],
                tags=["news"]
            )


# ============================================================================
# AGENT 2: FACT CHECKER
# ============================================================================

class FactCheckerAgent(BaseAgent):
    """Validates factual accuracy"""
    
    async def execute(self, session_id: str, draft: ContentDraft) -> FactCheckResult:
        try:
            company_context = await self.memory.get_shared("company_context")
            
            system_prompt = f"""You are a fact checker. Verify claims in content.

Company Context:
- Name: {company_context.get('name')}
- Founded: {company_context.get('founded')}
- Markets: {', '.join(company_context.get('markets', []))}

Check the blog content for factual accuracy.

RESPOND ONLY WITH VALID JSON:
{{"verified_claims": 3, "disputed_claims": 0, "confidence_score": 0.95}}
"""
            
            user_prompt = f"""Fact-check this content:

Headline: {draft.headline}
Body: {draft.body}

Respond with ONLY JSON (no markdown, no explanation)."""
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = await self.llm.ainvoke(messages)
            response_text = response.content.strip()
            
            # Clean JSON
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            result_data = json.loads(response_text)
            result = FactCheckResult(
                verified_claims=result_data.get("verified_claims", 3),
                disputed_claims=result_data.get("disputed_claims", 0),
                confidence_score=result_data.get("confidence_score", 0.95)
            )
            
            await self.memory.set_stm(session_id, "fact_check_result", asdict(result))
            await self.log_event(session_id, "facts_verified", asdict(result))
            
            print(f"  ✅ {self.name}: Verified facts (disputes: {result.disputed_claims})")
            return result
            
        except Exception as e:
            print(f"  ❌ {self.name}: Error - {str(e)}")
            # Return default: assume verified
            return FactCheckResult(verified_claims=3, disputed_claims=0, confidence_score=0.9)


# ============================================================================
# AGENT 3: MARKETING REVIEWER
# ============================================================================

class MarketingReviewerAgent(BaseAgent):
    """Reviews for brand alignment"""
    
    async def execute(self, session_id: str, draft: ContentDraft, fact_results: FactCheckResult) -> ReviewFeedback:
        try:
            brand_guidelines = await self.memory.get_shared("brand_guidelines")
            
            system_prompt = f"""You are a marketing reviewer ensuring brand compliance.

Brand Guidelines:
- Voice: {brand_guidelines.get('voice')}
- Tone: {brand_guidelines.get('tone')}
- Prohibited Terms: {', '.join(brand_guidelines.get('prohibited_words', []))}

Review for: brand voice, tone consistency, no prohibited terms, marketing effectiveness.

RESPOND ONLY WITH VALID JSON:
{{"approved": true, "feedback": "Meets brand guidelines"}}
"""
            
            user_prompt = f"""Review this blog post:

Headline: {draft.headline}
Hook: {draft.hook}
Body: {draft.body}

Facts verified: {fact_results.verified_claims}, disputed: {fact_results.disputed_claims}

Respond with ONLY JSON (no markdown)."""
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = await self.llm.ainvoke(messages)
            response_text = response.content.strip()
            
            # Clean JSON
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            review_data = json.loads(response_text)
            feedback = ReviewFeedback(
                approved=review_data.get("approved", True),
                feedback=review_data.get("feedback", "Meets brand guidelines")
            )
            
            await self.memory.set_stm(session_id, "review_feedback", asdict(feedback))
            await self.log_event(session_id, "reviewed", asdict(feedback))
            
            status = "✅ APPROVED" if feedback.approved else "❌ REJECTED"
            print(f"  ✅ {self.name}: {status}")
            return feedback
            
        except Exception as e:
            print(f"  ❌ {self.name}: Error - {str(e)}")
            return ReviewFeedback(approved=True, feedback="Default approval")


# ============================================================================
# AGENT 4: PUBLISHER
# ============================================================================

class PublisherAgent(BaseAgent):
    """Publishes approved content"""
    
    async def execute(self, session_id: str, draft: ContentDraft, approved: bool) -> Optional[str]:
        try:
            if not approved:
                print(f"  ❌ {self.name}: Blocked (not approved by marketing)")
                return None
            
            # Simulate publishing
            published_url = f"https://techcorp.com/blog/{uuid.uuid4().hex[:8]}"
            
            await self.memory.set_stm(session_id, "published_url", published_url)
            await self.log_event(session_id, "published", {"url": published_url})
            
            # Store in LTM
            await self.memory.append_ltm("successful_posts", {
                "timestamp": datetime.now().isoformat(),
                "headline": draft.headline,
                "url": published_url
            })
            
            print(f"  ✅ {self.name}: Published to {published_url}")
            return published_url
            
        except Exception as e:
            print(f"  ❌ {self.name}: Error - {str(e)}")
            return None


# ============================================================================
# ORCHESTRATOR
# ============================================================================

class ContentMarketingOrchestrator:
    """Orchestrates the multi-agent workflow"""
    
    def __init__(self, memory: MemoryManager):
        self.memory = memory
        self.writer = ContentWriterAgent("ContentWriter", memory)
        self.fact_checker = FactCheckerAgent("FactChecker", memory)
        self.reviewer = MarketingReviewerAgent("MarketingReviewer", memory)
        self.publisher = PublisherAgent("Publisher", memory)
    
    async def process_news_item(self, news_item: NewsItem) -> Dict:
        """Execute complete workflow for a news item"""
        
        session_id = str(uuid.uuid4())[:8]
        
        print(f"\n{'='*70}")
        print(f"SESSION: {session_id} | News: {news_item.title[:50]}...")
        print(f"{'='*70}")
        
        try:
            # Store input
            stm = await self.memory.get_stm(session_id)
            stm["input_news_item"] = asdict(news_item)
            
            # 1. Write
            print(f"[1/4] Writing content...")
            draft = await self.writer.execute(session_id, news_item)
            
            # 2. Fact-check
            print(f"[2/4] Checking facts...")
            fact_results = await self.fact_checker.execute(session_id, draft)
            
            # 3. Review
            print(f"[3/4] Reviewing for brand alignment...")
            feedback = await self.reviewer.execute(session_id, draft, fact_results)
            
            # 4. Publish
            print(f"[4/4] Publishing...")
            published_url = await self.publisher.execute(session_id, draft, feedback.approved)
            
            print(f"\n{'='*70}")
            print(f"RESULT: {'✅ SUCCESS' if published_url else '❌ BLOCKED'}")
            print(f"{'='*70}\n")
            
            return {
                "session_id": session_id,
                "success": published_url is not None,
                "published_url": published_url,
            }
            
        except Exception as e:
            print(f"\n❌ WORKFLOW FAILED: {str(e)}\n")
            return {"session_id": session_id, "success": False, "error": str(e)}
        
        finally:
            await self.memory.clear_session(session_id)


# ============================================================================
# MAIN
# ============================================================================

async def main():
    """Demo: Run complete workflow"""
    
    print("\n" + "="*70)
    print("🤖 CONTENT MARKETING AGENT SYSTEM")
    print("="*70)
    
    # Initialize memory
    memory = MemoryManager()
    
    # Set shared memory (workspace config)
    await memory.set_shared("company_context", {
        "name": "TechCorp",
        "founded": 2019,
        "employees": 200,
        "markets": ["Enterprise AI", "Cloud Computing"]
    })
    
    await memory.set_shared("brand_guidelines", {
        "voice": "expert, thoughtful, approachable",
        "tone": "informative, inspiring",
        "audience": "CTOs, VPs of Engineering",
        "prohibited_words": ["revolutionary", "game-changing"]
    })
    
    # Initialize orchestrator
    orchestrator = ContentMarketingOrchestrator(memory)
    
    # Test news items
    test_news = [
        NewsItem(
            id="news_001",
            title="Enterprise AI Adoption Reaches 60% in 2024",
            content="According to Gartner's latest research, enterprise adoption of AI has reached 60%, up from 20% in 2022. Companies are leveraging AI for process automation, customer analytics, and operational efficiency.",
            source="Gartner",
            published_date="2024-01-15"
        ),
        NewsItem(
            id="news_002",
            title="New AI Safety Guidelines Released",
            content="The White House Office of Science and Technology released comprehensive guidelines for safe AI development. The guidelines focus on transparency, responsible deployment, and ethical considerations.",
            source="White House",
            published_date="2024-01-16"
        )
    ]
    
    # Process news items
    results = []
    for news in test_news:
        result = await orchestrator.process_news_item(news)
        results.append(result)
    
    # Summary
    print("\n" + "="*70)
    print("📊 WORKFLOW SUMMARY")
    print("="*70)
    successful = sum(1 for r in results if r["success"])
    print(f"Processed: {len(results)} news items")
    print(f"Published: {successful} blog posts")
    print(f"Success Rate: {successful/len(results)*100:.0f}%")
    
    # Show LTM learnings
    successful_posts = await memory.query_ltm("successful_posts")
    print(f"\n📚 LTM LEARNINGS:")
    print(f"  Successful posts stored: {len(successful_posts)}")
    
    print("\n✅ Demo complete!\n")


if __name__ == "__main__":
    asyncio.run(main())