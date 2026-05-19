FULL CALL PATH: FRONTEND SESSION START TO AGENT EXECUTION

===================================================================
STEP 1: FRONTEND HTTP REQUEST (API ENTRY POINT)
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/server/routes_sessions.py
ENDPOINT: POST /api/sessions (line 103)
FUNCTION: async def handle_create_session(request: web.Request) -> web.Response

- Accepts optional "agent_path" in request body
- If agent_path provided: calls manager.create_session_with_worker()
- If no agent_path: calls manager.create_session()
- Returns 201 with session details

CALL CHAIN:
handle_create_session (line 103)
  ├─ validate_agent_path(agent_path) [line 128]
  ├─ manager.create_session_with_worker() [line 135] OR manager.create_session() [line 143]
  └─ _session_to_live_dict(session) [line 169]


===================================================================
STEP 2: SESSION CREATION (MANAGER LAYER)
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/server/session_manager.py

FLOW A: Create Session with Worker (Single Step)
─────────────────────────────────────────────────

FUNCTION: async def create_session_with_worker() (line 128)
  - Creates session infrastructure (EventBus, LLM)
  - Loads worker agent
  - Starts queen
  
CALL SEQUENCE:
create_session_with_worker (line 128)
  ├─ _create_session_core(model=model) [line 150]
  │  │ Creates RuntimeConfig, LiteLLMProvider, EventBus
  │  │ Creates Session dataclass with event_bus and llm
  │  │ Stores in self._sessions[resolved_id]
  │  └─ returns Session object
  │
  ├─ _load_worker_core(session, agent_path, worker_id) [line 153]
  │  │ Loads AgentRunner (blocking I/O via executor)
  │  │ Calls runner._setup(event_bus=session.event_bus)
  │  │ Starts worker_runtime if not already running
  │  │ Cleans up stale sessions on disk
  │  │ Updates session.runner, session.worker_runtime, etc.
  │  └─ returns None (modifies session in-place)
  │
  ├─ build_worker_profile(session.worker_runtime) [line 162]
  │  └─ returns worker identity string for queen
  │
  └─ _start_queen(session, worker_identity) [line 166]
     (See STEP 3 below)


FLOW B: Create Queen-Only Session
─────────────────────────────────

FUNCTION: async def create_session() (line 109)
  
CALL SEQUENCE:
create_session (line 109)
  ├─ _create_session_core(session_id, model) [line 120]
  │  └─ (same as above)
  │
  └─ _start_queen(session, worker_identity=None) [line 123]
     (See STEP 3 below)


===================================================================
STEP 3: WORKER AGENT LOADING (AGENT RUNNER LAYER)
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/runner/runner.py

FUNCTION: AgentRunner.load() (line 789) - Static method
CALLED BY: _load_worker_core() via loop.run_in_executor() (line 213-220)

LOAD SEQUENCE:
load(agent_path, model, interactive, skip_credential_validation) (line 789)
  │
  ├─ Tries agent.py path first:
  │  └─ agent_py = agent_path / "agent.py"
  │     ├─ _import_agent_module(agent_path) [line 823]
  │     │  (Dynamically imports agent Python module)
  │     │
  │     ├─ Extract goal, nodes, edges from module [line 825-827]
  │     ├─ Build GraphSpec from module variables [line 854-876]
  │     └─ return AgentRunner(...) [line 889]
  │
  └─ Fallback to agent.json if no agent.py:
     └─ load_agent_export(agent_json_path) [line 911]
        └─ return AgentRunner(...) [line 913]

RETURN: AgentRunner instance (NOT YET STARTED)

AgentRunner.__init__() (line 609) - Constructor
  ├─ Stores graph, goal, model, storage_path
  ├─ _validate_credentials() [line 684]
  │  (Checks required credentials are available)
  │
  ├─ Auto-discover tools from tools.py [line 687-689]
  │  └─ _tool_registry.discover_from_module(tools_path)
  │
  └─ Auto-discover MCP servers from mcp_servers.json [line 697-699]
     └─ _load_mcp_servers_from_config(mcp_config_path)

NOTE: __init__ does NOT call _setup() yet — that happens later.


===================================================================
STEP 4: WORKER RUNTIME SETUP (AFTER LOAD)
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/runner/runner.py

FUNCTION: runner._setup(event_bus=None) (line 1012)
CALLED BY: _load_worker_core() via loop.run_in_executor() (line 225-227)

