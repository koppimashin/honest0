import time
import logging
import datetime
from PIL import ImageGrab
from utils.session_manager import SessionManager

from core.capture.memory_box import MemoryBox

logger = logging.getLogger(__name__)

class Screenshot:
    """
    Handles capturing and saving screenshots, and adding them to the MemoryBox.
    """
    def __init__(self, settings: dict, session: SessionManager, memory_box: MemoryBox):
        """
        Initializes the Screenshot module.

        Args:
            settings (dict): Application settings.
            session (SessionManager): Manages session-specific data and paths.
            memory_box (MemoryBox): Stores transient data like audio and screenshots.
        """
        self.output_file_name = "screenshot.webp"
        self.settings = settings
        self.session = session
        self.memory_box = memory_box

    def capture_screenshot(self):
        """
        Captures a screenshot of the entire screen.

        Returns:
            PIL.Image.Image: The captured screenshot as a PIL Image object, or None if an error occurs.
        """
        try:
            screenshot = ImageGrab.grab()
            return screenshot
        except Exception as e:
            logger.error(f"Error capturing screenshot: {e}")
            return None

    def save_screenshot_to_file(self, screenshot, image_quality):
        """
        Saves the given screenshot to a file within the current session's screenshot directory.

        Args:
            screenshot (PIL.Image.Image): The screenshot image to save.
            image_quality (int): The quality level for WEBP compression (0-100).
        """
        try:
            filename = datetime.datetime.now().strftime("%H-%M-%S-%f_screenshot.webp")[:-3] + ".webp"
            output_path = self.session.get_screenshot_path(filename)
            screenshot.save(output_path, "WEBP", quality=image_quality)
            logger.info(f"Screenshot saved to {output_path}")
        except Exception as e:
            logger.error(f"Error saving screenshot: {e}")

if __name__ == '__main__':
    logger.info("Screenshot __main__ block executed. Requires settings object for full functionality.")