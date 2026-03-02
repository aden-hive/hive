# 📚 Hive Codebase Documentation Index

## 📖 Complete Guide Set

I've created **4 comprehensive documentation files** to help you understand the Hive codebase from every angle:

### 🎯 Start Here First

**File**: `README_CODEBASE_GUIDES.md`

- Overview of all 4 guides
- Hive in 30 seconds
- Core architecture simplified
- Key files and concepts
- Learning progression
- Next steps
- **Reading time**: 10 minutes

---

## 📋 The 4 Guides

### 1️⃣ **CODEBASE_STRUCTURE.md** - The Complete Reference

**Purpose**: Understand how every piece of the codebase works

**Sections** (100+):

- Overview & philosophy
- High-level architecture
- Complete directory structure
- **Core Modules Deep Dive** (10+ modules explained):
  - Graph Module (nodes, execution)
  - Runtime Module (decision recording)
  - Builder Module (self-improvement)
  - Schemas Module (data models)
  - LLM Module (AI provider abstraction)
  - Storage Module (persistence)
  - MCP Module (Builder integration)
  - Credentials Module (security)
  - Testing Module (tests)
  - TUI Module (terminal UI)
- Execution flow (step-by-step)
- Key data structures
- Key subsystems
- Security & safety
- Testing structure
- Extension points
- Performance & observability
- Common patterns
- Debugging & troubleshooting
- Learning path
- Important files table

**Best for**:

- Deep understanding of a specific component
- Finding where specific functionality lives
- Understanding how components interact
- Troubleshooting complex issues
- Extending the framework

**Reading time**: 30-60 minutes (or reference as needed)

---

### 2️⃣ **ARCHITECTURE_VISUAL.md** - Diagrams & Visual Flow

**Purpose**: See how pieces connect and data flows through the system

**Sections**:

- **Module Dependency Map** - Visual hierarchy of all components
- **Node Execution Sequence** - Step-by-step what happens when a node runs
- **Data Structure Relationships** - How GraphSpec, Run, Decision, etc. relate
- **Self-Improvement Loop** - Visual cycle of analyze → improve → deploy
- **Integration Points** - How CLI, MCP, and storage connect
- **Performance Considerations** - Token usage, latency, concurrency, memory

**Best for**:

- Understanding the big picture
- Tracing data flow
- Seeing connections between modules
- Understanding execution sequence
- Explaining to others

**Reading time**: 15-20 minutes

---

### 3️⃣ **QUICK_REFERENCE.md** - Practical Quick Lookup

**Purpose**: Fast answers to common questions and tasks

**Sections**:

- Most important files (table with descriptions)
- Quick import guide (copy-paste imports)
- Quick start patterns:
  - Run an existing agent
  - Create a decision recording node
  - Analyze agent performance
  - Build a graph incrementally
- Common Q&A (15+ questions answered)
- Node type reference with examples
- Testing patterns
- File organization cheat sheet
- Learning progression
- Debugging checklist
- Getting help resources

**Best for**:

- "How do I...?" questions
- Code examples to copy-paste
- Quick lookups while coding
- Finding files by name
- Troubleshooting

**Reading time**: 5-10 minutes (reference as needed)

---

### 4️⃣ **README_CODEBASE_GUIDES.md** - Navigation & Overview

**Purpose**: Navigate all guides and get oriented

**Sections**:

- What you have here (this overview)
- Hive in 30 seconds
- Core architecture (simplified)
- Key directories
- 5 most important files
- Execution flow (simplified)
- Key concepts (5 main ideas)
- Common tasks & where to look
- Recommended learning order (4 weeks)
- Most important code snippets
- When things go wrong
- Where to find each type of information
- Verification checklist
- Next steps (3 options)
- Resources
- Document reference

**Best for**:

- Getting started
- Understanding the overall structure
- Finding which guide to read
- Learning progression
- Navigation

**Reading time**: 10 minutes

---

## 🗺️ How to Use These Guides

### Scenario 1: "I'm brand new to Hive"

1. Start with **README_CODEBASE_GUIDES.md** (this file)
2. Read sections: Hive in 30s → Core architecture → Key concepts
3. Then read **CODEBASE_STRUCTURE.md** sections 1-3
4. Then run: `hive run examples/templates/basic_agent`

### Scenario 2: "How do I implement X?"

1. Go to **QUICK_REFERENCE.md**
2. Find your task in "Common Tasks & Where to Look"
3. Or search Common Q&A section
4. Or check "Quick Start Patterns"
5. Reference **CODEBASE_STRUCTURE.md** for deeper understanding

### Scenario 3: "Something broke, how do I debug?"

1. Check **QUICK_REFERENCE.md** "Debugging Checklist"
2. Check "When Things Go Wrong" section
3. Reference **CODEBASE_STRUCTURE.md** "Debugging & Troubleshooting"
4. Look at similar tests in `core/tests/`

### Scenario 4: "I want to understand how X works deeply"

