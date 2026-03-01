"""Budget enforcement for bounded maintenance cycles."""
from __future__ import annotations
import time
from dataclasses import dataclass

@dataclass
class BudgetToken:
    operations_budgeted: int
    cpu_time_budgeted_ms: int
    start_time_ms: float
    operations_consumed: int = 0

    def has_budget(self) -> bool:
        cpu_elapsed = (time.perf_counter() * 1000) - self.start_time_ms
        return self.operations_consumed < self.operations_budgeted and cpu_elapsed < self.cpu_time_budgeted_ms

class BudgetExhausted(Exception):
    def __init__(self, reason: str, budget: BudgetToken):
        self.reason = reason
        self.budget = budget

def create_budget_token(operations_budgeted: int, cpu_time_budgeted_ms: int) -> BudgetToken:
    return BudgetToken(operations_budgeted=operations_budgeted, cpu_time_budgeted_ms=cpu_time_budgeted_ms, start_time_ms=time.perf_counter() * 1000)
