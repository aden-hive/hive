import threading
import time
from dataclasses import dataclass, field
from typing import List


@dataclass
class Decision:
    id: str


@dataclass
class Run:
    decisions: List[Decision] = field(default_factory=list)


class MockRuntime:
    def __init__(self):
        self._current_run = Run()

    def decide(self, intent: str) -> str:
        # Simulate the vulnerable logic
        decision_id = f"dec_{len(self._current_run.decisions)}"

        # Simulate some processing delay to increase collision window
        time.sleep(0.01)

        self._current_run.decisions.append(Decision(id=decision_id))
        return decision_id


runtime = MockRuntime()
ids = []


def make_decisions():
    for i in range(10):
        ids.append(runtime.decide(f"intent_{i}"))


threads = [threading.Thread(target=make_decisions) for _ in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()

duplicates = [x for x in ids if ids.count(x) > 1]
print(f"Total decisions: {len(ids)}")
print(f"Unique IDs: {len(set(ids))}")
print(f"Duplicates found: {len(set(duplicates))}")
if len(set(ids)) < len(ids):
    print("COLLISION REPRODUCED!")
else:
    print("No collision found (lucky or window too small).")
