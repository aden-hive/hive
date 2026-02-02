from dataclasses import dataclass

@dataclass
class ExecutionContext:
    simulate: bool = False
