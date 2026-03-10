"""ProjectMemory: long-term repository knowledge and engineering history."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "RepositorySnapshot",
    "RefactorRecord",
    "FailurePattern",
    "ModuleCriticality",
    "ProjectMemory",
]


def _str_list_default() -> List[str]:
    return []


def _str_any_dict_default() -> Dict[str, Any]:
    return {}


@dataclass
class RepositorySnapshot:
    repo_id: str
    repo_path: str
    architecture_pattern: str = "Unknown"
    build_command: Optional[str] = None
    test_command: Optional[str] = None
    lint_command: Optional[str] = None
    critical_modules: List[str] = field(default_factory=_str_list_default)
    dependency_health: Dict[str, Any] = field(default_factory=_str_any_dict_default)
    last_analyzed: float = field(default_factory=time.time)
    total_loc: int = 0
    test_coverage_pct: float = 0.0
    primary_language: str = "Python"


@dataclass
class RefactorRecord:
    refactor_id: str
    repo_id: str
    description: str
    timestamp: float
    before_architecture: Dict[str, Any]
    after_architecture: Dict[str, Any]
    impact_metrics: Dict[str, Any] = field(default_factory=_str_any_dict_default)
    outcome: str = "unknown"
    reason: str = ""
    lessons_learned: str = ""


@dataclass
class FailurePattern:
    pattern_id: str
    repo_id: str
    failure_symptom: str
    root_cause: str
    recovery_action: str
    frequency: int = 1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    severity: str = "medium"


@dataclass
class ModuleCriticality:
    module_path: str
    repo_id: str
    criticality_score: float = 5.0
    incoming_dependencies: int = 0
    outgoing_dependencies: int = 0
    test_coverage_pct: float = 0.0
    change_frequency: float = 0.0
    last_modified: float = field(default_factory=time.time)


class ProjectMemory:
    """Persistent project intelligence for architectural decision support."""

    SCHEMA_VERSION = 1

    def __init__(self, storage_dir: str = "data/project_memory") -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._db_file = self.storage_dir / "project_memory.json"

        self.repositories: Dict[str, RepositorySnapshot] = {}
        self.architecture_snapshots: Dict[str, Dict[str, Any]] = {}
        self.refactor_history: Dict[str, RefactorRecord] = {}
        self.dependency_health: Dict[str, Dict[str, Any]] = {}
        self.failure_patterns: Dict[str, FailurePattern] = {}
        self.module_criticality: Dict[str, ModuleCriticality] = {}

        self._load_from_disk()

    def learn_repository(self, repo_path: str) -> RepositorySnapshot:
        repo_id = self._repo_id(repo_path)
        build_cmd, test_cmd, lint_cmd = self._detect_commands(repo_path)

        snapshot = RepositorySnapshot(
            repo_id=repo_id,
            repo_path=repo_path,
            architecture_pattern=self._detect_architecture_pattern(repo_path),
            build_command=build_cmd,
            test_command=test_cmd,
            lint_command=lint_cmd,
            critical_modules=self._detect_critical_modules(repo_path),
            dependency_health={"last_scan": None, "vulnerable_dependencies": []},
            total_loc=self._count_lines(repo_path),
            primary_language=self._detect_primary_language(repo_path),
        )
        self.repositories[repo_id] = snapshot
        self.architecture_snapshots[repo_id] = {
            "pattern": snapshot.architecture_pattern,
            "critical_modules": list(snapshot.critical_modules),
            "last_analyzed": snapshot.last_analyzed,
        }
        self._persist()
        return snapshot

    def record_refactoring(
        self,
        repo_path: str,
        description: str,
        before: Dict[str, Any],
        after: Dict[str, Any],
        outcome: str,
        reason: str = "",
    ) -> RefactorRecord:
        repo_id = self._repo_id(repo_path)
        ref_id = hashlib.sha256(f"{repo_id}:{description}:{time.time():.6f}".encode("utf-8")).hexdigest()[:16]
        record = RefactorRecord(
            refactor_id=ref_id,
            repo_id=repo_id,
            description=description,
            timestamp=time.time(),
            before_architecture=before,
            after_architecture=after,
            outcome=outcome,
            reason=reason,
        )
        self.refactor_history[ref_id] = record
        self._persist()
        return record

    def record_failure_pattern(
        self,
        repo_path: str,
        symptom: str,
        root_cause: str,
        recovery: str,
        severity: str = "medium",
    ) -> FailurePattern:
        repo_id = self._repo_id(repo_path)
        key = hashlib.sha256(f"{repo_id}:{symptom}".encode("utf-8")).hexdigest()[:16]
        existing = self.failure_patterns.get(key)
        if existing:
            existing.frequency += 1
            existing.last_seen = time.time()
            existing.root_cause = root_cause
            existing.recovery_action = recovery
            existing.severity = severity
            pattern = existing
        else:
            pattern = FailurePattern(
                pattern_id=key,
                repo_id=repo_id,
                failure_symptom=symptom,
                root_cause=root_cause,
                recovery_action=recovery,
                severity=severity,
            )
            self.failure_patterns[key] = pattern
        self._persist()
        return pattern

    def get_build_command(self, repo_path: str) -> Optional[str]:
        snapshot = self.repositories.get(self._repo_id(repo_path))
        return snapshot.build_command if snapshot else None

    def get_critical_modules(self, repo_path: str) -> List[str]:
        snapshot = self.repositories.get(self._repo_id(repo_path))
        return list(snapshot.critical_modules) if snapshot else []

    def query_failure_patterns(self, repo_path: str, symptom_query: str) -> List[FailurePattern]:
        repo_id = self._repo_id(repo_path)
        needle = symptom_query.lower()
        matches = [
            pattern
            for pattern in self.failure_patterns.values()
            if pattern.repo_id == repo_id and needle in pattern.failure_symptom.lower()
        ]
        return sorted(matches, key=lambda p: (-p.frequency, p.pattern_id))

    def update_dependency_health(self, repo_path: str, health: Dict[str, Any]) -> None:
        repo_id = self._repo_id(repo_path)
        self.dependency_health[repo_id] = dict(health)
        snapshot = self.repositories.get(repo_id)
        if snapshot:
            snapshot.dependency_health = dict(health)
            snapshot.last_analyzed = time.time()
        self._persist()

    def upsert_module_criticality(self, module: ModuleCriticality) -> None:
        key = f"{module.repo_id}:{module.module_path}"
        self.module_criticality[key] = module
        self._persist()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "repositories": {k: asdict(v) for k, v in self.repositories.items()},
            "architecture_snapshots": self.architecture_snapshots,
            "refactor_history": {k: asdict(v) for k, v in self.refactor_history.items()},
            "dependency_health": self.dependency_health,
            "failure_patterns": {k: asdict(v) for k, v in self.failure_patterns.items()},
            "module_criticality": {k: asdict(v) for k, v in self.module_criticality.items()},
        }

    def _load_from_disk(self) -> None:
        if not self._db_file.exists():
            return
        try:
            raw = self._db_file.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load project memory from %s: %s", self._db_file, exc)
            return

        if payload.get("schema_version") != self.SCHEMA_VERSION:
            logger.warning(
                "Schema version mismatch (got %s, expected %d); skipping load",
                payload.get("schema_version"),
                self.SCHEMA_VERSION,
            )
            return

        self.repositories = {
            k: RepositorySnapshot(**v) for k, v in payload.get("repositories", {}).items()
        }
        self.architecture_snapshots = payload.get("architecture_snapshots", {})
        self.refactor_history = {
            k: RefactorRecord(**v) for k, v in payload.get("refactor_history", {}).items()
        }
        self.dependency_health = payload.get("dependency_health", {})
        self.failure_patterns = {
            k: FailurePattern(**v) for k, v in payload.get("failure_patterns", {}).items()
        }
        self.module_criticality = {
            k: ModuleCriticality(**v) for k, v in payload.get("module_criticality", {}).items()
        }

    def _persist(self) -> None:
        """Atomic write: write to temp file then rename to avoid corruption."""
        serialized = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=True, indent=2)
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.storage_dir), suffix=".tmp", prefix="pm_"
            )
            try:
                os.write(fd, (serialized + "\n").encode("utf-8"))
            finally:
                os.close(fd)
            # Atomic rename on the same filesystem
            os.replace(tmp_path, str(self._db_file))
        except OSError as exc:
            logger.error("Failed to persist project memory: %s", exc)

    @staticmethod
    def _repo_id(repo_path: str) -> str:
        normalized = str(Path(repo_path).resolve())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def _detect_architecture_pattern(self, repo_path: str) -> str:
        root = Path(repo_path)
        if (root / "src" / "domain").exists() and (root / "src" / "infrastructure").exists():
            return "Clean Architecture"
        if (root / "controllers").exists() and (root / "models").exists() and (root / "views").exists():
            return "MVC"
        if (root / "services").exists() and (root / "api").exists() and (root / "workers").exists():
            return "Microservices"
        return "Layered"

    def _detect_commands(self, repo_path: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        root = Path(repo_path)
        if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
            return "python -m build", "pytest", "ruff check ."
        if (root / "package.json").exists():
            return "npm run build", "npm test", "npm run lint"
        return None, None, None

    def _detect_critical_modules(self, repo_path: str) -> List[str]:
        root = Path(repo_path)
        candidates: List[Path] = []
        for pattern in ("**/*kernel*.py", "**/*consensus*.py", "**/*memory*.py"):
            candidates.extend(root.glob(pattern))

        relative = [str(path.relative_to(root)).replace("\\", "/") for path in candidates if path.is_file()]
        return sorted(set(relative))[:20]

    def _count_lines(self, repo_path: str) -> int:
        total = 0
        root = Path(repo_path)
        for path in root.rglob("*.py"):
            if ".git" in path.parts:
                continue
            try:
                total += len(path.read_text(encoding="utf-8").splitlines())
            except (UnicodeDecodeError, OSError):
                continue
        return total

    def _detect_primary_language(self, repo_path: str) -> str:
        counts: Dict[str, int] = {"Python": 0, "TypeScript": 0, "JavaScript": 0, "Go": 0}
        root = Path(repo_path)
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix == ".py":
                counts["Python"] += 1
            elif suffix == ".ts":
                counts["TypeScript"] += 1
            elif suffix == ".js":
                counts["JavaScript"] += 1
            elif suffix == ".go":
                counts["Go"] += 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
