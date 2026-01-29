import cmd
import json
import sys

from .session import DebugSession


class DebugCLI(cmd.Cmd):
    """
    Interactive CLI for the Agent Debugger.
    """

    intro = "\n🐞 Agent Debugger. Type help or ? to list commands.\n"
    prompt = "(debug) "

    def __init__(self, session: DebugSession):
        super().__init__()
        self.session = session
        self.last_command = "step"  # Default behavior for empty line? or repeat last

    def do_next(self, arg):
        """Execute the next node and pause (alias for step)."""
        self.session.step()
        return True  # Return True to yield control back to executor loop

    def do_step(self, arg):
        """Execute the next node and pause."""
        self.session.step()
        return True

    def do_continue(self, arg):
        """Continue execution until next breakpoint."""
        self.session.resume()
        return True

    def do_break(self, arg):
        """
        Set a breakpoint at a node ID.
        Usage: break <node_id>
        """
        if not arg:
            self.session.list_breakpoints()
            return
        self.session.add_breakpoint(arg.strip())

    def do_clear(self, arg):
        """
        Clear a breakpoint.
        Usage: clear <node_id>
        """
        if not arg:
            print("Please specify a node ID")
            return
        self.session.remove_breakpoint(arg.strip())

    def do_memory(self, arg):
        """
        Inspect shared memory.
        Usage:
          memory             - Show all keys
          memory <key>       - Show specific value
        """
        mem = self.session.get_memory_snapshot()
        if not arg:
            print("\nMemory Keys:")
            for k in mem.keys():
                val_preview = str(mem[k])
                if len(val_preview) > 50:
                    val_preview = val_preview[:50] + "..."
                print(f"  {k}: {val_preview}")
        else:
            key = arg.strip()
            if key in mem:
                print(f"\n{key}:")
                try:
                    print(json.dumps(mem[key], indent=2, default=str))
                except Exception:
                    print(mem[key])
            else:
                print(f"Key '{key}' not found in memory.")

    def do_context(self, arg):
        """Show inputs for the current node."""
        ctx = self.session.get_context()
        print("\nCurrent Node Inputs:")
        try:
            print(json.dumps(ctx, indent=2, default=str))
        except Exception:
            print(ctx)

    def do_info(self, arg):
        """Show info about current node."""
        info = self.session.current_step_info
        if info:
            print(f"\nNode ID:   {info['node_id']}")
            print(f"Node Name: {info['node_name']}")
        else:
            print("No active step info.")

    def do_quit(self, arg):
        """Exit the debugger and abort execution."""
        print("Aborting execution...")
        sys.exit(0)

    def emptyline(self):
        """Repeat last command (usually step)."""
        # If the user just hits enter, usually 'step' or 'next' is intuitive
        # But 'cmd' defaults to repeating the last command typed.
        if self.lastcmd:
            return super().emptyline()
        else:
            return self.do_next("")

    # Aliases
    do_n = do_next
    do_s = do_step
    do_c = do_continue
    do_b = do_break
    do_m = do_memory
    do_q = do_quit
    do_l = do_info  # list/look?
