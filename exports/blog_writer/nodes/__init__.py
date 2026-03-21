"""Node definitions for Blog Writer Agent."""

from framework.graph import NodeSpec

# IMPORTANT: set_output value must always be a STRING.
# Keep values short and single-line where possible.

# Node 1: Write Post
# Does research, outlining, and writing in one shot.
write_post_node = NodeSpec(
    id="write-post",
    name="Write Post",
    description="Research the topic and write a complete blog post",
    node_type="event_loop",
    input_keys=["topic"],
    output_keys=["draft_content", "post_title"],
    system_prompt="""\
You are an expert blog writer. Given a topic, write a complete, well-structured blog post.

Your blog post should:
- Be 800-1200 words
- Have a compelling title
- Include an introduction with a strong hook
- Have 3-4 main sections with H2 headings
- Use short paragraphs (2-3 sentences)
- End with a clear call-to-action conclusion
- Be informative and include relevant statistics or examples

Write the full blog post, then store it using set_output.
The value for draft_content must be the COMPLETE markdown blog post as a single string.

Call set_output for each output key:
- set_output("post_title", "The Blog Post Title")
- set_output("draft_content", "# Title\n\n## Introduction\n\nFull post content here...")
""",
    tools=[],
)

# Node 2: Save Post (function node — pure Python, no LLM)
save_post_node = NodeSpec(
    id="save-post",
    name="Save Post",
    description="Write the blog post to a markdown file on disk",
    node_type="function",
    function="save_blog_post",
    input_keys=["draft_content", "post_title"],
    output_keys=["file_path"],
)

def save_blog_post(draft_content: str, post_title: str) -> str:
    """Write the blog post to a markdown file and return the path."""
    import re
    from datetime import date
    from pathlib import Path

    date_str = date.today().strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-z0-9]+", "-", post_title.lower()).strip("-")[:60]
    file_path = Path("blog_posts") / f"blog_{date_str}_{slug}.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(draft_content, encoding="utf-8")

    return str(file_path)


__all__ = [
    "write_post_node",
    "save_post_node",
    "save_blog_post",
]
