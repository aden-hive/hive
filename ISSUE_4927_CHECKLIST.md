# Issue #4927: DSA Mentor Agent Recipe - Implementation Checklist

## Overview
Create a complete DSA (Data Structures and Algorithms) Mentor Agent template that helps developers learn algorithms through guided hints, code review, weakness identification, and personalized practice plans.

---

## Phase 1: Setup & Planning ✅

### 1.1 Repository Setup
- [ ] Ensure you're on the latest main branch: `git pull upstream main`
- [ ] Create feature branch: `git checkout -b feat/templates/dsa-mentor-agent`

- [ ] Verify you're assigned to issue #4927 on GitHub
### 1.2 Directory Structure
- [ ] Create template directory: `examples/templates/dsa_mentor/`
- [ ] Create nodes subdirectory: `examples/templates/dsa_mentor/nodes/`
- [ ] Verify directory structure matches existing templates

### 1.3 Reference Review
- [ ] Review `examples/templates/marketing_agent/` structure
- [ ] Review `examples/templates/twitter_outreach/` for event_loop patterns
- [ ] Review `examples/templates/README.md` for template conventions
- [ ] Review `CONTRIBUTING.md` for code style and commit conventions

---

## Phase 2: Core Agent Files 📝

### 2.1 `__init__.py`
- [ ] Create package exports file
- [ ] Export: `DSAMentorAgent`, `goal`, `edges`, `nodes`, `default_config`
- [ ] Follow pattern from `marketing_agent/__init__.py`

### 2.2 `config.py`
- [ ] Create `RuntimeConfig` dataclass with:
  - [ ] `model` (default: "claude-haiku-4-5-20251001")
  - [ ] `max_tokens` (default: 2048)
  - [ ] `storage_path` (default: "~/.hive/storage")
  - [ ] `mock_mode` (default: False)
- [ ] Create `AgentMetadata` dataclass with:
  - [ ] `name`: "dsa_mentor"
  - [ ] `version`: "0.1.0"
  - [ ] `description`: "DSA Mentor Agent for algorithm learning"
  - [ ] `tags`: ["education", "dsa", "algorithms", "mentor", "template"]
- [ ] Create `default_config` and `metadata` instances

### 2.3 `agent.py` - Goal Definition
- [ ] Import required modules:
  - [ ] `from framework.graph import Goal, SuccessCriterion, Constraint, EdgeCondition, EdgeSpec`
  - [ ] `from framework.graph.edge import GraphSpec`
  - [ ] `from framework.graph.executor import GraphExecutor`
  - [ ] `from framework.runtime.core import Runtime`
  - [ ] `from framework.llm.anthropic import AnthropicProvider`
- [ ] Define `goal` with:
  - [ ] `id`: "dsa-mentor"
  - [ ] `name`: "DSA Mentor Agent"
  - [ ] `description`: Comprehensive description of mentor capabilities
  - [ ] **Success Criteria** (4 criteria):
    - [ ] `hint-quality`: Progressive hints without full solutions (weight: 0.3)
    - [ ] `code-review`: Reviews code for correctness/complexity (weight: 0.25)
    - [ ] `weakness-identification`: Identifies weak DSA areas (weight: 0.2)
    - [ ] `personalized-plan`: Suggests targeted practice problems (weight: 0.25)
  - [ ] **Constraints** (2 constraints):
    - [ ] `no-direct-solutions`: Never provide complete solutions (hard constraint)
    - [ ] `progressive-hints`: Hints should be progressive (soft constraint)
  - [ ] **Input Schema**:
    - [ ] `problem_statement` (string, required)
    - [ ] `user_code` (string, optional)
    - [ ] `user_question` (string, optional)
    - [ ] `difficulty_level` (string, optional)
  - [ ] **Output Schema**:
    - [ ] `hint` (string)
    - [ ] `code_review` (object, optional)
    - [ ] `weak_areas` (array, optional)
    - [ ] `practice_plan` (array, optional)

