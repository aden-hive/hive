#!/usr/bin/env python3
"""
Build Script for the Blog Writer Agent
---------------------------------------
Generates the exports/blog-writer-agent package using the GraphBuilder SDK.
"""

import os
from pathlib import Path

# Need to update sys.path if this is run from root or scripts dir
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core")))

from framework.builder.workflow import GraphBuilder

def build_agent():
    print("🚀 Building Blog Writer Agent...")
    
    # Create a workflow builder
    builder = GraphBuilder()

    # Define goal
    builder.set_goal(
        goal_id="blog-writer-goal",
        name="Blog Writer Agent",
        description="Research a topic and write a high-quality, structured blog post based on the findings.",
    )

    # Add success criteria
    builder.add_success_criterion(
        "thorough-research", "Conduct web research to gather factual information on the given topic."
    )
    builder.add_success_criterion(
        "structured-outline", "Create a structured outline covering the main points to be discussed."
    )
    builder.add_success_criterion(
        "final-blog-post", "Generate a complete, engaging blog post matching the specified tone."
    )

    # 1. Web Researcher Node
    builder.add_node(
        node_id="web-researcher",
        name="Web Research",
        description="Search the web for up-to-date information on the topic.",
        node_type="llm_tool_use",
        system_prompt="""You are a meticulous researcher. The user wants to write a blog post about the following topic: {topic}.
Your task:
1. Formulate search queries based on the topic to find the most relevant, up-to-date information.
2. Use the `web_search` tool to gather data.
3. Synthesize your findings into a comprehensive research summary. Provide key facts, statistics, and interesting insights that would make a great blog post.

Output your compiled research findings.""",
        tools=["web_search"],
        input_keys=["topic"],
        output_keys=["search_results"],
    )

    # 2. Outline Creator Node
    builder.add_node(
        node_id="outline-creator",
        name="Outline Creator",
        description="Create a blog post outline based on research.",
        node_type="llm_generate",
        system_prompt="""You are an expert content strategist.
Given the topic '{topic}' and the following research findings:
{search_results}

Create a detailed, logical outline for a blog post.
The tone of the blog post should be: {tone}.

Your outline should include:
- A catchy title
- Introduction
- 3 to 5 main body sections (with sub-bullets of what to cover)
- Conclusion

Respond ONLY with the outline.""",
        input_keys=["topic", "tone", "search_results"],
        output_keys=["outline"],
    )

    # 3. Blog Writer Node
    builder.add_node(
        node_id="blog-writer",
        name="Blog Writer",
        description="Write the final blog post.",
        node_type="llm_generate",
        system_prompt="""You are a professional blog writer. Here is everything you need:
Topic: {topic}
Tone: {tone}
Target Word Count: {word_count}

Research Findings:
{search_results}

Article Outline:
{outline}

Your task is to write the complete, full-length blog post.
Follow the outline strictly. Adopt the specified tone. Ensure the structure flows logically, use headings/subheadings (Markdown format), and write engaging content. Make sure to hit the targeted word count as closely as possible.

Return the final blog post in Markdown format.""",
        input_keys=["topic", "tone", "word_count", "search_results", "outline"],
        output_keys=["blog_post"],
    )

    # Connect nodes strictly sequentially
    builder.add_edge("web-researcher", "outline-creator")
    builder.add_edge("outline-creator", "blog-writer")

    # Set entry and terminal nodes
    builder.set_entry("web-researcher")
    builder.set_terminal("blog-writer")

    # Export
    export_path = Path("exports/blog-writer-agent")
    export_path.mkdir(parents=True, exist_ok=True)
    builder.export(export_path)
    
    print(f"✅ Blog Writer Agent successfully exported to {export_path}/")

if __name__ == "__main__":
    build_agent()
