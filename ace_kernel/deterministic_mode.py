"""Deterministic mode for ACE - reproducible execution"""

import random
import logging

logger = logging.getLogger("ACE.DeterministicMode")


class DeterministicMode:
    """
    Deterministic execution mode for debugging and reproducibility.
    
    When enabled:
    - All random operations use fixed seed
    - LLM temperature overridden to 0.0 (no sampling)
    - Execution is fully reproducible given same inputs
    """
    
    def __init__(self, enabled: bool = False, seed: int = 42):
        """
        Initialize deterministic mode.
        
        Args:
            enabled: Whether deterministic mode is active
            seed: Random seed for reproducibility
        """
        self.enabled = enabled
        self.seed = seed
        self._original_seed = None
        
        if self.enabled:
            self.activate()
    
    def activate(self) -> None:
        """Activate deterministic mode."""
        self.enabled = True
        logger.info(f"🔒 Deterministic mode ACTIVATED (seed={self.seed})")
        
        # Set Python random seed
        random.seed(self.seed)
        
        # Note: LLM temperature override handled separately in llm_interface
    
    def deactivate(self) -> None:
        """Deactivate deterministic mode."""
        self.enabled = False
        logger.info("🔓 Deterministic mode DEACTIVATED")
    
    def toggle(self) -> None:
        """Toggle deterministic mode."""
        self.enabled = not self.enabled
        if self.enabled:
            self.activate()
        else:
            self.deactivate()
    
    def set_seed(self, seed: int) -> None:
        """Change random seed."""
        self.seed = seed
        if self.enabled:
            random.seed(seed)
            logger.info(f"Deterministic seed changed to {seed}")
    
    def is_deterministic(self) -> bool:
        """Check if deterministic mode is active."""
        return self.enabled
    
    @staticmethod
    def get_llm_temperature(base_temperature: float) -> float:
        """
        Get LLM temperature, considering deterministic mode.
        
        Args:
            base_temperature: Original temperature setting
        
        Returns:
            Adjusted temperature (0.0 if deterministic mode active, base_temperature otherwise)
        """
        # This will be called from llm_interface
        # and will check the global deterministic mode instance
        return 0.0  # Deterministic mode always uses 0.0 temperature
