"""LLM Interface for ACE - Phase 0 minimal version"""

from typing import Optional
import logging

logger = logging.getLogger("ACE.LLMInterface")


class LLMInterface:
    """
    Minimal LLM interface for Phase 0.
    
    In Phase 0, this uses a simple mock LLM.
    Phase 1 will integrate llama.cpp for real inference.
    """
    
    def __init__(self, model_name: str = "mock", deterministic: bool = False):
        """
        Initialize LLM interface.
        
        Args:
            model_name: Model to load ("mock" for Phase 0)
            deterministic: If True, use temperature=0.0
        """
        self.model_name = model_name
        self.deterministic = deterministic
        self.temperature = 0.0 if deterministic else 0.7
        
        logger.info(f"LLMInterface initialized - Model: {model_name}, Deterministic: {deterministic}")
    
    def generate(self, prompt: str, max_tokens: int = 100) -> str:
        """
        Generate text from prompt.
        
        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
        
        Returns:
            Generated text
        """
        logger.info(f"LLM.generate() called - Deterministic: {self.deterministic}")
        logger.debug(f"Prompt: {prompt[:100]}...")
        
        if self.model_name == "mock":
            return self._mock_generate(prompt, max_tokens)
        else:
            raise ValueError(f"Model not supported in Phase 0: {self.model_name}")
    
    def _mock_generate(self, prompt: str, max_tokens: int) -> str:
        """Mock LLM for Phase 0 testing."""
        if "file" in prompt.lower() and "read" in prompt.lower():
            return "I should read the file using the read_file tool."
        elif "list" in prompt.lower() and "files" in prompt.lower():
            return "I should list files using the list_files tool."
        elif "write" in prompt.lower():
            return "I should write content to a file using the write_file tool."
        else:
            return "I understood your request. Let me think about how to help."
    
    def set_temperature(self, temperature: float):
        """Set LLM sampling temperature (0.0 = deterministic)."""
        if self.deterministic:
            logger.warning("Cannot change temperature in deterministic mode")
            return
        self.temperature = max(0.0, min(1.0, temperature))
        logger.info(f"LLM temperature set to {self.temperature}")
    
    def set_deterministic(self, enabled: bool):
        """Enable/disable deterministic mode."""
        self.deterministic = enabled
        self.temperature = 0.0 if enabled else 0.7
        logger.info(f"Deterministic mode: {enabled}")


# Global LLM instance
_global_llm: Optional[LLMInterface] = None


def get_llm(model_name: str = "mock", deterministic: bool = False) -> LLMInterface:
    """
    Get or create global LLM interface.
    
    Args:
        model_name: Model to use
        deterministic: If True, use deterministic mode
    
    Returns:
        LLM interface instance
    """
    global _global_llm
    if _global_llm is None:
        _global_llm = LLMInterface(model_name=model_name, deterministic=deterministic)
    return _global_llm


def reset_llm():
    """Reset global LLM instance (for testing)."""
    global _global_llm
    _global_llm = None
