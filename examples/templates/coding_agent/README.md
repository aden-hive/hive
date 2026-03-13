# Coding Agent Template

An autonomous software engineer agent that takes a high-level request, plans the implementation, writes the code, and reviews it.

## 🧠 Workflow

1.  **Analyze**: Dissects the user request into requirements and tech stack.
2.  **Plan**: Creates a file structure and implementation steps.
3.  **Code**: Generates the actual code files.
4.  **Review**: Critiques the code against requirements.
5.  **Refine**: If the review fails, it loops back to the coding step with feedback.
6.  **Deliver**: Packages the final approved code.

## 🚀 Usage

```bash
python -m examples.templates.coding_agent '{"request": "Create a Python script that scrapes the top 10 news headlines from BBC"}'
```

## 🛠️ Customization

-   **Tools**: Add file system or git tools to `agent.py` to allow the agent to write directly to your disk or push commits.
-   **Review Logic**: Enhance the review node prompt to check for specific linting rules or security policies.