SETUP SEQUENCE:
_setup(event_bus=session.event_bus) (line 1012)
  │
  ├─ Configure logging [line 1015-1017]
  │  └─ configure_logging(level="INFO", format="auto")
  │
  ├─ Create LLM provider [line 1031-1145]
  │  ├─ Check for mock mode → MockLLMProvider
  │  ├─ Check for Claude Code subscription → LiteLLMProvider with OAuth
  │  ├─ Check for Codex subscription → LiteLLMProvider with Codex API
  │  ├─ Fallback to environment variables or credential store
  │  └─ self._llm = <LLMProvider instance>
  │
  ├─ Auto-register GCU MCP server if needed [line 1148-1170]
  │
  ├─ Auto-register file tools MCP server [line 1173-1192]
  │
  ├─ Get all tools from registry [line 1195-1196]
  │  └─ tools = list(self._tool_registry.get_tools().values())
  │
  └─ _setup_agent_runtime(tools, tool_executor, accounts_prompt, event_bus) [line 1215]
     (See STEP 5 below)


===================================================================
STEP 5: AGENT RUNTIME CREATION (CORE RUNTIME INSTANTIATION)
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/runner/runner.py
          (method _setup_agent_runtime, line 1299)
          & /Users/timothy/repo/hive/core/framework/runtime/agent_runtime.py
          (function create_agent_runtime, line 1642)

FUNCTION: runner._setup_agent_runtime() (line 1299)
CALLED BY: runner._setup() [line 1215]

SETUP SEQUENCE:
_setup_agent_runtime(tools, tool_executor, accounts_prompt, event_bus) (line 1299)
  │
  ├─ Convert AsyncEntryPointSpec to EntryPointSpec [line 1310-1323]
  │
  ├─ Create primary entry point for entry_node [line 1328-1338]
  │
  ├─ Create RuntimeLogStore [line 1341]
  │
  ├─ Create CheckpointConfig [line 1346-1352]
  │  (Enables checkpointing by default for resumable sessions)
  │
  └─ create_agent_runtime(
       graph=self.graph,
       goal=self.goal,
       storage_path=self._storage_path,
       entry_points=entry_points,
       llm=self._llm,
       tools=tools,
       tool_executor=tool_executor,
       runtime_log_store=log_store,
       checkpoint_config=checkpoint_config,
       event_bus=event_bus,
     ) [line 1364]

NEXT: create_agent_runtime() in agent_runtime.py

FUNCTION: create_agent_runtime() (line 1642)

CREATION SEQUENCE:
create_agent_runtime(...) (line 1642)
  │
  ├─ Auto-create RuntimeLogStore if needed [line 1689-1694]
  │
  ├─ Create AgentRuntime instance [line 1696]
  │  └─ runtime = AgentRuntime(
  │       graph=graph,
  │       goal=goal,
  │       storage_path=storage_path,
  │       llm=llm,
  │       tools=tools,
  │       tool_executor=tool_executor,
  │       runtime_log_store=runtime_log_store,
  │       checkpoint_config=checkpoint_config,
  │       event_bus=event_bus,  # <-- SHARED WITH QUEEN/JUDGE
  │     ) [line 1696]
  │
  ├─ Register each entry point [line 1713-1714]
  │  └─ runtime.register_entry_point(spec) for each spec
  │
  └─ return runtime  [line 1716]

RETURN: AgentRuntime instance (NOT YET STARTED)


===================================================================
STEP 6: AGENT RUNTIME INITIALIZATION (RUNTIME CLASS)
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/runtime/agent_runtime.py

FUNCTION: AgentRuntime.__init__() (line 118)

INITIALIZATION:
AgentRuntime.__init__(...) (line 118)
  │
  ├─ Initialize storage (ConcurrentStorage) [line 175-179]
  │
  ├─ Initialize SessionStore for unified sessions [line 182]
  │
  ├─ Initialize shared components:
  │  ├─ SharedStateManager [line 185]
  │  ├─ EventBus (or use shared one) [line 186]
  │  └─ OutcomeAggregator [line 187]
  │
  ├─ Store LLM, tools, tool_executor [line 190-195]
  │
  ├─ Initialize entry points dict [line 198]
  │
  ├─ Initialize execution streams dict [line 199]
  │
  └─ Set state to NOT running [line 211: self._running = False]

RETURN: Unstarted AgentRuntime instance

NEXT: register_entry_point() for each entry point