1. Search **CODEBASE_STRUCTURE.md** for X
2. It will tell you which file and line numbers
3. Read those sections, or go read the actual code
4. Cross-reference with **ARCHITECTURE_VISUAL.md** to see connections
5. Look for tests in `core/tests/` that exercise X

### Scenario 5: "I need to explain architecture to someone"

1. Use **ARCHITECTURE_VISUAL.md** diagrams
2. Back up with **CODEBASE_STRUCTURE.md** explanations
3. Reference **QUICK_REFERENCE.md** for quick facts

---

## 🎯 What Each Guide Answers

### CODEBASE_STRUCTURE.md Answers:

- What is [component] and how does it work?
- What are all the node types and when to use each?
- How does decision recording work?
- How does the self-improvement loop work?
- What's the execution flow from start to finish?
- Where is [functionality]?
- How do I extend/customize the framework?
- What security considerations are there?
- What are the key data structures?

### ARCHITECTURE_VISUAL.md Answers:

- How do these modules connect?
- What's the dependency tree?
- How does data flow through the system?
- What happens in each step of execution?
- How do these 5 things relate to each other?
- What's the big picture of self-improvement?

### QUICK_REFERENCE.md Answers:

- Where is the most important file for [task]?
- How do I [common task]?
- What's an example of [pattern]?
- How do I test [thing]?
- What imports do I need?
- What does this error mean?
- Where's the file I need?

### README_CODEBASE_GUIDES.md Answers:

- Which guide should I read?
- What should I learn first?
- How do these guides relate?
- What's a quick summary of Hive?
- How do I get started?

---

## 📚 Reading Recommendations by Role

### Software Engineer (Building Agents)

1. README_CODEBASE_GUIDES.md (overview)
2. ARCHITECTURE_VISUAL.md (understand flow)
3. QUICK_REFERENCE.md (copy-paste patterns)
4. CODEBASE_STRUCTURE.md (reference as needed)

### ML Engineer (Tuning Agent Behavior)

1. CODEBASE_STRUCTURE.md sections: "Builder Module", "Analysis"
2. QUICK_REFERENCE.md: "Analyze Agent Performance" pattern
3. ARCHITECTURE_VISUAL.md: "Self-Improvement Loop" section

### DevOps / Infrastructure

1. CODEBASE_STRUCTURE.md sections: "Storage Module", "Credentials Module", "MCP Module"
2. QUICK_REFERENCE.md: "Performance Considerations"
3. ARCHITECTURE_VISUAL.md: "Integration Points"

### Product Manager / Stakeholder

1. README_CODEBASE_GUIDES.md: "Hive in 30s", "Core Architecture"
2. ARCHITECTURE_VISUAL.md: "Self-Improvement Loop"
3. CODEBASE_STRUCTURE.md: "Typical Workflow"

### New Contributor

1. README_CODEBASE_GUIDES.md: Everything
2. CODEBASE_STRUCTURE.md: "Most Important Files", "Extension Points"
3. QUICK_REFERENCE.md: "Common Patterns"
4. core/tests/: Look at existing tests

---

## 🔍 How to Find Things

### "Where is [thing]?"

**Option 1**: Use QUICK_REFERENCE.md

- "File Organization Cheat Sheet" table
- Example: Need to handle credentials? → Look in framework/credentials/

**Option 2**: Use CODEBASE_STRUCTURE.md

- Search for the section on that topic
- Example: Search "Credentials Module" → See what files are there

**Option 3**: Use grep or file search

- Go to repository
- Search for the filename or class name

### "How do I [do something]?"

**Option 1**: Check QUICK_REFERENCE.md

- "Common Tasks & Where to Look" table
- "Quick Start Patterns" section
- "Common Q&A" section

**Option 2**: Check CODEBASE_STRUCTURE.md

- "Key Subsystems" section
- "Common Patterns" section
- "Extension Points" section

**Option 3**: Look at examples

- `core/examples/` directory
- `examples/templates/` directory

### "What does [error] mean?"

**Option 1**: QUICK_REFERENCE.md

- "When Things Go Wrong" section
- Maps error → likely cause → solution

**Option 2**: CODEBASE_STRUCTURE.md

- "Debugging & Troubleshooting" section
- Look for similar issues

**Option 3**: core/tests/

- Find a passing test that does what you want
- Compare with your code

---

## 📊 Document Statistics

| Document                  | Pages    | Sections | Tables  | Diagrams | Code Examples |
| ------------------------- | -------- | -------- | ------- | -------- | ------------- |
| CODEBASE_STRUCTURE.md     | 50+      | 100+     | 10+     | 20+      | 50+           |
| ARCHITECTURE_VISUAL.md    | 30+      | 10       | 5+      | 30+      | 15+           |
| QUICK_REFERENCE.md        | 20+      | 20       | 10+     | 5+       | 30+           |
| README_CODEBASE_GUIDES.md | 15+      | 15       | 5+      | 5+       | 10+           |
| **TOTAL**                 | **115+** | **145+** | **30+** | **60+**  | **105+**      |

---

## ✅ Pre-Reading Checklist

Before diving in, you should:

