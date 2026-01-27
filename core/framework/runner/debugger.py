"""Console debugger for interactive agent execution."""

import asyncio
import json
from typing import Any

from framework.graph.node import NodeSpec, SharedMemory


class ConsoleDebugger:
    """
    Interactive debugger for the agent runner.
    
    Allows stepping through execution, inspecting state, and controlling flow.
    """

    def __init__(self):
        self._disabled = False

    async def on_step(self, step: int, node: NodeSpec, memory: SharedMemory) -> None:
        """
        Callback invoked before each execution step.
        
        Args:
            step: Current step number
            node: Node about to be executed
            memory: Current state of shared memory
        """
        if self._disabled:
            return

        print()
        print("=" * 60)
        print(f"🐞 DEBUGGER PAUSE (Step {step})")
        print("=" * 60)
        print(f"Next Node: {node.name} ({node.id})")
        print(f"Type:      {node.node_type}")
        print(f"Inputs:    {node.input_keys}")
        print()

        while True:
            try:
                # Use a specific prompt to indicate debug mode
                cmd_input = input("(debug) ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAborting...")
                # Exit the process cleanly
                import sys
                sys.exit(1)

            if not cmd_input:
                continue
            
            # Parse command
            parts = cmd_input.split()
            cmd = parts[0].lower()
            args = parts[1:]

            if cmd in ("n", "next", ""):
                # Execute next step
                print("▶ Executing step...")
                return

            elif cmd in ("c", "continue"):
                # Disable debugger and continue to end
                self._disabled = True
                print("▶ Continuing execution (debugger disabled)...")
                return

            elif cmd in ("i", "inspect", "p", "print"):
                # Inspect memory value
                if not args:
                    print("Usage: inspect <key> or inspect *")
                    continue
                
                key = args[0]
                state = memory.read_all_sync()
                
                if key == "*":
                    print(json.dumps(state, indent=2, default=str))
                elif key in state:
                    val = state[key]
                    if isinstance(val, (dict, list)):
                        print(json.dumps(val, indent=2, default=str))
                    else:
                        print(val)
                else:
                    print(f"Key '{key}' not found in memory.")

            elif cmd in ("l", "list"):
                # List all keys in memory
                state = memory.read_all_sync()
                print(f"Memory keys ({len(state)}):")
                for k in sorted(state.keys()):
                    type_name = type(state[k]).__name__
                    val_preview = str(state[k])
                    if len(val_preview) > 50:
                        val_preview = val_preview[:47] + "..."
                    print(f"  {k} ({type_name}): {val_preview}")

            elif cmd in ("q", "quit", "exit"):
                print("Aborting execution...")
                import sys
                sys.exit(0)

            elif cmd in ("h", "help", "?"):
                print("Commands:")
                print("  n, next, <enter>  : Execute next step")
                print("  c, continue       : Continue to end (disable debugger)")
                print("  i, inspect <key>  : Print value of memory key (* for all)")
                print("  l, list           : List all memory keys")
                print("  q, quit           : Abort execution")
                print("  h, help           : Show this help")

            else:
                print(f"Unknown command: {cmd}")