FUNCTION: AgentRuntime.register_entry_point() (line 218)
  ├─ Validate entry node exists [line 236-237]
  └─ Store spec in self._entry_points[spec.id] [line 239]


===================================================================
STEP 7: QUEEN STARTUP (CONCURRENT WITH WORKER)
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/server/session_manager.py

FUNCTION: _start_queen() (line 394)
CALLED BY: create_session() OR create_session_with_worker()

QUEEN STARTUP SEQUENCE:
_start_queen(session, worker_identity, initial_prompt) (line 394)
  │
  ├─ Create queen directory [line 410-411]
  │  └─ ~/.hive/queen/session/{session.id}/
  │
  ├─ Register MCP coding tools [line 414-424]
  │  └─ Load from hive_coder/mcp_servers.json
  │
  ├─ Register lifecycle tools [line 428-436]
  │  └─ register_queen_lifecycle_tools()
  │
  ├─ Register worker monitoring tools if worker exists [line 438-448]
  │  └─ register_worker_monitoring_tools()
  │
  ├─ Build queen graph with adjusted prompt [line 454-478]
  │  ├─ Add worker_identity to system prompt
  │  └─ Filter tools to available ones
  │
  ├─ Create queen executor task [line 482-519]
  │  └─ async def _queen_loop():
  │     ├─ Create GraphExecutor [line 484]
  │     ├─ Call executor.execute(graph=queen_graph, goal=queen_goal, ...) [line 501]
  │     └─ (Queen stays alive forever unless error)
  │
  └─ session.queen_task = asyncio.create_task(_queen_loop()) [line 519]

RESULT: Queen task starts in background, never awaited


===================================================================
STEP 8: WORKER RUNTIME START
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/runtime/agent_runtime.py

FUNCTION: AgentRuntime.start() (line 263)
CALLED BY: _load_worker_core() [line 234 in session_manager.py]

START SEQUENCE:
await runtime.start() (line 263)
  │
  ├─ Mark as running [line 266: self._running = True]
  │
  ├─ Create ExecutionStream for each registered entry point [loop in start()]
  │  └─ stream = ExecutionStream(
  │       stream_id=entry_point.id,
  │       entry_spec=entry_point_spec,
  │       graph=self.graph,
  │       goal=self.goal,
  │       state_manager=self._state_manager,
  │       storage=self._storage,
  │       outcome_aggregator=self._outcome_aggregator,
  │       event_bus=self._event_bus,  # <-- SHARED
  │       llm=self._llm,
  │       tools=self._tools,
  │       tool_executor=self._tool_executor,
  │     )
  │
  ├─ Start each stream [await stream.start() for each stream]
  │
  ├─ Setup webhook server if configured [line ~350]
  │
  ├─ Register event-driven entry points (timers, webhooks) [line ~400]
  │
  └─ self._running = True [line 266]

RESULT: AgentRuntime ready to execute


===================================================================
STEP 9: TRIGGER EXECUTION (MANUAL VIA ENTRY POINT)
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/runtime/agent_runtime.py

FUNCTION: async def trigger() (line 790)
CALLED BY: Frontend API, timers, webhooks, manual calls

TRIGGER SEQUENCE:
await runtime.trigger(entry_point_id, input_data, session_state) (line 790)
  │
  ├─ Verify runtime is running [line 818]
  │
  ├─ Resolve stream for entry point [line 821]
  │  └─ stream = self._resolve_stream(entry_point_id)
  │
  └─ return await stream.execute(input_data, correlation_id, session_state) [line 825]
     (See STEP 10 below)

RETURNS: execution_id (non-blocking)


===================================================================
STEP 10: EXECUTION STREAM MANAGEMENT
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/runtime/execution_stream.py

FUNCTION: ExecutionStream.execute() (line 426)
CALLED BY: AgentRuntime.trigger() [line 825]

EXECUTE SEQUENCE:
await stream.execute(input_data, correlation_id, session_state) (line 426)
  │
  ├─ Verify stream is running [line 445]
  │
  ├─ Cancel any existing running executions [line 453-467]
  │  (Only one execution per stream at a time)
  │
  ├─ Generate execution_id [line 473-487]
  │  ├─ If resuming: use resume_session_id [line 474]
  │  ├─ Otherwise: generate from SessionStore [line 476]
  │  └─ Format: session_{timestamp}_{uuid}
  │
  ├─ Create ExecutionContext [line 493]
  │  └─ ctx = ExecutionContext(
  │       id=execution_id,
  │       correlation_id=correlation_id,
  │       stream_id=stream_id,
  │       input_data=input_data,
  │       session_state=session_state,
  │     )
  │
  ├─ Store context in self._active_executions [line 504]
  │
  ├─ Create completion event [line 505]
  │
  ├─ Start async execution task [line 508]
  │  └─ task = asyncio.create_task(self._run_execution(ctx))
  │
  └─ return execution_id [line 512] (non-blocking)

