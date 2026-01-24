"""
Simple example: Using the Content Marketing Agent
"""

import asyncio
from agent import (
    NewsItem,
    MemoryManager,
    ContentMarketingOrchestrator
)


async def simple_example():
    """Process a single news item"""
    
    # Initialize
    memory = MemoryManager()
    
    # Set up shared memory
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
    
    # Create orchestrator
    orchestrator = ContentMarketingOrchestrator(memory)
    
    # Define a news item
    news = NewsItem(
        id="news_custom_001",
        title="Enterprise AI Adoption Reaches 60% in 2024",
        content="According to Gartner's latest research, enterprise adoption of AI has reached 60%. Companies are leveraging AI for automation, analytics, and efficiency.",
        source="Gartner",
        published_date="2024-01-15"
    )
    
    # Process the news item
    print("Processing single news item...\n")
    result = await orchestrator.process_news_item(news)
    
    # Display results
    print(f"Success: {result['success']}")
    if result['published_url']:
        print(f"Published URL: {result['published_url']}")
    else:
        print(f"Error: {result.get('error', 'Unknown error')}")
    
    # Show LTM learnings
    successful_posts = await memory.query_ltm("successful_posts")
    print(f"\nSuccessful posts in LTM: {len(successful_posts)}")
    for post in successful_posts:
        print(f"  - {post['headline']} ({post['url']})")


async def batch_processing_example():
    """Process multiple news items"""
    
    memory = MemoryManager()
    
    await memory.set_shared("company_context", {
        "name": "TechCorp",
        "founded": 2019,
        "employees": 200,
        "markets": ["Enterprise AI"]
    })
    
    await memory.set_shared("brand_guidelines", {
        "voice": "expert, thoughtful",
        "tone": "informative",
        "audience": "CTOs",
        "prohibited_words": ["revolutionary"]
    })
    
    orchestrator = ContentMarketingOrchestrator(memory)
    
    # Multiple news items
    news_items = [
        NewsItem(
            id="batch_001",
            title="AI Safety Guidelines Released",
            content="New guidelines focus on responsible AI deployment...",
            source="White House",
            published_date="2024-01-16"
        ),
        NewsItem(
            id="batch_002",
            title="Enterprise Cloud Computing Trends",
            content="Multi-cloud strategies becoming standard...",
            source="Forrester",
            published_date="2024-01-17"
        )
    ]
    
    print("Processing batch of news items...\n")
    results = []
    for news in news_items:
        result = await orchestrator.process_news_item(news)
        results.append(result)
    
    # Summary
    successful = sum(1 for r in results if r["success"])
    print(f"\nBatch Summary:")
    print(f"  Processed: {len(results)}")
    print(f"  Published: {successful}")
    print(f"  Success Rate: {successful/len(results)*100:.0f}%")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        asyncio.run(batch_processing_example())
    else:
        asyncio.run(simple_example())