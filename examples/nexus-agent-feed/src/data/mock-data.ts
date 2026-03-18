export type MessageRole = "user" | "assistant";
export type StepStatus = "success" | "running" | "warning" | "failed" | "pending";
export type SessionStatus = "completed" | "running" | "failed";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  file?: { name: string; size: string; type: string };
}

export interface ExecutionStep {
  id: string;
  label: string;
  status: StepStatus;
  time: string;
  tool?: string;
  details?: string;
  duration?: string;
}

export interface Session {
  id: string;
  title: string;
  preview: string;
  date: string;
  status: SessionStatus;
  agent: string;
  tokens: number;
  duration: string;
  messageCount: number;
}

export interface TemplateConfig {
  systemPrompt: string;
  model: string;
  maxSteps: number;
  responseStyle: string;
  memoryEnabled: boolean;
  enabledTools: string[];
}

export interface AgentTemplate {
  id: string;
  title: string;
  description: string;
  tags: string[];
  icon: string;
  popularity: number;
  capabilities: string[];
  useCases: string[];
  config: TemplateConfig;
  quickActions: string[];
  sampleMessages: ChatMessage[];
  executionSteps: ExecutionStep[];
}

export const MOCK_MESSAGES: ChatMessage[] = [
  {
    id: "msg-1",
    role: "user",
    content: "Analyze the Q3 sales data and compare it with our inventory levels. Can you find any discrepancies?",
    timestamp: "10:01",
  },
  {
    id: "msg-2",
    role: "assistant",
    content: `I've analyzed the Q3 sales reports against current inventory levels. Here are my findings:

### Key Findings

**1. Overstock Issues**
- \`SKU-902\` (Wireless Headphones) has **45% more stock** than projected sales demand
- \`SKU-445\` (USB-C Hub) is overstocked by approximately 2,300 units

**2. Critical Shortages**
- \`SKU-114\` (Laptop Stand Pro) is trending to **stock out in 4 days** based on current velocity
- \`SKU-287\` (Ergonomic Mouse) has only 12 units remaining

### Data Summary

| SKU | Current Stock | Projected Need | Delta |
|---------|--------------|----------------|---------|
| SKU-902 | 4,200 | 2,900 | +1,300 |
| SKU-114 | 89 | 1,400 | -1,311 |
| SKU-445 | 5,100 | 2,800 | +2,300 |
| SKU-287 | 12 | 890 | -878 |

### Recommendations
1. Initiate emergency reorder for SKU-114 and SKU-287
2. Consider running a promotional discount on SKU-902 and SKU-445
3. Set up automated low-stock alerts at the 15% threshold

Would you like me to generate a reorder draft or create a detailed report?`,
    timestamp: "10:02",
  },
  {
    id: "msg-3",
    role: "user",
    content: "Yes, please generate the reorder draft for the critical shortage items. I've attached the supplier pricing sheet.",
    timestamp: "10:03",
    file: { name: "supplier-pricing-q3.xlsx", size: "2.4 MB", type: "spreadsheet" },
  },
  {
    id: "msg-4",
    role: "assistant",
    content: `I've reviewed the uploaded supplier pricing sheet and prepared the reorder draft:

### Reorder Draft — Priority: **Critical**

**Order #RO-2024-Q3-087**

| Item | SKU | Qty to Order | Supplier | Est. Delivery |
|------|-----|-------------|----------|---------------|
| Laptop Stand Pro | SKU-114 | 2,000 | TechSupply Co. | 5 business days |
| Ergonomic Mouse | SKU-287 | 1,200 | PeripheralsDirect | 3 business days |

**Total Estimated Cost:** $47,600

\`\`\`json
{
  "order_id": "RO-2024-Q3-087",
  "priority": "critical",
  "items": [
    { "sku": "SKU-114", "qty": 2000, "unit_price": 18.50 },
    { "sku": "SKU-287", "qty": 1200, "unit_price": 12.80 }
  ],
  "total": 47600,
  "status": "pending_approval"
}
\`\`\`

> ⚠️ **Note:** SKU-114 has a minimum order quantity of 500 units from TechSupply Co. I've rounded up to 2,000 to provide a 6-week buffer based on current sales velocity.

The draft is ready for approval. Shall I submit this to your procurement system?`,
    timestamp: "10:03",
  },
];