RESULT: Execution queued, _run_execution() runs in background


===================================================================
STEP 11: EXECUTION RUNNER (BACKGROUND TASK)
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/runtime/execution_stream.py

FUNCTION: ExecutionStream._run_execution() (line 538)
CALLED BY: asyncio.create_task() [line 508]
RUNS IN BACKGROUND: Yes, non-blocking

EXECUTION SEQUENCE:
await _run_execution(ctx) (line 538)
  │
  ├─ Acquire semaphore for concurrency control [line 558]
  │
  ├─ Mark status as "running" [line 559]
  │
  ├─ Create execution-scoped memory [line 572-576]
  │  └─ self._state_manager.create_memory(execution_id, stream_id, isolation)
  │
  ├─ Start runtime adapter [line 579-586]
  │  └─ runtime_adapter.start_run(goal_id, goal_description, input_data)
  │
  ├─ Create RuntimeLogger [line 589-595]
  │
  ├─ Determine storage location [line 601-604]
  │  └─ exec_storage = self._session_store.sessions_dir / execution_id
  │
  ├─ Write initial session state [line 611-612]
  │
  ├─ RESURRECTION LOOP [line 618]
  │  └─ while True:
  │     ├─ Create GraphExecutor [line 625-639]
  │     │  └─ executor = GraphExecutor(
  │     │       runtime=runtime_adapter,
  │     │       llm=self._llm,
  │     │       tools=self._tools,
  │     │       tool_executor=self._tool_executor,
  │     │       event_bus=self._scoped_event_bus,  # <-- SHARED
  │     │       storage_path=exec_storage,
  │     │       checkpoint_config=self._checkpoint_config,
  │     │     )
  │     │
  │     ├─ Execute graph [line 644]
  │     │  └─ result = await executor.execute(
  │     │       graph=modified_graph,
  │     │       goal=self.goal,
  │     │       input_data=_current_input_data,
  │     │       session_state=_current_session_state,
  │     │       checkpoint_config=self._checkpoint_config,
  │     │     )
  │     │
  │     └─ Check for resurrection [line 656-707]
  │        (On non-fatal error, retry from failed node)
  │
  ├─ Record result [line 710]
  │  └─ self._record_execution_result(execution_id, result)
  │
  ├─ Emit completion event [line 730-754]
  │  ├─ execution_completed (if success)
  │  ├─ execution_paused (if paused)
  │  └─ execution_failed (if error)
  │
  └─ Mark completion event [line 774]
     └─ self._completion_events[execution_id].set()

RESULT: Execution complete, event emitted, task ends


===================================================================
STEP 12: GRAPH EXECUTION (THE ACTUAL AGENT LOGIC)
===================================================================

FILE: /Users/timothy/repo/hive/core/framework/graph/executor.py

FUNCTION: GraphExecutor.execute() (line 289)
CALLED BY: ExecutionStream._run_execution() [line 644]
RUNS IN BACKGROUND: Yes, as part of _run_execution task

