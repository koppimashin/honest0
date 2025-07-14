import logging
import threading
from typing import Optional, List
from PIL import Image

logger = logging.getLogger(__name__)

class MemoryBox:
    """
    A thread-safe class for temporarily storing audio and image data.
    It acts as a buffer for multimodal inputs before they are dispatched to the LLM.
    """
    def __init__(self, settings: dict):
        """
        Initializes the MemoryBox.

        Args:
            settings (dict): Application settings, used to configure max_images_stored.
        """
        self._audio: Optional[bytes] = None
        self._images: List[Image.Image] = []
        self._lock = threading.Lock()
        self._max_images = settings.get("max_images_stored", 3)
        logger.info(f"MemoryBox initialized with max_images_stored: {self._max_images}.")

    def set_audio(self, audio_data: bytes):
        """
        Sets the audio data in the MemoryBox.

        Args:
            audio_data (bytes): The audio data to store.
        """
        with self._lock:
            self._audio = audio_data
            logger.debug("Audio set in MemoryBox.")

    def add_image(self, image_data: Image.Image):
        """
        Adds an image to the MemoryBox. If the maximum number of images is reached,
        the oldest image is removed.

        Args:
            image_data (Image.Image): The PIL Image object to store.
        """
        with self._lock:
            if not isinstance(image_data, Image.Image):
                logger.warning(f"Attempted to add non-Image object to MemoryBox: {type(image_data)}")
                return
            if len(self._images) >= self._max_images:
                logger.warning(f"MemoryBox full ({self._max_images} images) — dropping oldest image.")
                self._images.pop(0)
                logger.info(f"Dropped oldest image. MemoryBox now contains {len(self._images)} image(s).")
            self._images.append(image_data)
            logger.debug("Image added to MemoryBox.")

    def get_bundle(self) -> tuple[Optional[bytes], List[Image.Image]]:
        """
        Retrieves the current audio and image bundle without clearing them.

        Returns:
            tuple[Optional[bytes], List[Image.Image]]: A tuple containing the audio data
            and a list of image data.
        """
        with self._lock:
            logger.debug(f"Retrieving bundle: audio_present={self._audio is not None}, images_count={len(self._images)}")
            return self._audio, list(self._images)

    def pop_bundle(self) -> tuple[Optional[bytes], List[Image.Image]]:
        """
        Retrieves the current audio and image bundle and then clears the MemoryBox.

        Returns:
            tuple[Optional[bytes], List[Image.Image]]: A tuple containing the audio data
            and a list of image data.
        """
        with self._lock:
            audio, images = self._audio, list(self._images)
            self._audio, self._images = None, []
            logger.info("MemoryBox popped and cleared.")
            return audio, images

    def clear(self):
        """
        Clears all audio and image data from the MemoryBox.
        """
        with self._lock:
            self._audio = None
            self._images.clear()
            logger.info("MemoryBox cleared.")
            logger.debug(f"MemoryBox state after clear: audio_present={self._audio is not None}, images_count={len(self._images)}")

    def is_empty(self) -> bool:
        """
        Checks if the MemoryBox is empty (contains no audio or images).

        Returns:
            bool: True if empty, False otherwise.
        """
        with self._lock:
            return self._audio is None and not self._images

    def has_audio(self) -> bool:
        """
        Checks if the MemoryBox contains audio data.

        Returns:
            bool: True if audio is present, False otherwise.
        """
        with self._lock:
            return self._audio is not None

    def has_image(self) -> bool:
        """
        Checks if the MemoryBox contains any image data.

        Returns:
            bool: True if at least one image is present, False otherwise.
        """
        with self._lock:
            return bool(self._images)

    def has_data(self) -> bool:
        """
        Checks if the MemoryBox contains any data (audio or images).

        Returns:
            bool: True if any data is present, False otherwise.
        """
        with self._lock:
            return self._audio is not None or bool(self._images)