- [ ] Have Hive cloned locally (or know the path)
- [ ] Have Python 3.11+ installed
- [ ] Understand graph concepts (nodes, edges)
- [ ] Be familiar with async/await in Python
- [ ] Have read the main README.md in the repo

---

## 🚀 Getting Started (5 Steps)

1. **Read** (10 min): README_CODEBASE_GUIDES.md
2. **Scan** (5 min): ARCHITECTURE_VISUAL.md Module Dependency Map
3. **Try** (5 min): Run `hive run examples/templates/basic_agent`
4. **Reference** (ongoing): Use QUICK_REFERENCE.md for questions
5. **Deep Dive** (as needed): CODEBASE_STRUCTURE.md for understanding

**Total time to understand basics**: ~30 minutes  
**Time to implement first agent**: ~2 hours  
**Time to become proficient**: ~1-2 weeks

---

## 🎓 Learning Paths

### Path 1: Fast Track (2 hours)

1. README_CODEBASE_GUIDES.md (full read)
2. Run basic example
3. Read QUICK_REFERENCE.md "Quick Start Patterns"
4. Start building

### Path 2: Standard (1 day)

1. README_CODEBASE_GUIDES.md (full read)
2. ARCHITECTURE_VISUAL.md (full read)
3. CODEBASE_STRUCTURE.md sections 1-5
4. Run and analyze examples
5. Look at core/tests/
6. Start building

### Path 3: Comprehensive (1 week)

1. Read all 4 guides completely
2. Study core/framework/ source code
3. Read all tests
4. Build multiple agents
5. Contribute improvements
6. Become expert

---

## 💬 FAQ About These Guides

**Q: Is this replacing the official documentation?**
A: No! These guides complement the official docs. Use together:

- These guides: "How does this work?"
- Official docs: "How do I use this?" + API reference

**Q: Should I read all guides from start to finish?**
A: Not necessarily. Use as reference:

1. Start with README_CODEBASE_GUIDES.md
2. Then read only what you need
3. Come back to guides when you have questions

**Q: These seem long. Do I really need to read all of it?**
A: No! Most people only use:

1. README_CODEBASE_GUIDES.md (full, once)
2. QUICK_REFERENCE.md (frequent, as needed)
3. CODEBASE_STRUCTURE.md (occasional, for deep dives)

**Q: Is this kept up to date?**
A: These guides were created for Hive v0.4.2 (Feb 2026). Check the version tags in each document. As Hive evolves, some details may change. Use GitHub for latest info.

**Q: Can I contribute improvements to these guides?**
A: Absolutely! Submit PRs to improve accuracy, clarity, or add examples. These guides are part of the repository.

---

## 🔗 Quick Navigation

### By File Name

- Need executor? → CODEBASE_STRUCTURE.md "Graph Module"
- Need runtime? → CODEBASE_STRUCTURE.md "Runtime Module"
- Need builder? → CODEBASE_STRUCTURE.md "Builder Module"
- Need storage? → CODEBASE_STRUCTURE.md "Storage Module"
- Need examples? → CODEBASE_STRUCTURE.md "Examples & Documentation"

### By Topic

- How graphs work? → ARCHITECTURE_VISUAL.md "Node Execution Sequence"
- How self-improvement works? → ARCHITECTURE_VISUAL.md "Self-Improvement Loop"
- How to build something? → QUICK_REFERENCE.md "Quick Start Patterns"
- How to debug? → QUICK_REFERENCE.md "Debugging Checklist"
- How things connect? → ARCHITECTURE_VISUAL.md "Module Dependency Map"

### By Problem

- Can't find something → QUICK_REFERENCE.md "File Organization Cheat Sheet"
- Need code example → QUICK_REFERENCE.md "Quick Start Patterns"
- Understanding error → QUICK_REFERENCE.md "When Things Go Wrong"
- Deep dive needed → CODEBASE_STRUCTURE.md (search for topic)

---

## 🎯 Your Next Action

**Choose one**:

1. **New to codebase**: Read README_CODEBASE_GUIDES.md (starts here)
2. **Quick answer needed**: Go to QUICK_REFERENCE.md
3. **Understanding specific topic**: Search CODEBASE_STRUCTURE.md
4. **Need visual**: Check ARCHITECTURE_VISUAL.md
5. **Want to learn progressively**: Follow "Learning Paths" above

---

## 📝 Document Versions

| Document                  | Version | Created      | Updated |
| ------------------------- | ------- | ------------ | ------- |
| CODEBASE_STRUCTURE.md     | 1.0     | Feb 10, 2026 | -       |
| ARCHITECTURE_VISUAL.md    | 1.0     | Feb 10, 2026 | -       |
| QUICK_REFERENCE.md        | 1.0     | Feb 10, 2026 | -       |
| README_CODEBASE_GUIDES.md | 1.0     | Feb 10, 2026 | -       |

**For**: Hive v0.4.2  
**Audience**: Developers learning/working with Hive

---

**Happy coding! 🚀**

Need help? Check the guides or go to: https://github.com/adenhq/hive
