# 🎨 Frontend Challenge

Build beautiful, functional interfaces for AI agent management! This challenge is for frontend engineers who want to contribute to Honeycomb, Aden's dashboard.

**Difficulty:** Intermediate
**Time:** 1-2 hours
**Prerequisites:** Complete [Getting Started](./01-getting-started.md), React/TypeScript experience

---

## Part 1: Codebase Exploration (15 points)

### Task 1.1: Tech Stack Analysis 🔍
Explore the `honeycomb/` directory and answer:

1. What React version is used?
2. What styling solution is used? (Tailwind, CSS Modules, etc.)
3. What state management approach is used?
4. What charting library is used for analytics?
5. How does the frontend communicate with the backend in real-time?

### Task 1.2: Component Structure 📁
Map out the component architecture:

1. List the main page components (routes)
2. Find and describe 3 reusable components
3. Where are TypeScript types defined for agent data?
4. How is authentication handled in the frontend?

### Task 1.3: Design System 🎨
Analyze the UI patterns:

1. What UI component library is used? (Radix, shadcn, etc.)
2. Find 3 custom components that aren't from a library
3. What color scheme/theme approach is used?
4. How are loading and error states typically handled?

---

## Part 2: UI/UX Analysis (20 points)

### Task 2.1: Dashboard Critique 📊
Based on the codebase and agent control types, analyze what the dashboard likely shows:

1. What key metrics would you display for agent monitoring?
2. How would you visualize the agent graph/connections?
3. What real-time updates are most important to show?
4. Critique: What could be improved in the current approach?

### Task 2.2: User Flow Design 🔄
Design the user flow for this feature:

**Feature:** "Create New Agent from Goal"

Map out:
1. Entry point (where does the user start?)
2. Step-by-step screens needed
3. Form fields and validation
4. Success/error states
5. How to show agent generation progress

Provide a wireframe (can be ASCII, hand-drawn, or Figma):

```
+----------------------------------+
|  Create New Agent                |
|----------------------------------|
|  Step 1: Define Your Goal        |
|  +----------------------------+  |
|  | Describe what you want     |  |
|  | your agent to achieve...   |  |
|  +----------------------------+  |
|                                  |
|  [ ] Include human checkpoints   |
|  [ ] Enable cost controls        |
|                                  |
|  [Cancel]           [Next Step]  |
+----------------------------------+
```

### Task 2.3: Accessibility Audit ♿
Consider accessibility for the agent dashboard:

1. List 5 accessibility requirements for a data-heavy dashboard
2. How would you make real-time updates accessible?
3. What keyboard navigation is essential?
4. How would you handle screen readers for the agent graph visualization?

---

## Part 3: Implementation Challenges (35 points)

### Task 3.1: Build a Component 🧱
Create a React component: `AgentStatusCard`

Requirements:
- Display agent name, status, and key metrics
- Status: online (green), degraded (yellow), offline (red), unknown (gray)
- Show: requests/min, success rate, avg latency, cost today
- Include a mini sparkline chart for requests over last hour
- Expandable to show more details
- TypeScript with proper types

```tsx
interface AgentStatusCardProps {
  agent: {
    id: string;
    name: string;
    status: 'online' | 'degraded' | 'offline' | 'unknown';
    metrics: {
      requestsPerMinute: number;
      successRate: number;
      avgLatency: number;
      costToday: number;
      requestHistory: number[]; // last 60 minutes
    };
  };
  onExpand?: () => void;
  expanded?: boolean;
}

export function AgentStatusCard({ agent, onExpand, expanded }: AgentStatusCardProps) {
  // Your implementation
}
```

### Task 3.2: Real-time Hook 🔌
Create a custom hook for real-time agent metrics:

```tsx
interface UseAgentMetricsOptions {
  agentId: string;
  refreshInterval?: number;
}

interface UseAgentMetricsResult {
  metrics: AgentMetrics | null;
  isLoading: boolean;
  error: Error | null;
  lastUpdated: Date | null;
}

function useAgentMetrics(options: UseAgentMetricsOptions): UseAgentMetricsResult {
  // Your implementation
  // Should handle:
  // - WebSocket subscription for real-time updates
  // - Fallback to polling if WebSocket unavailable
  // - Cleanup on unmount
  // - Error handling and retry logic
}
```

### Task 3.3: Data Visualization 📈
Design and implement a cost breakdown chart component:

Requirements:
- Show cost by model (GPT-4, Claude, etc.) as a donut/pie chart
- Show cost over time as a line/area chart
- Toggle between daily/weekly/monthly views
- Animate transitions between views
- Show tooltip with details on hover

Provide:
1. Component interface/props
2. Implementation (can use Recharts, Vega, or any library)
3. Example mock data
4. Responsive design considerations

---

## Part 4: Advanced Frontend (30 points)

### Task 4.1: Agent Graph Visualization 🕸️
Design how to visualize the agent graph:

**Challenge:** Show a dynamic graph where:
- Nodes are agents
- Edges are connections between agents
- Real-time data flows are animated
- Users can zoom, pan, and click for details

Provide:
1. Library choice and justification (D3, React Flow, Cytoscape, etc.)
2. Component architecture
3. Performance considerations for 50+ nodes
4. Interaction design (how users explore the graph)
5. Code sketch for the main component

### Task 4.2: Optimistic UI for Budget Controls 💰
Implement optimistic UI for budget updates:

**Scenario:** User changes an agent's budget limit
- Update should appear instantly
- Backend validation may reject the change
- Must handle race conditions with real-time updates

Provide:
1. State management approach
2. Rollback mechanism on failure
3. Conflict resolution strategy
4. User feedback design

```tsx
function useBudgetUpdate(agentId: string) {
  // Your implementation showing:
  // - Optimistic update
  // - Server sync
  // - Rollback on error
  // - Conflict handling
}
```

### Task 4.3: Performance Optimization ⚡
The dashboard shows data for 100+ agents with real-time updates.

Design optimizations for:

1. **Rendering:** How to prevent unnecessary re-renders?
2. **Data:** How to handle high-frequency WebSocket updates?
3. **Memory:** How to prevent memory leaks with subscriptions?
4. **Initial Load:** How to prioritize visible content?

Provide specific techniques and code examples for each.

---

## Submission Checklist

- [ ] All Part 1 exploration answers
- [ ] Part 2 wireframes and design analysis
- [ ] Part 3 component implementations
- [ ] Part 4 advanced designs

### How to Submit

1. Create a GitHub Gist with your answers
2. Name it `aden-frontend-YOURNAME.md`
3. Include code files as separate Gist files
4. If you created working code, include a CodeSandbox/StackBlitz link
5. Email to `careers@adenhq.com`
   - Subject: `[Frontend Challenge] Your Name`

---

## Scoring

| Section | Points |
|---------|--------|
| Part 1: Exploration | 15 |
| Part 2: UI/UX | 20 |
| Part 3: Implementation | 35 |
| Part 4: Advanced | 30 |
| **Total** | **100** |

**Passing score:** 75+ points

---

## Bonus Points (+20)

- **+10:** Create a working prototype in CodeSandbox
- **+5:** Submit a PR improving existing UI
- **+5:** Create a Figma design for a new feature

---

## Resources

- [React Documentation](https://react.dev)
- [Tailwind CSS](https://tailwindcss.com)
- [Radix UI](https://radix-ui.com)
- [Recharts](https://recharts.org)
- [React Flow](https://reactflow.dev) (for graph visualization)

---

Good luck! We love engineers who care about user experience! 🎨✨
