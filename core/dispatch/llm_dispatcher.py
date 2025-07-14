from typing import Any, List, Optional
from services.base_api import BaseLLMAPI
import logging
from PIL import Image
from interface.overlay import OverlayListener, OverlayEvent
import uuid
import time
import logging
from typing import Any, List, Optional
from services.base_api import BaseLLMAPI
from PIL import Image
from interface.overlay import OverlayListener, OverlayEvent

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LLMDispatcher:
    """
    Dispatches multimodal input (audio and images) to the LLM provider
    and handles streaming responses back to the GUI.
    """
    def __init__(self, provider: BaseLLMAPI, gui_listener: OverlayListener = None):
        """
        Initializes the LLMDispatcher.

        Args:
            provider (BaseLLMAPI): An instance of an LLM API provider (e.g., GeminiAPI).
            gui_listener (OverlayListener, optional): Listener for GUI events. Defaults to None.
        """
        if not isinstance(provider, BaseLLMAPI):
            raise TypeError("Provider must be an instance of BaseLLMAPI")
        self.provider = provider
        self.gui_listener = gui_listener
        logging.info(f"LLMDispatcher initialized with provider: {type(provider).__name__}")

    def send_bundle(self, audio: Any = None, images: Optional[List[Image.Image]] = None) -> str:
        """
        Sends a bundle of audio and/or images to the LLM and streams the response.

        Args:
            audio (Any, optional): Audio data. Defaults to None.
            images (Optional[List[Image.Image]], optional): List of PIL Image objects. Defaults to None.

        Returns:
            str: The full concatenated response from the LLM.
        """
        request_id = str(uuid.uuid4())[:8]
        logging.info(f"Dispatching to LLM (ID: {request_id}) — audio: {'✅' if audio else '❌'}, images: {len(images) if images else 0}")
        if self.gui_listener:
            self.gui_listener.update(OverlayEvent.STREAM_START, {"mode": "LLM", "request_id": request_id})
        
        full_response = ""
        start_time = time.perf_counter()
        try:
            response_generator = self.provider.send_multimodal(audio=audio, images=images or [])
            for i, chunk in enumerate(response_generator):
                elapsed = time.perf_counter() - start_time
                logging.debug(f"[{elapsed:.2f}s] Dispatcher Chunk {i}: {chunk[:40]!r}")
                full_response += chunk
                if self.gui_listener:
                    self.gui_listener.update(OverlayEvent.STREAM_CHUNK, {"text": chunk, "request_id": request_id})
        except Exception as e:
            logging.error(f"Error during LLM streaming (ID: {request_id}): {e}", exc_info=True)
            if self.gui_listener:
                self.gui_listener.update(OverlayEvent.STREAM_CHUNK, {"text": f"\n\nError: {e}\n", "request_id": request_id})
        finally:
            if self.gui_listener:
                self.gui_listener.update(OverlayEvent.STREAM_END, {"request_id": request_id})
            
            return full_response