export const EXECUTION_STEPS: ExecutionStep[] = [
  {
    id: "step-1",
    label: "Parsing user request",
    status: "success",
    time: "10:03:15",
    duration: "85ms",
    details: "Identified intent: generate_reorder_draft with entities: SKU-114, SKU-287",
  },
  {
    id: "step-2",
    label: "Processing uploaded file",
    status: "success",
    time: "10:03:16",
    tool: "File_Reader",
    duration: "340ms",
    details: "Parsed supplier-pricing-q3.xlsx — 3 sheets, 847 rows extracted",
  },
  {
    id: "step-3",
    label: "Querying inventory database",
    status: "success",
    time: "10:03:16",
    tool: "SQL_Query",
    duration: "1.2s",
    details: "SELECT * FROM inventory WHERE sku IN ('SKU-114','SKU-287') — 2 rows returned",
  },
  {
    id: "step-4",
    label: "Searching supplier pricing",
    status: "success",
    time: "10:03:17",
    tool: "Knowledge_Base",
    duration: "890ms",
    details: "Matched 3 suppliers for SKU-114, 2 suppliers for SKU-287. Best price selected.",
  },
  {
    id: "step-5",
    label: "Calculating reorder quantities",
    status: "success",
    time: "10:03:18",
    tool: "Analytics_Engine",
    duration: "210ms",
    details: "Applied safety stock formula: reorder_qty = (avg_daily_sales × lead_time) + safety_buffer",
  },
  {
    id: "step-6",
    label: "Generating order draft",
    status: "success",
    time: "10:03:19",
    duration: "1.8s",
    details: "Created structured order with cost estimates and delivery timeline",
  },
  {
    id: "step-7",
    label: "Composing response",
    status: "running",
    time: "10:03:21",
    tool: "AI_Gateway",
    duration: "...",
  },
];

export const RECENT_SESSIONS: Session[] = [
  {
    id: "sess-1",
    title: "Q3 Sales Analysis",
    preview: "Analyzed sales data and inventory discrepancies…",
    date: "2 min ago",
    status: "running",
    agent: "Research Agent v2.4",
    tokens: 2840,
    duration: "4m 12s",
    messageCount: 6,
  },
  {
    id: "sess-2",
    title: "Customer Churn Report",
    preview: "Generated monthly churn analysis with predictions…",
    date: "45 min ago",
    status: "completed",
    agent: "Data Analyst v1.8",
    tokens: 4200,
    duration: "8m 45s",
    messageCount: 12,
  },
  {
    id: "sess-3",
    title: "API Documentation Review",
    preview: "Reviewed and suggested improvements for REST API…",
    date: "2h ago",
    status: "completed",
    agent: "Writing Assistant v3.1",
    tokens: 3100,
    duration: "6m 20s",
    messageCount: 8,
  },
  {
    id: "sess-4",
    title: "Market Research Brief",
    preview: "Compiled competitive analysis for Q4 strategy…",
    date: "Yesterday",
    status: "completed",
    agent: "Research Agent v2.4",
    tokens: 5600,
    duration: "12m 10s",
    messageCount: 15,
  },
  {
    id: "sess-5",
    title: "Bug Triage Session",
    preview: "Categorized and prioritized 23 open issues…",
    date: "Mar 15",
    status: "completed",
    agent: "Coding Assistant v2.0",
    tokens: 1900,
    duration: "3m 45s",
    messageCount: 5,
  },
  {
    id: "sess-6",
    title: "Email Campaign Draft",
    preview: "Created email sequences for product launch…",
    date: "Mar 15",
    status: "failed",
    agent: "Writing Assistant v3.1",
    tokens: 980,
    duration: "1m 30s",
    messageCount: 3,
  },
  {
    id: "sess-7",
    title: "Database Schema Review",
    preview: "Analyzed and optimized schema for performance…",
    date: "Mar 14",
    status: "completed",
    agent: "Coding Assistant v2.0",
    tokens: 3400,
    duration: "7m 15s",
    messageCount: 9,
  },
];