### 2.4 `agent.py` - Edges Definition
- [ ] Define edges list with:
  - [ ] `intake-to-analyze`: intake → analyze-problem (ON_SUCCESS)
  - [ ] `analyze-to-hint`: analyze-problem → provide-hint (ON_SUCCESS)
  - [ ] `hint-to-review`: provide-hint → review-code (CONDITIONAL, if code provided)
  - [ ] `review-to-weaknesses`: review-code → identify-weaknesses (ON_SUCCESS)
  - [ ] `weaknesses-to-practice`: identify-weaknesses → suggest-practice (ON_SUCCESS)
  - [ ] `hint-to-weaknesses`: provide-hint → identify-weaknesses (CONDITIONAL, if no code)
  - [ ] `hint-escalation`: provide-hint → provide-hint (CONDITIONAL, for hint level escalation)
- [ ] Set appropriate priorities for conditional edges
- [ ] Add descriptive edge descriptions

### 2.5 `agent.py` - Graph Structure
- [ ] Set `entry_node`: "intake"
- [ ] Define `entry_points`: `{"start": "intake"}`
- [ ] Set `terminal_nodes`: `["suggest-practice"]`
- [ ] Set `pause_nodes`: `[]` (or add if human approval needed)
- [ ] Import `all_nodes` from nodes module

### 2.6 `agent.py` - Agent Class
- [ ] Create `DSAMentorAgent` class:
  - [ ] `__init__` method accepting `config: RuntimeConfig | None`
  - [ ] `_build_graph` method returning `GraphSpec`
  - [ ] `_create_executor` method setting up Runtime and LLM
  - [ ] `run` async method executing the agent
- [ ] Create `default_agent = DSAMentorAgent()` instance

---

## Phase 3: Node Definitions 🧩

### 3.1 `nodes/__init__.py` - Imports
- [ ] Import `NodeSpec` from `framework.graph`
- [ ] Import all node definitions

### 3.2 Node 1: Intake Node
- [ ] Create `intake_node` with:
  - [ ] `id`: "intake"
  - [ ] `name`: "Intake"
  - [ ] `description`: "Collect problem statement, user code, and questions"
  - [ ] `node_type`: "event_loop"
  - [ ] `input_keys`: `[]`
  - [ ] `output_keys`: `["problem_statement", "user_code", "user_question", "difficulty_level"]`
  - [ ] `nullable_output_keys`: `["user_code", "user_question", "difficulty_level"]`
  - [ ] `client_facing`: `True`
  - [ ] **System Prompt**:
    - [ ] Greet user as DSA mentor
    - [ ] Ask for problem statement (required)
    - [ ] Ask for user code (optional)
    - [ ] Ask for specific question (optional)
    - [ ] Ask for difficulty level (optional)
    - [ ] Use `set_output` tool to store collected data
    - [ ] Be friendly and encouraging
  - [ ] `max_retries`: 3
  - [ ] `max_node_visits`: 1

### 3.3 Node 2: Analyze Problem Node
- [ ] Create `analyze_problem_node` with:
  - [ ] `id`: "analyze-problem"
  - [ ] `name`: "Analyze Problem"
  - [ ] `description`: "Classify problem by topic, difficulty, and key concepts"
  - [ ] `node_type`: "event_loop"
  - [ ] `input_keys`: `["problem_statement", "difficulty_level"]`
  - [ ] `output_keys`: `["problem_analysis"]`
  - [ ] `client_facing`: `False`
  - [ ] **System Prompt**:
    - [ ] Analyze the problem statement
    - [ ] Identify DSA topic (arrays, trees, DP, graphs, greedy, etc.)
    - [ ] Determine difficulty level if not provided
    - [ ] Extract key concepts and patterns
    - [ ] Identify common pitfalls
    - [ ] Output structured analysis as JSON
  - [ ] `max_retries`: 2
  - [ ] `max_node_visits`: 1

