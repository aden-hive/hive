# 🚀 Getting Started Challenge

Welcome to Aden! This challenge will help you get familiar with our project and community. Complete all tasks to earn your first badge!

**Difficulty:** Beginner
**Time:** ~30 minutes
**Prerequisites:** GitHub account

---

## Part 1: Join the Aden Community (10 points)

### Task 1.1: Star the Repository ⭐
Show your support by starring our repo!

1. Go to [github.com/adenhq/hive](https://github.com/adenhq/hive)
2. Click the **Star** button in the top right
3. **Screenshot** your starred repo (showing the star count)
<img width="2880" height="1540" alt="image" src="https://github.com/user-attachments/assets/0b0e4ecb-de99-4b3d-959f-56ebfe98baa9" />


### Task 1.2: Watch the Repository 👁️
Stay updated with our latest changes!

1. Click the **Watch** button
2. Select **"All Activity"** to get notifications
3. **Screenshot** your watch settings
<img width="2868" height="1344" alt="image" src="https://github.com/user-attachments/assets/547a9f21-f543-446a-adef-d4d1f5b13346" />


### Task 1.3: Fork the Repository 🍴
Create your own copy to experiment with!

1. Click the **Fork** button
2. Keep the default settings and create the fork
3. **Screenshot** your forked repository
<img width="2880" height="1354" alt="image" src="https://github.com/user-attachments/assets/517cc104-1a48-4b97-8969-ff5c2f8d2caf" />


### Task 1.4: Join Discord 💬
Connect with our community!

1. Join our [Discord server](https://discord.com/invite/MXE49hrKDk)
2. Introduce yourself in `#introductions`
3. **Screenshot** your introduction message
<img width="1564" height="428" alt="image" src="https://github.com/user-attachments/assets/16f675d7-f33d-47b1-b11d-b5501af38ee0" />


---

## Part 2: Explore Aden (15 points)

### Task 2.1: README Scavenger Hunt 🔍
Find the answers to these questions by reading our README:

1. What are the **three LLM providers** Aden supports out of the box? OpenAI, Gemini, Anthropic
2. How many **MCP tools** does the Hive Control Plane provide? 19
3. What is the name of the **frontend dashboard**? Honeycomb
4. In the "How It Works" section, what is **Step 5**? Self-Improve
5. What city is Aden made with passion in? San Francisco

### Task 2.2: Architecture Quiz 🏗️
Based on the architecture diagram in the README:

1. What are the three databases in the Storage Layer? PostgreSQL, DuckDB, MongoDB
2. Name two components inside an "SDK-Wrapped Node" Local RLM Memory and LLM access outside of the box
3. What connects the Control Plane to the Dashboard? API Server, Multi Agent Decision Executor, and the MCP Server
4. Where does "Failure Data" flow to in the diagram? Into the Multi Agent System to evolve and redeploy the agent

### Task 2.3: Comparison Challenge 📊
From the Comparison Table, answer:

1. What category is CrewAI in? Multi-Agent Orchestration
2. What's the Aden difference compared to LangChain? Generates entire graph and connection code upfront
3. Which framework focuses on "emergent behavior in large-scale simulations"? CAMEL

---

## Part 3: Quick Code Exploration (15 points)

### Task 3.1: Project Structure 📁
Clone your fork and explore the codebase:

```bash
git clone https://github.com/YOUR_USERNAME/hive.git
cd hive
```

Answer these questions:

1. What is the main frontend folder called? Honeycomb
2. What is the main backend folder called? Hive
3. What file would you edit to configure the application? config.yaml.example
4. What's the Docker command to start all services (hint: check README)? docker compose up

### Task 3.2: Find the Features 🎯
Look through the codebase to find:

1. Where are the MCP tools defined? (provide the file path) hive/core/.mcp.json
2. What port does the API run on? (hint: check README or docker-compose) 4000
3. Find one TypeScript interface related to agents (provide file path and interface name) hive/src/mcp/tools/agents.ts agents.ts/Control Emitter

---

## Part 4: Creative Challenge (10 points)

### Task 4.1: Agent Idea 💡
Aden can build self-improving agents for any use case. Propose ONE creative agent idea:

1. **Name:** Give your agent a catchy name. PAT (Performance Agent Tracking)
2. **Goal:** What problem does it solve? (2-3 sentences) This agent would be designed to track the performance of your products in a retail setting. It would analyze the profitability and popularity of these items, and if they are performing below a certain threshold, the agent will notify and produce graphs to support these claims. It could provide insights on how to improve products based on customer reviews, or help with pricing.
3. **Self-Improvement:** How would it get better over time when things fail? Failure in this scenario is flagging a product for review and then performing worse after adjustments. For example, if the agent suggested a price change and when the price on the product is changed to the given suggestion, sales and profits decrease.
4. **Human-in-the-Loop:** When would it need human input? It would need human input to verify change recommendations before deployment.

Example format:
```
Name: DocBot
Goal: Automatically keeps documentation in sync with code changes.
      Monitors PRs and updates relevant docs.
Self-Improvement: When docs get rejected in review, it learns the feedback
                  and adjusts its writing style and coverage.
Human-in-the-Loop: Major architectural changes require human approval
                   before doc updates go live.
```

---

## Submission Checklist

Before submitting, make sure you have:

- [ ] Screenshots from Part 1 (Star, Watch, Fork, Discord)
- [ ] Answers to all Part 2 questions
- [ ] Answers to all Part 3 questions
- [ ] Your creative agent idea from Part 4

### How to Submit

1. Create a GitHub Gist at [gist.github.com](https://gist.github.com)
2. Name it `aden-getting-started-YOURNAME.md`
3. Include all your answers and screenshots (use image hosting like imgur for screenshots)
4. Email the Gist link to `careers@adenhq.com`
   - Subject: `[Getting Started Challenge] Your Name`
   - Include your GitHub username

---

## Scoring

| Section | Points |
|---------|--------|
| Part 1: Community | 10 |
| Part 2: Explore | 15 |
| Part 3: Code | 15 |
| Part 4: Creative | 10 |
| **Total** | **50** |

**Passing score:** 40+ points

---

## What's Next?

After completing this challenge, choose your specialization:

- **Backend Engineers:** [🧠 Architecture Deep Dive](./02-architecture-deep-dive.md)
- **AI/ML Engineers:** [🤖 Build Your First Agent](./03-build-your-first-agent.md)
- **Frontend Engineers:** [🎨 Frontend Challenge](./04-frontend-challenge.md)
- **DevOps Engineers:** [🔧 DevOps Challenge](./05-devops-challenge.md)

---

Good luck! We're excited to see your submissions! 🎉
