Part 1: Join the Aden Community (10 points)
Task 1.1: Star the Repository ⭐
Show your support by starring our repo!
1.	Go to github.com/adenhq/hive
2.	Click the Star button in the top right
3.	Screenshot your starred repo (showing the star count)-> https://imgur.com/a/yNmvW82
 
 
Task 1.2: Watch the Repository 👁️
Stay updated with our latest changes!
1.	Click the Watch button
2.	Select "All Activity" to get notifications
3.	Screenshot your watch settings-> https://imgur.com/a/I5JIQwo
 
Task 1.3: Fork the Repository 🍴
Create your own copy to experiment with!
1.	Click the Fork button
2.	Keep the default settings and create the fork
3.	Screenshot your forked repository-> https://imgur.com/a/iMwsNi1
 
Task 1.4: Join Discord 💬
Connect with our community!
1.	Join our Discord server
2.	Introduce yourself in #introductions
3.	Screenshot your introduction message-> https://imgur.com/a/ELrJXvY
 

________________________________________
✅ Task 2.1: README Scavenger Hunt 🔍
1.	What are the three LLM providers Aden supports out of the box?
Aden supports OpenAI (GPT-4/GPT-4o), Anthropic (Claude models), and Google Gemini out of the box. (GitHub)
2.	How many MCP tools does the Hive Control Plane provide?
The Hive Control Plane provides 19 MCP tools for budget management, agent status, and policy control. (GitHub)
3.	What is the name of the frontend dashboard?
Honeycomb is the frontend dashboard of the Aden Hive platform. It is a web-based user interface built to help developers observe, control, and understand AI agents running inside the Hive system.
Instead of interacting only through code or logs, Honeycomb provides visual, real-time insight into how agents behave and improve over time.
4.	In the “How It Works” section, what is Step 5?
After the agents execute a task, Aden does not stop at success or failure.
In Step 5, the system:
Collects failure data (errors, bad outputs, unmet goals)
Analyzes what went wrong
Evolves the agent graph based on those failures
Redeploys the improved graph automatically
This is what makes Aden different from traditional agent frameworks — it is self-improving by design.

5.	What city is Aden made with passion in?
From related Aden documentation, Aden is crafted with passion in San Francisco, CA. (GitHub)
________________________________________


✅ Task 2.2: Architecture Quiz 🏗️
1.	What are the three databases in the Storage Layer?
The Storage Layer consists of three databases: State DB, Memory DB, and Metrics DB. The Storage Layer includes a State DB for execution state, a Memory DB for shared agent context, and a Metrics DB for performance and observability data.
2.	Name two components inside an “SDK-Wrapped Node.
Two components inside an SDK-Wrapped Node are the LLM and MCP Tools.An SDK-Wrapped Node includes an LLM for reasoning and a set of MCP tools that allow the agent to interact with memory, policies, and external systems.

3.	What connects the Control Plane to the Dashboard?
The architecture connects the Control Plane to the Dashboard via real-time streaming & event APIs/WebSockets for observability and execution feedback. (GitHub)
4.	Where does “Failure Data” flow to in the diagram?
In the architecture diagram for Aden Hive, "Failure Data" flows from the Runtime (specifically the execution of agents) back into the Build phase to enable the framework's self-healing and evolutionary capabilities.
According to the documentation and the "Aden Architecture" diagram:
Capture: When an agent execution fails or encounters issues, the framework captures the failure data (including errors, logs, and state).
Storage: This data is sent to the Infrastructure layer (specifically FileStorage under "Runs & Decisions").
Feedback Loop: From the storage, the data flows back to the Build stage via a path labeled "Analyze & Improve."
Action: The Coding Agent in the Build phase uses this failure data to:
Update the agent's objectives.
Modify the agent's node graph.
Regenerate the connection code.
Redeploy the improved agent.
In short, "Failure Data" flows from Runtime/Infrastructure back to the Build/Coding Agent to facilitate proactive self-evolution.

________________________________________
✅ Task 2.3: Comparison Challenge 📊
1.	What category is CrewAI in?
In the comparison table, CrewAI is categorized under “Multi-Agent Orchestration” frameworks. (GitHub)
2.	What’s the Aden difference compared to LangChain?
Aden automatically generates entire agent graphs from natural language goals, whereas LangChain provides component libraries and requires manual connection logic. (GitHub)
3.	Which framework focuses on “emergent behavior in large-scale simulations”?
That refers to the CAMEL Research Framework, which the table notes focuses on emergent behavior in large-scale simulations. (GitHub)


Task 3.1: Project Structure 📁 
📁 1. What is the main frontend folder called?
The frontend of the project lives in the honeycomb/ folder — this contains the React + TypeScript + Vite dashboard code. (GitHub)
🧠 2. What is the main backend folder called?
The core backend (agent runtime, MCP tools, and Python logic) is structured under the root of the repo, with key server logic typically in folders meant for framework / core services. The exact name often shown in docs is the backend itself (often seen as root Python modules). (GitHub)
⚙️ 3. What file would you edit to configure the application?
Configuration for Aden Hive is centralized in a config.yaml file. This is where app-wide settings (database, tools, LLM providers, etc.) are defined and edited. (GitHub)

🐳 4. What’s the Docker command to start all services?
To start the entire application stack via Docker, use:
docker compose up
This command launches all defined services (frontend, backend, databases, etc.) as containers per the project’s docker-compose.yml. (GitHub)

Task 3.2: Find the Features 🎯
1. MCP Tools Location
The MCP tools are defined in the aden_tools package.
•	File Path: packages/aden_tools/src/tools/
•	This directory contains individual subfolders for each tool implementation (e.g., web_search_tool/, web_scrape_tool/, file_system_toolkits/).
2. MCP Server Port
The MCP server typically runs on a specific port defined in its configuration or Docker setup.
•	Default Port: 8080 (or 8082 depending on specific service configuration).
•	Hint: If you check the tools/Dockerfile or the mcp_server.py entry point, you will see the environment variable MCP_PORT or an EXPOSE instruction pointing to these ports.
3. TypeScript Agent Interface
A core TypeScript interface used to define the structure of an agent can be found in the core framework definitions.
•	File Path: packages/framework/src/types/agent.ts (or packages/framework/src/index.ts)
•	Interface Name: AgentConfig or GraphSpec
•	Description: This interface defines the essential components of an agent, including its goal, nodes (LLM, Router, Function), and edges (connections between nodes).



Part 4: Creative Challenge - Agent Idea Example
Here's a creative agent idea for you:
Name: CodeReviewer Pro
Goal: Automatically reviews pull requests for code quality, security vulnerabilities, and best practices. It analyzes code changes, runs static analysis, checks for common anti-patterns, and provides detailed feedback with specific line-by-line suggestions for improvement.
Self-Improvement: When developers reject or modify its suggestions, it learns from the feedback patterns. It tracks which types of suggestions get accepted vs rejected, adjusts its strictness levels based on team preferences, and refines its understanding of the codebase's specific patterns and conventions over time.
Human-in-the-Loop: Critical security vulnerabilities require human security team approval before deployment. Major architectural changes or refactoring suggestions pause for senior developer review. When confidence scores fall below 70% on complex logic changes, it escalates to a human reviewer rather than making automated suggestions.