export const AGENT_TEMPLATES: AgentTemplate[] = [
  {
    id: "tmpl-1",
    title: "Research Assistant",
    description: "Deep-dive research with source citation, data analysis, and structured report generation across multiple domains.",
    tags: ["Research", "Analysis", "Reports"],
    icon: "search",
    popularity: 94,
    capabilities: [
      "Multi-source web research with citation",
      "Data analysis and trend identification",
      "Structured report generation (PDF/Markdown)",
      "Competitive landscape analysis",
      "Literature review and summarization",
    ],
    useCases: [
      "Market research briefs for strategy meetings",
      "Competitive analysis reports",
      "Academic literature reviews",
      "Industry trend monitoring",
    ],
    config: {
      systemPrompt: "You are a precise research assistant. Always cite sources, verify claims from multiple references, and present findings with clear data tables and markdown formatting.",
      model: "google/gemini-2.5-pro",
      maxSteps: 20,
      responseStyle: "Detailed & Thorough",
      memoryEnabled: true,
      enabledTools: ["Web Search", "Knowledge Base", "File Manager"],
    },
    quickActions: ["Research topic", "Summarize findings", "Compare sources", "Generate report"],
    sampleMessages: [
      { id: "r-1", role: "user", content: "Research the current state of AI regulation in the EU and compare it with the US approach.", timestamp: "09:15" },
      { id: "r-2", role: "assistant", content: "I've conducted a comprehensive analysis of AI regulation across both jurisdictions.\n\n### EU AI Act (2024)\n- **Risk-based framework** classifying AI systems into 4 tiers\n- Prohibits social scoring and real-time biometric surveillance\n- Requires transparency for generative AI outputs\n- Fines up to **€35M or 7% of global revenue**\n\n### US Approach\n- **Sector-specific** rather than comprehensive\n- Executive Order 14110 (Oct 2023) sets safety standards\n- NIST AI Risk Management Framework is voluntary\n- State-level laws creating a **patchwork** of requirements\n\n| Aspect | EU | US |\n|--------|-----|-----|\n| Scope | Comprehensive | Sector-specific |\n| Enforcement | Centralized | Distributed |\n| Penalties | Up to €35M | Varies by sector |\n| Timeline | Phased 2024-2027 | Ongoing |\n\nWould you like me to dive deeper into any specific area?", timestamp: "09:16" },
    ],
    executionSteps: [
      { id: "rs-1", label: "Parsing research query", status: "success", time: "09:15:01", duration: "120ms", details: "Identified topics: AI regulation, EU, US, comparative analysis" },
      { id: "rs-2", label: "Searching academic sources", status: "success", time: "09:15:02", tool: "Web_Search", duration: "2.1s", details: "Found 47 relevant sources across legal databases and news" },
      { id: "rs-3", label: "Querying knowledge base", status: "success", time: "09:15:04", tool: "Knowledge_Base", duration: "680ms", details: "Retrieved 12 internal policy documents" },
      { id: "rs-4", label: "Cross-referencing sources", status: "success", time: "09:15:05", tool: "Analytics_Engine", duration: "1.4s", details: "Validated claims across 23 sources, 3 conflicts resolved" },
      { id: "rs-5", label: "Generating comparative analysis", status: "success", time: "09:15:07", duration: "2.3s" },
      { id: "rs-6", label: "Formatting response", status: "running", time: "09:15:09", tool: "AI_Gateway", duration: "..." },
    ],
  },
  {
    id: "tmpl-2",
    title: "Customer Support Agent",
    description: "Handle customer inquiries, resolve issues, and escalate when necessary. Trained on your knowledge base and support docs.",
    tags: ["Support", "Customer-facing", "Knowledge Base"],
    icon: "headphones",
    popularity: 91,
    capabilities: [
      "Intelligent ticket routing and prioritization",
      "Knowledge base search and response drafting",
      "Sentiment analysis and escalation detection",
      "Multi-language support",
      "Follow-up scheduling and tracking",
    ],
    useCases: [
      "Drafting customer email responses",
      "Troubleshooting product issues",
      "Processing refund and return requests",
      "Escalating complex issues to specialists",
    ],
    config: {
      systemPrompt: "You are a professional customer support agent. Be empathetic, solution-oriented, and follow company policies. Always confirm understanding before proposing solutions.",
      model: "google/gemini-2.5-flash",
      maxSteps: 10,
      responseStyle: "Casual & Friendly",
      memoryEnabled: true,
      enabledTools: ["Knowledge Base", "API Connector"],
    },
    quickActions: ["Draft reply", "Find help article", "Escalate issue", "Check status"],
    sampleMessages: [
      { id: "cs-1", role: "user", content: "Customer says their order #ORD-4821 hasn't arrived after 10 days. They're asking for a refund.", timestamp: "14:22" },
      { id: "cs-2", role: "assistant", content: "I've looked into order **#ORD-4821** and here's what I found:\n\n### Order Status\n- **Shipped:** March 8, via FedEx Ground\n- **Tracking:** `FX-9284710283`\n- **Last scan:** March 12, distribution center (Memphis, TN)\n- **Expected delivery:** March 14 (2 days overdue)\n\n### Recommended Response\n\n> Hi [Customer Name],\n>\n> Thank you for reaching out about your order. I can see it's currently in transit but has been delayed at our distribution center. I sincerely apologize for the inconvenience.\n>\n> I've flagged this for **priority handling** and you should receive an updated delivery estimate within 24 hours. If it doesn't arrive by March 20, I'll process a full refund immediately.\n>\n> Is there anything else I can help with?\n\nShall I send this response or adjust the tone?", timestamp: "14:23" },
    ],
    executionSteps: [
      { id: "cs-s1", label: "Parsing customer inquiry", status: "success", time: "14:22:01", duration: "95ms", details: "Intent: order_status + refund_request, Order: #ORD-4821" },
      { id: "cs-s2", label: "Retrieving order details", status: "success", time: "14:22:01", tool: "API_Connector", duration: "450ms", details: "Fetched order from OMS — shipped March 8, FedEx Ground" },
      { id: "cs-s3", label: "Checking shipping status", status: "success", time: "14:22:02", tool: "API_Connector", duration: "820ms", details: "FedEx API: last scan March 12, delayed at distribution center" },
      { id: "cs-s4", label: "Searching support policies", status: "success", time: "14:22:03", tool: "Knowledge_Base", duration: "340ms", details: "Policy: auto-refund after 7 days overdue for ground shipping" },
      { id: "cs-s5", label: "Drafting response", status: "success", time: "14:22:03", duration: "1.6s" },
      { id: "cs-s6", label: "Sentiment check", status: "warning", time: "14:22:05", duration: "200ms", details: "Customer frustration level: moderate. Recommend empathetic tone." },
    ],
  },
  {
    id: "tmpl-3",
    title: "Coding Assistant",
    description: "Code review, debugging, refactoring suggestions, and documentation generation with multi-language support.",
    tags: ["Development", "Code Review", "Debugging"],
    icon: "code",
    popularity: 92,
    capabilities: [
      "Code review with actionable feedback",
      "Bug detection and fix suggestions",
      "Refactoring for performance and readability",
      "Documentation and JSDoc generation",
      "Unit test generation",
    ],
    useCases: [
      "Reviewing pull requests",
      "Debugging production issues",
      "Generating boilerplate code",
      "Writing technical documentation",
    ],
    config: {
      systemPrompt: "You are a senior software engineer. Provide precise, well-reasoned code suggestions. Always explain the 'why' behind changes. Use code blocks with language tags.",
      model: "openai/gpt-5",
      maxSteps: 25,
      responseStyle: "Technical & Precise",
      memoryEnabled: true,
      enabledTools: ["Code Interpreter", "Web Search", "File Manager"],
    },
    quickActions: ["Review code", "Fix bug", "Generate tests", "Write docs"],
    sampleMessages: [
      { id: "cd-1", role: "user", content: "Review this React hook for potential issues:\n```typescript\nfunction useDebounce(value, delay) {\n  const [debounced, setDebounced] = useState(value);\n  useEffect(() => {\n    const timer = setTimeout(() => setDebounced(value), delay);\n    return () => clearTimeout(timer);\n  }, [value]);\n  return debounced;\n}\n```", timestamp: "11:30" },
      { id: "cd-2", role: "assistant", content: "Good foundation, but I found **2 issues** and have **1 improvement** suggestion:\n\n### Issues Found\n\n**1. Missing `delay` dependency**\nThe `useEffect` depends on `delay` but it's not in the dependency array. If `delay` changes, the effect won't re-run.\n\n**2. No TypeScript generics**\nThe hook lacks type safety — it should be generic to preserve the input type.\n\n### Improved Version\n\n```typescript\nfunction useDebounce<T>(value: T, delay: number): T {\n  const [debounced, setDebounced] = useState<T>(value);\n  \n  useEffect(() => {\n    const timer = setTimeout(() => setDebounced(value), delay);\n    return () => clearTimeout(timer);\n  }, [value, delay]); // ← added delay\n  \n  return debounced;\n}\n```\n\n### Why this matters\n- Missing deps can cause **stale closures** in production\n- Generic typing ensures **type inference** flows correctly to consumers\n\nWant me to also generate unit tests for this hook?", timestamp: "11:31" },
    ],
    executionSteps: [
      { id: "cd-s1", label: "Parsing code snippet", status: "success", time: "11:30:01", duration: "65ms", details: "Language: TypeScript/React, Pattern: custom hook" },
      { id: "cd-s2", label: "Static analysis", status: "success", time: "11:30:01", tool: "Code_Interpreter", duration: "1.1s", details: "AST parsed, 2 issues detected: missing dep, no generics" },
      { id: "cd-s3", label: "Searching best practices", status: "success", time: "11:30:02", tool: "Web_Search", duration: "780ms", details: "Cross-referenced React docs and eslint-plugin-react-hooks rules" },
      { id: "cd-s4", label: "Generating fix", status: "success", time: "11:30:03", duration: "1.2s", details: "Produced corrected version with TypeScript generics" },
      { id: "cd-s5", label: "Formatting response", status: "running", time: "11:30:04", tool: "AI_Gateway", duration: "..." },
    ],
  },
  {
    id: "tmpl-4",
    title: "Data Analyst",
    description: "Process datasets, generate visualizations, perform statistical analysis, and create automated data pipelines.",
    tags: ["Analytics", "Visualization", "SQL"],
    icon: "bar-chart",
    popularity: 87,
    capabilities: [
      "SQL query generation and optimization",
      "Statistical analysis and hypothesis testing",
      "Chart and visualization recommendations",
      "Data cleaning and transformation",
      "Automated pipeline suggestions",
    ],
    useCases: [
      "Analyzing sales and revenue trends",
      "Building executive dashboards",
      "A/B test result analysis",
      "Customer segmentation studies",
    ],
    config: {
      systemPrompt: "You are a data analyst specializing in business intelligence. Always present data with tables, suggest visualizations, and explain statistical significance clearly.",
      model: "google/gemini-2.5-pro",
      maxSteps: 20,
      responseStyle: "Detailed & Thorough",
      memoryEnabled: true,
      enabledTools: ["Code Interpreter", "Knowledge Base", "API Connector"],
    },
    quickActions: ["Analyze dataset", "Generate chart", "Write SQL", "Extract insights"],
    sampleMessages: [
      { id: "da-1", role: "user", content: "What was our MRR growth rate over the last 6 months? Break it down by plan tier.", timestamp: "15:00" },
      { id: "da-2", role: "assistant", content: "Here's the MRR analysis broken down by plan tier:\n\n### Monthly Recurring Revenue — Last 6 Months\n\n| Month | Starter | Pro | Enterprise | Total MRR |\n|-------|---------|-----|------------|----------|\n| Oct | $12,400 | $45,200 | $89,000 | $146,600 |\n| Nov | $13,100 | $48,800 | $91,500 | $153,400 |\n| Dec | $13,800 | $51,200 | $95,000 | $160,000 |\n| Jan | $14,500 | $54,600 | $98,200 | $167,300 |\n| Feb | $15,200 | $57,900 | $102,400 | $175,500 |\n| Mar | $16,100 | $61,300 | $108,000 | $185,400 |\n\n### Key Insights\n- **Overall MRR growth:** 26.5% over 6 months (4.0% MoM avg)\n- **Fastest growing tier:** Pro at **35.6%** growth\n- **Enterprise:** Steady at **21.3%**, driven by 3 new contracts\n- **Starter:** Consistent **29.8%** growth, strong acquisition funnel\n\n> 📊 **Recommendation:** The Pro tier shows the strongest momentum. Consider allocating more marketing budget to Pro conversion campaigns.\n\nWant me to generate a visualization or forecast the next quarter?", timestamp: "15:01" },
    ],
    executionSteps: [
      { id: "da-s1", label: "Parsing analytics query", status: "success", time: "15:00:01", duration: "90ms", details: "Metrics: MRR, Dimensions: month, plan_tier, Range: 6 months" },
      { id: "da-s2", label: "Querying revenue database", status: "success", time: "15:00:01", tool: "SQL_Query", duration: "1.8s", details: "SELECT month, plan_tier, SUM(mrr) FROM subscriptions GROUP BY month, plan_tier" },
      { id: "da-s3", label: "Computing growth rates", status: "success", time: "15:00:03", tool: "Code_Interpreter", duration: "450ms", details: "Calculated MoM and cumulative growth per tier" },
      { id: "da-s4", label: "Generating insights", status: "success", time: "15:00:04", tool: "Analytics_Engine", duration: "1.1s", details: "Identified Pro tier as fastest growing, flagged Enterprise stability" },
      { id: "da-s5", label: "Formatting response", status: "running", time: "15:00:05", tool: "AI_Gateway", duration: "..." },
    ],
  },
  {
    id: "tmpl-5",
    title: "Scheduling Assistant",
    description: "Manage calendars, coordinate meetings across time zones, and optimize daily schedules for productivity.",
    tags: ["Scheduling", "Calendar", "Productivity"],
    icon: "calendar",
    popularity: 78,
    capabilities: [
      "Cross-timezone meeting coordination",
      "Calendar conflict detection",
      "Optimal time slot suggestion",
      "Meeting agenda generation",
      "Follow-up reminder scheduling",
    ],
    useCases: [
      "Coordinating team standups across offices",
      "Scheduling client demos",
      "Planning sprint ceremonies",
      "Organizing executive review meetings",
    ],
    config: {
      systemPrompt: "You are a scheduling assistant. Be precise with time zones, proactively identify conflicts, and always suggest alternatives. Use tables for time comparisons.",
      model: "google/gemini-2.5-flash",
      maxSteps: 10,
      responseStyle: "Concise & Professional",
      memoryEnabled: true,
      enabledTools: ["API Connector", "Knowledge Base"],
    },
    quickActions: ["Find time slot", "Check conflicts", "Send invite", "Review calendar"],
    sampleMessages: [
      { id: "sc-1", role: "user", content: "Schedule a 45-minute product review with the NYC and London teams next week. Everyone should be available.", timestamp: "16:00" },
      { id: "sc-2", role: "assistant", content: "I've analyzed both teams' calendars for next week. Here are the best slots:\n\n### Available Slots (45 min)\n\n| Day | NYC (ET) | London (GMT) | Conflicts |\n|-----|----------|-------------|----------|\n| Mon | 10:00 AM | 3:00 PM | ✅ None |\n| Tue | 11:30 AM | 4:30 PM | ⚠️ Sarah has a soft hold |\n| Thu | 9:00 AM | 2:00 PM | ✅ None |\n\n### Recommendation\n**Monday 10:00 AM ET / 3:00 PM GMT** — cleanest slot with no conflicts and good energy levels for both teams.\n\n### Proposed Agenda\n1. Sprint progress review (15 min)\n2. Feature demo: Dashboard v2 (20 min)\n3. Q&A and action items (10 min)\n\nShall I send the calendar invite?", timestamp: "16:01" },
    ],
    executionSteps: [
      { id: "sc-s1", label: "Parsing scheduling request", status: "success", time: "16:00:01", duration: "75ms", details: "Duration: 45min, Teams: NYC + London, Window: next week" },
      { id: "sc-s2", label: "Fetching NYC team calendars", status: "success", time: "16:00:01", tool: "API_Connector", duration: "1.2s", details: "Retrieved 5 calendars, 23 existing events" },
      { id: "sc-s3", label: "Fetching London team calendars", status: "success", time: "16:00:02", tool: "API_Connector", duration: "1.4s", details: "Retrieved 4 calendars, 18 existing events" },
      { id: "sc-s4", label: "Computing available slots", status: "success", time: "16:00:04", duration: "320ms", details: "Cross-referenced 41 events, found 3 viable slots" },
      { id: "sc-s5", label: "Generating agenda", status: "success", time: "16:00:04", duration: "890ms" },
      { id: "sc-s6", label: "Formatting response", status: "running", time: "16:00:05", tool: "AI_Gateway", duration: "..." },
    ],
  },
  {
    id: "tmpl-6",
    title: "Content Writer",
    description: "Create blog posts, social media content, email campaigns, and marketing copy with brand voice consistency.",
    tags: ["Writing", "Marketing", "Content"],
    icon: "pen-tool",
    popularity: 85,
    capabilities: [
      "Blog post and article drafting",
      "Social media content calendars",
      "Email campaign sequence creation",
      "SEO-optimized copywriting",
      "Brand voice consistency checking",
    ],
    useCases: [
      "Writing weekly blog posts",
      "Creating product launch campaigns",
      "Drafting newsletter content",
      "Social media content batching",
    ],
    config: {
      systemPrompt: "You are a creative content writer with expertise in marketing copy. Match the brand voice, optimize for engagement, and always suggest CTAs. Use headers and bullet points for readability.",
      model: "openai/gpt-5",
      maxSteps: 15,
      responseStyle: "Casual & Friendly",
      memoryEnabled: true,
      enabledTools: ["Web Search", "Knowledge Base", "File Manager"],
    },
    quickActions: ["Write blog post", "Create campaign", "Draft email", "Social media copy"],
    sampleMessages: [
      { id: "cw-1", role: "user", content: "Write a product launch email for our new AI analytics dashboard. Target audience: B2B SaaS CTOs.", timestamp: "13:00" },
      { id: "cw-2", role: "assistant", content: "Here's a launch email tailored for B2B SaaS CTOs:\n\n### Subject Line Options\n1. \"Your data team just got 10x faster\"\n2. \"The analytics dashboard your engineers actually want to use\"\n3. \"Stop building dashboards. Start shipping insights.\"\n\n---\n\n### Email Body\n\n**Hi [First Name],**\n\nYour engineering team spends **40% of their time** building internal dashboards. We built one that builds itself.\n\n**Introducing Nexus Analytics** — an AI-powered dashboard that:\n\n- 📊 **Auto-generates visualizations** from your data warehouse\n- 🔍 **Answers questions in plain English** — no SQL required\n- ⚡ **Deploys in 15 minutes** with your existing stack\n- 🔒 **SOC 2 compliant** with role-based access\n\n> \"We replaced 3 internal tools and saved 120 engineering hours per month.\" — VP Eng, Series C SaaS\n\n**[→ Book a 15-min Demo](https://nexus.ai/demo)**\n\n---\n\nWant me to create the follow-up sequence or A/B test variants?", timestamp: "13:01" },
    ],
    executionSteps: [
      { id: "cw-s1", label: "Analyzing brief", status: "success", time: "13:00:01", duration: "110ms", details: "Type: product launch email, Audience: B2B SaaS CTOs" },
      { id: "cw-s2", label: "Researching audience", status: "success", time: "13:00:01", tool: "Web_Search", duration: "1.6s", details: "Analyzed CTO pain points, email benchmarks for SaaS launches" },
      { id: "cw-s3", label: "Loading brand guidelines", status: "success", time: "13:00:03", tool: "Knowledge_Base", duration: "420ms", details: "Retrieved brand voice doc, tone: professional-casual, no jargon" },
      { id: "cw-s4", label: "Generating subject lines", status: "success", time: "13:00:03", duration: "780ms", details: "Created 3 variants optimized for open rate" },
      { id: "cw-s5", label: "Writing email body", status: "success", time: "13:00:04", duration: "2.1s" },
      { id: "cw-s6", label: "SEO & tone review", status: "warning", time: "13:00:06", duration: "350ms", details: "Readability score: 72 (target: 75+). Minor adjustment recommended." },
      { id: "cw-s7", label: "Formatting response", status: "running", time: "13:00:07", tool: "AI_Gateway", duration: "..." },
    ],
  },
];

