"""Phase 3A runtime configuration defaults."""

# Deterministic mode: when True, background thread does NOT auto-run.
# Maintenance only executes via explicit run_single_cycle() calls.
# Golden trace captures every cycle boundary for deterministic replay.
DETERMINISTIC_MODE = True

# Maintenance cycle interval (milliseconds).
# In non-deterministic mode, thread wakes every N ms to check for work.
# In deterministic mode, this parameter is unused (explicit trigger only).
CYCLE_INTERVAL_MS = 5000

# Max CPU time per maintenance cycle (milliseconds).
# If cycle duration exceeds this, abort and yield.
MAX_CYCLE_CPU_MS = 100

# Max operations per maintenance cycle.
# Operations include: consolidation merges, compaction entries, quota reconciliations.
# If operation count exceeds this, abort and yield.
MAX_OPERATIONS_PER_CYCLE = 500

# Memory budget per cycle (reserved for future use).
MEMORY_BUDGET_PER_CYCLE_MB = 50

# Max concurrent agents (for future AgentScheduler in Gate 3).
MAX_CONCURRENT_AGENTS = 4

# Circuit breaker retry window (minutes): grace period before re-attempting failed agents.
CIRCUIT_BREAKER_RETRY_WINDOW_MINUTES = 5

# Max consecutive executions per agent before forcing fair scheduling.
MAX_CONSECUTIVE_EXECUTIONS_PER_AGENT = 3
