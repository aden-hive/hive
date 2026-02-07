"""LLM integration for analysis and summarization."""

import json
from openai import OpenAI

from app.config import settings

client = OpenAI(api_key=settings.openai_api_key)


def generate_summary(issue_text: str) -> str:
    """
    Generate a one-sentence summary of an issue.
    
    Args:
        issue_text: Full issue text (title + body + comments)
        
    Returns:
        One-sentence summary
    """
    response = client.chat.completions.create(
        model="gpt-4.1-nano",  # Use mini for summarization
        messages=[
            {
                "role": "system",
                "content": "Create a single concise sentence summarizing the GitHub issue."
            },
            {
                "role": "user",
                "content": f"Issue:\n{issue_text[:2000]}"  # Limit to avoid huge prompts
            }
        ],
        temperature=0.3,
        max_tokens=100
    )
    
    return response.choices[0].message.content.strip()


def analyze_novelty(candidate_text: str, similar_summaries: list[str]) -> dict:
    """
    Analyze if a candidate issue is novel compared to similar issues.
    
    Args:
        candidate_text: Full text of the new issue
        similar_summaries: List of summaries from similar past issues
        
    Returns:
        Dict with keys: is_semantic_duplicate, novelty_score, reasoning, one_sentence_summary
    """
    summaries_text = "\n".join([f"{i+1}. {s}" for i, s in enumerate(similar_summaries)])
    
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": """Analyze if this GitHub issue is novel compared to existing issues and assess its IMPACT.

Output JSON with:
- is_semantic_duplicate: boolean
- novelty_score: 1-10 (8+ only for NEW scope or critical UNKNOWN bugs)
- severity: "Current Critical", "High", "Medium", "Low"
- reasoning: brief explanation
- one_sentence_summary: concise summary"""
            },
            {
                "role": "user",
                "content": f"""Candidate Issue:
{candidate_text[:3000]}

Similar Past Issues:
{summaries_text}

Analyze:"""
            }
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )
    
    return json.loads(response.choices[0].message.content)