export const DASHBOARD_STATS = [
  { label: "Total Sessions", value: "1,284", trend: "+12%", trendUp: true },
  { label: "Tasks Completed", value: "3,847", trend: "+8%", trendUp: true },
  { label: "Success Rate", value: "99.2%", trend: "+0.4%", trendUp: true },
  { label: "Avg. Response", value: "1.4s", trend: "-0.2s", trendUp: true },
];

export const MOCK_LOG_ENTRIES = [
  { id: "log-1", title: "Q3 Sales Analysis", status: "running" as const, created_at: "2026-03-18T10:01:00Z", updated_at: "2026-03-18T10:04:00Z", message_count: 4, token_estimate: 2840, tools: ["SQL_Query", "Analytics_Engine"] },
  { id: "log-2", title: "Customer Churn Report", status: "completed" as const, created_at: "2026-03-18T09:15:00Z", updated_at: "2026-03-18T09:23:00Z", message_count: 12, token_estimate: 4200, tools: ["Knowledge_Base", "Chart_Gen"] },
  { id: "log-3", title: "API Documentation Review", status: "completed" as const, created_at: "2026-03-17T16:30:00Z", updated_at: "2026-03-17T16:36:00Z", message_count: 8, token_estimate: 3100, tools: ["Web_Search", "File_Reader"] },
  { id: "log-4", title: "Market Research Brief", status: "completed" as const, created_at: "2026-03-17T14:00:00Z", updated_at: "2026-03-17T14:12:00Z", message_count: 15, token_estimate: 5600, tools: ["Web_Search", "Knowledge_Base", "Analytics_Engine"] },
  { id: "log-5", title: "Bug Triage Session", status: "completed" as const, created_at: "2026-03-15T11:00:00Z", updated_at: "2026-03-15T11:03:00Z", message_count: 5, token_estimate: 1900, tools: ["Code_Interpreter"] },
  { id: "log-6", title: "Email Campaign Draft", status: "failed" as const, created_at: "2026-03-15T09:00:00Z", updated_at: "2026-03-15T09:01:00Z", message_count: 3, token_estimate: 980, tools: ["File_Reader"] },
  { id: "log-7", title: "Database Schema Review", status: "completed" as const, created_at: "2026-03-14T15:00:00Z", updated_at: "2026-03-14T15:07:00Z", message_count: 9, token_estimate: 3400, tools: ["SQL_Query", "Code_Interpreter"] },
  { id: "log-8", title: "Onboarding Flow Redesign", status: "completed" as const, created_at: "2026-03-14T10:00:00Z", updated_at: "2026-03-14T10:08:00Z", message_count: 7, token_estimate: 2100, tools: ["Web_Search"] },
];