### 3.4 Node 3: Provide Hint Node
- [ ] Create `provide_hint_node` with:
  - [ ] `id`: "provide-hint"
  - [ ] `name`: "Provide Hint"
  - [ ] `description`: "Generate progressive hints without revealing solutions"
  - [ ] `node_type`: "event_loop"
  - [ ] `input_keys`: `["problem_analysis", "user_question", "hint_level"]`
  - [ ] `output_keys`: `["hint", "hint_level"]`
  - [ ] `nullable_output_keys`: `["hint_level"]`
  - [ ] `client_facing`: `True`
  - [ ] **System Prompt** (CRITICAL - must enforce no solutions):
    - [ ] NEVER provide complete solutions or working code
    - [ ] Start with vague hints (level 1) - guide thinking
    - [ ] Progressively get more specific (levels 2-4)
    - [ ] Focus on CONCEPT and APPROACH, not code
    - [ ] Ask leading questions
    - [ ] Implement hint escalation logic
    - [ ] Use `set_output` for hint and hint_level
  - [ ] `max_retries`: 3
  - [ ] `max_node_visits`: 5 (allow multiple hint levels)

### 3.5 Node 4: Review Code Node
- [ ] Create `review_code_node` with:
  - [ ] `id`: "review-code"
  - [ ] `name`: "Review Code"
  - [ ] `description`: "Review user code for correctness, complexity, and optimization"
  - [ ] `node_type`: "event_loop"
  - [ ] `input_keys`: `["user_code", "problem_analysis"]`
  - [ ] `output_keys`: `["code_review"]`
  - [ ] `client_facing`: `False`
  - [ ] **System Prompt**:
    - [ ] Check code correctness
    - [ ] Analyze time complexity (Big O)
    - [ ] Analyze space complexity
    - [ ] Identify bugs or edge cases
    - [ ] Suggest optimizations
    - [ ] Provide constructive feedback
    - [ ] Output structured review as JSON
  - [ ] `max_retries`: 2
  - [ ] `max_node_visits`: 1

### 3.5 Node 5: Identify Weaknesses Node
- [ ] Create `identify_weaknesses_node` with:
  - [ ] `id`: "identify-weaknesses"
  - [ ] `name`: "Identify Weaknesses"
  - [ ] `description`: "Identify weak DSA areas based on code review and problem history"
  - [ ] `node_type`: "event_loop"
  - [ ] `input_keys`: `["code_review", "problem_analysis", "user_history"]`
  - [ ] `output_keys`: `["weak_areas", "strength_areas"]`
  - [ ] `nullable_output_keys`: `["user_history"]`
  - [ ] `client_facing`: `False`
  - [ ] **System Prompt**:
    - [ ] Analyze code review for patterns
    - [ ] Identify weak topics (DP, graphs, greedy, etc.)
    - [ ] Identify strong areas
    - [ ] Prioritize weaknesses by frequency/severity
    - [ ] Output structured weakness analysis
  - [ ] `max_retries`: 2
  - [ ] `max_node_visits`: 1

### 3.6 Node 6: Suggest Practice Node
- [ ] Create `suggest_practice_node` with:
  - [ ] `id`: "suggest-practice"
  - [ ] `name`: "Suggest Practice"
  - [ ] `description`: "Create personalized practice plan based on weaknesses"
  - [ ] `node_type`: "event_loop"
  - [ ] `input_keys`: `["weak_areas", "problem_analysis", "difficulty_level"]`
  - [ ] `output_keys`: `["practice_plan"]`
  - [ ] `client_facing`: `True`
  - [ ] **System Prompt**:
    - [ ] Create personalized practice plan
    - [ ] Recommend 3-5 problems per weak area
    - [ ] Suggest difficulty progression
    - [ ] Include problem descriptions or links
    - [ ] Prioritize by weakness severity
    - [ ] Output structured practice plan
  - [ ] `max_retries`: 2
  - [ ] `max_node_visits`: 1

### 3.7 `nodes/__init__.py` - Export
- [ ] Create `all_nodes` list with all 6 nodes
- [ ] Export all nodes for use in `agent.py`

---

