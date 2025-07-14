import os
import datetime

class SessionManager:
    def __init__(self, base_dir="sessions"):
        self.base_dir = base_dir
        self.session_path = None
        self.audio_dir = None
        self.screenshot_dir = None
        self._initialize_session()

    def _initialize_session(self):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_path = os.path.join(self.base_dir, timestamp)
        self.audio_dir = os.path.join(self.session_path, "audio")
        self.screenshot_dir = os.path.join(self.session_path, "screenshot")

        os.makedirs(self.audio_dir, exist_ok=True)
        os.makedirs(self.screenshot_dir, exist_ok=True)

    def get_audio_path(self, filename):
        return os.path.join(self.audio_dir, filename)

    def get_screenshot_path(self, filename):
        return os.path.join(self.screenshot_dir, filename)

    def get_session_root(self):
        return self.session_path