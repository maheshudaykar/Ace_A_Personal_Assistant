# Contributing to ACE

Thanks for contributing to ACE.

This guide explains how to contribute safely to a deterministic, governance-first codebase.

## Project Philosophy

ACE prioritizes:

- deterministic behavior
- bounded resource growth
- auditable system actions
- clear layer boundaries

When in doubt, choose the simpler, more predictable implementation.

## Repository Structure

```text
ace/
  ace_kernel/        # core governance/state/audit primitives
  ace_core/          # event infrastructure
  ace_tools/         # tool interfaces/executors
  ace_memory/        # memory, consolidation, governance controls
  ace_diagnostics/   # evaluation, profiling, benchmarking helpers
  ace_cognitive/     # cognitive modules
  runtime/           # runtime orchestration helpers

tests/               # full regression and phase tests
run_ace.py           # entrypoint
README.md            # project overview
CHANGELOG.md         # release and phase history
```

## Ground Rules

- Do not modify kernel behavior casually; treat `ace_kernel/` as stability-critical.
- Preserve determinism (stable sorting, reproducible behavior, no hidden randomness).
- Avoid introducing async/threads for memory governance paths unless explicitly required.
- Keep changes focused; avoid drive-by refactors unrelated to the issue.
- Do not weaken quotas/guards without explicit design approval.

## Development Setup

```bash
python -m venv .venv
```

**Windows (PowerShell)**
```powershell
.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
```

**Linux/macOS**
```bash
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

## Branch and Commit Workflow

1. Create a focused branch from `main`
2. Make minimal, reviewable changes
3. Add or update tests for behavior changes
4. Run validation locally
5. Open PR with clear scope and rationale

Commit style recommendation:

```text
feat: short description
fix: short description
refactor: short description
test: short description
docs: short description
```

## Coding Standards

- Use explicit type hints for new/changed code.
- Prefer small, composable functions with clear responsibilities.
- Keep public APIs backward compatible unless change is approved.
- Add concise docstrings for non-trivial behavior.
- Avoid one-letter variable names in production code.

## Testing Requirements

Before opening a PR, run:

```bash
python -m pytest tests/ -q
```

For memory/governance changes, also run target suites/benchmarks relevant to your change (for example, phase governance tests and stress benchmarks).

### Test Expectations

- New behavior must have tests.
- Bug fixes must include regression coverage when feasible.
- Deterministic behavior must remain stable across repeated runs.

## Performance and Safety Expectations

For changes affecting memory or runtime governance:

- preserve enforcement order and guard semantics
- avoid repeated full-store scans in hot paths
- ensure bounded growth behavior remains intact
- verify no index corruption or nondeterministic side effects

If performance regresses materially, report it in the PR with benchmark context.

## Documentation Expectations

Update docs when behavior changes:

- `README.md` for user-facing architecture/usage changes
- `CHANGELOG.md` for release-impacting changes
- inline module docstrings where logic is non-obvious

Avoid duplicating long phase history in README; keep detailed progression in CHANGELOG.

## Pull Request Checklist

- [ ] Scope is clear and limited
- [ ] Tests added/updated
- [ ] Full suite passes locally
- [ ] No unrelated files changed
- [ ] Determinism and governance constraints preserved
- [ ] Documentation updated where needed

## Reporting Issues

Please include:

- what you expected
- what happened
- steps to reproduce
- environment (OS, Python version)
- relevant logs or tracebacks

A minimal repro script or failing test is highly appreciated.

## Questions

- Start with `README.md` for architecture and runtime flow.
- Check `CHANGELOG.md` for phase-specific release details.
- Review existing tests for expected behavior patterns.

Thanks for helping improve ACE.
