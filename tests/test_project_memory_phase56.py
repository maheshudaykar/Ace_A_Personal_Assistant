from ace.ace_memory.project_memory import ProjectMemory


def test_project_memory_learns_repository(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (repo / "core.py").write_text("print('x')\n", encoding="utf-8")

    memory = ProjectMemory(storage_dir=str(tmp_path / "pm"))
    snapshot = memory.learn_repository(str(repo))

    assert snapshot.repo_id
    assert snapshot.primary_language == "Python"
    assert memory.get_build_command(str(repo)) == "python -m build"


def test_project_memory_failure_pattern_accumulates(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    memory = ProjectMemory(storage_dir=str(tmp_path / "pm"))
    first = memory.record_failure_pattern(str(repo), "db timeout", "pool too small", "increase pool")
    second = memory.record_failure_pattern(str(repo), "db timeout", "pool too small", "increase pool")

    assert first.pattern_id == second.pattern_id
    assert second.frequency == 2
