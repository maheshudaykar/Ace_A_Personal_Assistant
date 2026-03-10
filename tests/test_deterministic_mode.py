"""Unit tests for ace_kernel.deterministic_mode module."""

import random

from ace_kernel.deterministic_mode import DeterministicMode


class TestDeterministicMode:
    """Test DeterministicMode class."""

    def test_deterministic_mode_creation(self) -> None:
        """Test DeterministicMode instantiation."""
        dm = DeterministicMode(enabled=False)
        assert dm.enabled is False
        assert dm.seed == 42  # Default seed

    def test_deterministic_mode_with_seed(self) -> None:
        """Test DeterministicMode with custom seed."""
        dm = DeterministicMode(enabled=True, seed=123)
        assert dm.seed == 123
        assert dm.enabled is True

    def test_is_deterministic(self) -> None:
        """Test is_deterministic check."""
        dm = DeterministicMode(enabled=True)
        assert dm.is_deterministic() is True

        dm_off = DeterministicMode(enabled=False)
        assert dm_off.is_deterministic() is False

    def test_activate_deactivate(self) -> None:
        """Test activate and deactivate methods."""
        dm = DeterministicMode(enabled=False)
        assert dm.is_deterministic() is False

        dm.activate()
        assert dm.is_deterministic() is True

        dm.deactivate()
        assert dm.is_deterministic() is False

    def test_toggle(self) -> None:
        """Test toggle method."""
        dm = DeterministicMode(enabled=False)
        assert dm.is_deterministic() is False

        dm.toggle()
        assert dm.is_deterministic() is True

        dm.toggle()
        assert dm.is_deterministic() is False

    def test_set_seed(self) -> None:
        """Test seed setting functionality."""
        dm = DeterministicMode(enabled=True, seed=42)
        assert dm.seed == 42

        dm.set_seed(999)
        assert dm.seed == 999

    def test_reproducible_random(self) -> None:
        """Test that same seed produces reproducible random sequences."""
        random.seed(42)
        vals1 = [random.random() for _ in range(5)]

        random.seed(42)
        vals2 = [random.random() for _ in range(5)]

        assert vals1 == vals2

    def test_different_seeds_produce_different_randoms(self) -> None:
        """Test that different seeds produce different random sequences."""
        random.seed(42)
        vals1 = [random.random() for _ in range(5)]

        random.seed(999)
        vals2 = [random.random() for _ in range(5)]

        assert vals1 != vals2

    def test_get_llm_temperature(self) -> None:
        """Test get_llm_temperature static method returns base temp.

        The static method returns the caller's base temperature; callers
        should check ``.enabled`` to decide whether to override to 0.0.
        """
        result = DeterministicMode.get_llm_temperature(0.7)
        assert result == 0.7

        result2 = DeterministicMode.get_llm_temperature(0.1)
        assert result2 == 0.1