## Phase 4: CLI & Entry Point 🖥️

### 4.1 `__main__.py`
- [ ] Create CLI entry point
- [ ] Import `DSAMentorAgent` and `default_config`
- [ ] Create default input data example:
  ```python
  {
    "problem_statement": "Find two numbers in array that sum to target",
    "user_code": "def two_sum(nums, target): ...",
    "user_question": "Is my approach optimal?",
    "difficulty_level": "medium"
  }
  ```
- [ ] Support `--input` JSON argument
- [ ] Run agent with `asyncio.run(agent.run(input_data))`
- [ ] Print results as formatted JSON

---

## Phase 5: Documentation 📚

### 5.1 `README.md`
- [ ] Create comprehensive README with:
  - [ ] **Title**: "Template: DSA Mentor Agent"
  - [ ] **Description**: What the agent does
  - [ ] **Workflow Diagram**: ASCII art showing node flow
  - [ ] **Nodes Table**: All 6 nodes with types and descriptions
  - [ ] **Usage Examples**:
    - [ ] Basic usage command
    - [ ] With custom input JSON
    - [ ] Interactive mode example
  - [ ] **Features**:
    - [ ] Progressive hint system
    - [ ] Code review capabilities
    - [ ] Weakness identification
    - [ ] Personalized practice plans
  - [ ] **Escalation Logic**: Document all escalation scenarios
  - [ ] **Customization Ideas**:
    - [ ] Add LeetCode integration
    - [ ] Add progress tracking
    - [ ] Add GitHub Gist storage
  - [ ] **File Structure**: Directory tree
  - [ ] **Example Interactions**: Sample conversations

### 5.2 Update Templates README
- [ ] Add DSA Mentor to `examples/templates/README.md`
- [ ] Add to "Available templates" table
- [ ] Include description and use case

---

## Phase 6: Testing & Validation 🧪

### 6.1 Basic Functionality Tests
- [ ] Test agent loads without errors
- [ ] Test with minimal input (problem_statement only)
- [ ] Test with full input (all fields)
- [ ] Test hint progression (multiple hint levels)
- [ ] Test code review path
- [ ] Test weakness identification
- [ ] Test practice plan generation

### 6.2 Edge Cases
- [ ] Test with empty user_code (should skip review)
- [ ] Test with invalid problem statement
- [ ] Test hint escalation (user asks for solution)
- [ ] Test multiple hint requests
- [ ] Test with no weak areas identified

### 6.3 Validation
- [ ] Run `make check` - ensure no linting errors
- [ ] Run `make format` - ensure code is formatted
- [ ] Verify agent.json structure (if exported)
- [ ] Test agent runs: `uv run python -m examples.templates.dsa_mentor`
- [ ] Test with CLI input: `--input '{"problem_statement": "..."}'`

### 6.4 Integration Tests
- [ ] Test with different LLM providers (if applicable)
- [ ] Test in mock mode
- [ ] Test with real DSA problems:
  - [ ] Easy: Two Sum
  - [ ] Medium: Binary Tree Inorder Traversal
  - [ ] Hard: Merge K Sorted Lists

---

## Phase 7: Code Quality ✨

### 7.1 Code Style
- [ ] Follow Python 3.11+ syntax
- [ ] Add type hints to all functions
- [ ] Add docstrings to classes and methods
- [ ] Follow PEP 8 style guide
- [ ] Use meaningful variable names
- [ ] Keep functions focused and small

### 7.2 Ruff Compliance
- [ ] Run `make check` in `core/` directory
- [ ] Run `make check` in `tools/` directory
- [ ] Fix all linting errors
- [ ] Ensure line length ≤ 100 characters
- [ ] Verify import sorting (stdlib, third-party, first-party, local)

### 7.3 Error Handling
- [ ] Add proper error handling in agent class
- [ ] Handle missing input gracefully
- [ ] Provide helpful error messages
- [ ] Validate input schemas

---

## Phase 8: Git & PR Preparation 📤

