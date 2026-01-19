Product Roadmap

Aden Agent Framework aims to help developers build outcome orienated, self-adaptive agents. Please find our roadmap here

```mermaid
timeline
    title Aden Agent Framework Roadmap
    section MVP Phase
        Architecture : Node-Based : Python SDK : Flexible Edges : Hooks : Tool Use
        Capabilities : Goal Creation : Worker Agents Generation: File/Memory Tools : Multi-Agent : Human-in-the-Loop
        Foundations : Basic Eval : Docker Deployment : Documentation
    section Post-MVP
        Intelligence : Guardrails : Streaming : Semantic Search
        Ecosystem : Javascript SDK : Cloud Deployment : CI/CD : Autonomous Agent
        Agent Templates : Sales Agent : Marketing Agent : Analytics Agent
```

---

## Phase 1: MVP and SDK backbone

### Backbone Architecture
- [ ] **Node-Based Architecture (Agent as a node)**
    - [ ] Object schema definition
    - [ ] Node wrapper SDK
    - [ ] Shared memory access
    - [ ] Default monitoring hooks
    - [ ] Tool access layer
    - [ ] LLM integration layer (Natively supports all mainstream LLMs through LiteLLM)
- [ ] **Communication protocol between nodes**
- [ ] **[Coding Agent] Goal Creation Session**
    - [ ] Instruction for coding agents supporting generation of goal with multiple rounds of conversation
    - [ ] Goal Object schema definition
    - [ ] Support generating test cases for goal
- [ ] **[Coding Agent] Worker Agent Creation**
    - [ ] Coding Agent tools
    - [ ] Use Template Agent as a start

### Essential Tools
- [ ] **File Use**
- [ ] **Memory Tools**
    - [ ] STM Layer Tool (state-based short-term memory)
    - [ ] LTM Layer Tool (RLM - long-term memory)
- [ ] **Infrastructure Tools**
    - [ ] Runtime Log Tool (logs for coding agent)
    - [ ] Audit Trail Tool (decision timeline generation)

### Memory & File System
- [ ] DB for long-term persistent memory (Filesystem as durable scratchpad pattern)
- [ ] Session Local memory isolation

### Basic Eval System
- [ ] Test Driven
- [ ] Failure recording mechanism
- [ ] SDK for defining failure conditions
- [ ] Basic observability hooks
- [ ] User-driven log analysis (OSS approach)

### Data Validation
- [ ] Natively Support data validation of LLMs output with Pydantic

### Developer Experience (MVP)
- [ ] **Documentation**
    - [ ] Quick start guide
    - [ ] Goal creation guide
    - [ ] Agent creation guide
- [ ] **Distribution**
    - [ ] PyPI package
    - [ ] Docker image on Docker Hub

### Sample Agents
- [ ] Knowledge Agent
- [ ] Blog Writer Agent
- [ ] SDR Agent

---

## Phase 2: Post-MVP & Scaling

### Basic Guardrails
- [ ] Support Basic Monitoring from Agent node SDK
- [ ] SDK guardrail implementation (in node)
- [ ] Guardrail type support (Determined Condition as Guardrails)

### Agent Capability
- [ ] Streaming mode support

### Cross-Platform
- [ ] Javascript / TypeScript Version SDK

### File System Enhancement
- [ ] Semantic Search integration
- [ ] Interactive File System in product (frontend integration)

### More Worker Tools
- [ ] Custom Tool Integrator
- [ ] Integration as a tool (Credential Store & Support)
- [ ] **Core Agent Tools**
    - [ ] Node Discovery Tool
    - [ ] HITL Tool (pause execution for human approval)
    - [ ] Wake-up Tool (resume agent tasks)

### Deployment (Self-Hosted)
- [ ] Docker container standardization
- [ ] Headless backend execution
- [ ] Exposed API for frontend attachment
- [ ] Local monitoring & observability (from hive repo)
- [ ] Basic lifecycle APIs (Start, Stop, Pause, Resume)

### Deployment (Cloud)
- [ ] Cloud Service Options
- [ ] Support deployment to 3rd-party platforms
- [ ] Self-deploy + orchestrator connection
- [ ] **CI/CD Pipeline**
    - [ ] Automated test execution
    - [ ] Agent version control
    - [ ] All tests must pass for deployment

### Developer Experience Enhancement
- [ ] Detailed Tool usage documentation
- [ ] Recipe for common agent use cases
- [ ] Discord Support Channel

### More Agent Templates
- [ ] GTM Sales Agent (workflow)
- [ ] GTM Marketing Agent (workflow)
- [ ] Analytics Agent
- [ ] Training Agent
- [ ] Smart Entry / Form Agent (self-evolution emphasis)