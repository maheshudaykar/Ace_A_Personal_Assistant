"""Phase 2C memory hardening configuration defaults."""

MAX_TOTAL_ENTRIES = 10_000
MAX_ACTIVE_ENTRIES = 5_000
MAX_ENTRIES_PER_TASK = 1_000
MAX_COMPARISONS_PER_PASS = 50_000

# Observability-only growth monitor (entries per rolling minute).
GROWTH_SPIKE_ENTRIES_PER_MINUTE = 2_000