### 8.1 Git Workflow
- [ ] Stage all new files: `git add examples/templates/dsa_mentor/`
- [ ] Stage README updates: `git add examples/templates/README.md`
- [ ] Review changes: `git status` and `git diff`

### 8.2 Commit
- [ ] Commit with conventional commit format:
  ```
  feat(templates): add DSA mentor agent template
  
  - Add DSA mentor agent with 6 nodes (intake, analyze, hint, review, weaknesses, practice)
  - Implement progressive hint system without revealing solutions
  - Add code review and weakness identification capabilities
  - Create personalized practice plan generation
  - Add comprehensive README with usage examples
  
  Closes #4927
  ```
- [ ] Verify commit message follows CONTRIBUTING.md guidelines

### 8.3 Pre-PR Checklist
- [ ] All tests pass locally
- [ ] `make check` passes
- [ ] `make test` passes (if applicable)
- [ ] README is complete and accurate
- [ ] Code is properly formatted
- [ ] No console.log or debug statements
- [ ] All TODOs addressed or documented

### 8.4 PR Description
- [ ] Create PR with title: `feat(templates): add DSA mentor agent template`
- [ ] Link to issue: `Closes #4927`
- [ ] Add description:
  - [ ] Summary of changes
  - [ ] What the agent does
  - [ ] How to test it
  - [ ] Screenshots/examples (if applicable)
- [ ] Request review from maintainers

---

## Phase 9: Post-PR Follow-up 🔄

### 9.1 Address Feedback
- [ ] Respond to review comments
- [ ] Make requested changes
- [ ] Update PR with fixes
- [ ] Re-run tests after changes

### 9.2 Documentation Updates
- [ ] Update CHANGELOG.md if requested
- [ ] Add to examples showcase (if applicable)
- [ ] Update any related documentation

### 9.3 Final Validation
- [ ] Ensure CI passes
- [ ] Verify agent works in production environment
- [ ] Test with different users/scenarios

---

## Phase 10: Optional Enhancements 🚀

### 10.1 Advanced Features (Future)
- [ ] Add LeetCode API integration for problem fetching
- [ ] Add progress tracking with local storage
- [ ] Add GitHub Gist integration for solution storage
- [ ] Add Slack/Discord reminders
- [ ] Add Notion integration for progress notes
- [ ] Add Codeforces integration

### 10.2 Template Variations
- [ ] Create recipe version (markdown only)
- [ ] Create simplified version for beginners
- [ ] Create advanced version with more features

---

## Notes & Reminders 📝

### Critical Requirements
- ✅ **NEVER provide complete solutions** - this is a hard constraint
- ✅ **Progressive hints only** - start vague, get specific
- ✅ **Client-facing nodes** - intake, hint, and practice nodes should be interactive
- ✅ **Follow existing template patterns** - consistency is key

### Key Files to Create
1. `examples/templates/dsa_mentor/__init__.py`
2. `examples/templates/dsa_mentor/__main__.py`
3. `examples/templates/dsa_mentor/agent.py`
4. `examples/templates/dsa_mentor/config.py`
5. `examples/templates/dsa_mentor/nodes/__init__.py`
6. `examples/templates/dsa_mentor/README.md`

### Testing Commands
```bash
# Run the agent
uv run python -m examples.templates.dsa_mentor

# With input
uv run python -m examples.templates.dsa_mentor --input '{"problem_statement": "..."}'

# Check code quality
make check

# Run tests
make test
```

---

## Progress Tracking

**Started**: _______________  
**Phase 1 Complete**: _______________  
**Phase 2 Complete**: _______________  
**Phase 3 Complete**: _______________  
**Phase 4 Complete**: _______________  
**Phase 5 Complete**: _______________  
**Phase 6 Complete**: _______________  
**Phase 7 Complete**: _______________  
**Phase 8 Complete**: _______________  
**PR Submitted**: _______________  
**Merged**: _______________

---

**Total Checklist Items**: ~150+  
**Estimated Time**: 8-12 hours  
**Priority**: High (assigned issue)
