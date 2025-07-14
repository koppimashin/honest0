"""
This module defines the abstract base class for Language Model Manager (LLM) APIs.
It establishes a common interface for sending multimodal data (audio and images)
to different LLM providers.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Any

class BaseLLMAPI(ABC):
    """
    Abstract Base Class for LLM API integrations.
    All concrete LLM API implementations (e.g., GeminiAPI) must inherit from this class
    and implement its abstract methods.
    """
    @abstractmethod
    def send_multimodal(self, audio: Optional[bytes] = None, images: Optional[List[Any]] = None) -> str:
        """
        Abstract method to send multimodal data (audio and/or images) to an LLM.

        Args:
            audio (Optional[bytes]): Optional audio data in bytes.
            images (Optional[List[Any]]): Optional list of image data (format depends on concrete implementation).

        Returns:
            str: The response from the LLM, typically a text string.
        """
        pass