EXECUTION SEQUENCE:
await executor.execute(graph, goal, input_data, session_state, checkpoint_config) (line 289)
  │
  ├─ Validate graph [line 312-318]
  │
  ├─ Validate tool availability [line 320-332]
  │
  ├─ Initialize SharedMemory for session [line 335]
  │
  ├─ Restore session state if resuming [line 353-369]
  │  └─ Load memory from previous session
  │
  ├─ Restore checkpoints if available [line 412-463]
  │
  ├─ Determine entry point (normal or resume) [line 464-492]
  │
  ├─ Start run in observability system [line 567-579]
  │
  ├─ MAIN EXECUTION LOOP [line 596]
  │  └─ while steps < graph.max_steps:
  │     │
  │     ├─ Check for pause requests [line 599-636]
  │     │
  │     ├─ Get current node spec [line 648-650]
  │     │  └─ node_spec = graph.get_node(current_node_id)
  │     │
  │     ├─ Enforce max_node_visits [line 652-678]
  │     │
  │     ├─ Append node to execution path [line 680]
  │     │
  │     ├─ Clear stale nullable outputs [line 682-695]
  │     │
  │     ├─ Create node context [line 730-745]
  │     │  └─ ctx = self._build_context(node_spec, memory, goal, ...)
  │     │
  │     ├─ Get/create node implementation [line 760]
  │     │  └─ node_impl = self._get_node_implementation(node_spec, ...)
  │     │
  │     ├─ Validate inputs [line 762-769]
  │     │
  │     ├─ Create checkpoints [line 771-790]
  │     │
  │     ├─ EXECUTE NODE [line 800-802]
  │     │  └─ result = await node_impl.execute(ctx)
  │     │     (Executes LLM call, tool calls, or other logic)
  │     │
  │     ├─ Handle success [line 825-876]
  │     │  ├─ Validate output [line 836-850]
  │     │  └─ Write to memory [line 874-876]
  │     │
  │     ├─ Handle failure and retries [line 884-934]
  │     │  ├─ Track retry count [line 886-888]
  │     │  ├─ Check max_retries [line 906-934]
  │     │  └─ Sleep with exponential backoff before retry
  │     │
  │     ├─ Update progress in state.json [line 941]
  │     │  └─ self._write_progress(current_node_id, path, memory, ...)
  │     │
  │     ├─ FOLLOW EDGES [line 942+]
  │     │  └─ next_node = await self._follow_edges(
  │     │       graph, goal, current_node_id,
  │     │       node_spec, result, memory
  │     │     )
  │     │     Evaluates conditional edges, determines next node
  │     │
  │     └─ Transition to next node [line steps += 1]
  │        (Loop continues with next node)
  │
  ├─ Handle timeout/max_steps [line 596: while steps < graph.max_steps]
  │
  └─ Return ExecutionResult [line 1100+]
     └─ ExecutionResult(
          success=success,
          output=final_output,
          error=error_message,
          paused_at=paused_node_id,
          session_state={memory, path, ...},
        )

RESULT: ExecutionResult returned to ExecutionStream._run_execution()


===================================================================
DATA FLOW SUMMARY
===================================================================

Shared Component: EventBus
  ├─ Created in Session (line 95 in session_manager.py)
  ├─ Passed to AgentRuntime.__init__ (line 186 in agent_runtime.py)
  ├─ Stored and used by ExecutionStream (line 219 in execution_stream.py)
  ├─ Wrapped as GraphScopedEventBus (line 254 in execution_stream.py)
  ├─ Passed to GraphExecutor (line 630 in execution_stream.py)
  └─ Used for event publishing during execution

Shared Component: LLM Provider
  ├─ Created in Session._create_session_core() (line 89-94 in session_manager.py)
  ├─ Passed to AgentRuntime.__init__ (line 123 in agent_runtime.py)
  ├─ Stored and used by ExecutionStream (line 220 in execution_stream.py)
  ├─ Passed to GraphExecutor (line 627 in execution_stream.py)
  └─ Used by node implementations for LLM calls

Memory Flow:
  ├─ Each execution has ExecutionContext with input_data
  ├─ SharedMemory created per execution (line 572-576 in execution_stream.py)
  ├─ Session state restored if resuming (line 354-369 in executor.py)
  ├─ Each node reads from memory via input_keys
  ├─ Each node writes to memory via output_keys
  ├─ Memory checkpoints created for resumability
  └─ Final memory returned in ExecutionResult


===================================================================
KEY FILE PATHS AND LINE NUMBERS
===================================================================

1. API Entry: /Users/timothy/repo/hive/core/framework/server/routes_sessions.py:103
2. Session Manager: /Users/timothy/repo/hive/core/framework/server/session_manager.py:128
3. Agent Runner Load: /Users/timothy/repo/hive/core/framework/runner/runner.py:789
4. Agent Runner Setup: /Users/timothy/repo/hive/core/framework/runner/runner.py:1012
5. Runtime Creation: /Users/timothy/repo/hive/core/framework/runtime/agent_runtime.py:1642
6. Runtime Class: /Users/timothy/repo/hive/core/framework/runtime/agent_runtime.py:66
7. Trigger Method: /Users/timothy/repo/hive/core/framework/runtime/agent_runtime.py:790
8. Execution Stream: /Users/timothy/repo/hive/core/framework/runtime/execution_stream.py:134
9. Graph Executor: /Users/timothy/repo/hive/core/framework/graph/executor.py:102
10. Main Loop: /Users/timothy/repo/hive/core/framework/graph/executor.py:596
