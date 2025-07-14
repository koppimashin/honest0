"""
This is the main application file for the Stealth Assistant.
It handles application setup, GUI creation, core component initialization,
and the main application loop.
"""
import time
import os
from pathlib import Path
import sys
import ctypes
import logging
import json
import argparse
from concurrent.futures import ThreadPoolExecutor

from pathlib import Path
from config.settings import Settings

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.session_manager import SessionManager
from core.capture.audio_recorder import AudioRecorder
from core.capture.screenshot import Screenshot
from core.capture.memory_box import MemoryBox
from services.gemini_api import GeminiAPI
from core.dispatch.llm_dispatcher import LLMDispatcher
from interface.command_mode import CommandMode
from interface.overlay import MinimalOverlayGUI, OverlayListener, OverlayEvent
import tkinter as tk
import threading
from PIL import Image
from utils.semantic_export import convert_chat_history

from typing import Tuple, Any, Callable, Optional

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def elevate():
    """
    Attempts to elevate the current process to administrator privileges on Windows.
    If not running as administrator, it will re-launch the script with elevated privileges.
    """
    if not ctypes.windll.shell32.IsUserAnAdmin():
        logger.warning("Not running as administrator. Attempting to elevate privileges.")
        try:
            script = os.path.abspath(sys.argv[0])
            params = ' '.join([f'"{arg}"' for arg in sys.argv[1:]])
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, script, params, 1)
            sys.exit(0)
        except Exception as e:
            logger.error(f"Failed to elevate privileges: {e}")
            sys.exit(1)
    else:
        logger.info("Running as administrator.")

def create_gui(settings_instance: Settings) -> Tuple[OverlayListener, Optional[tk.Tk]]:
    """
    Creates and initializes the graphical user interface (GUI) for the application.

    Args:
        settings_instance (Settings): The application settings object.

    Returns:
        Tuple[OverlayListener, Optional[tk.Tk]]: A tuple containing the GUI listener
        (MinimalOverlayGUI or DummyOverlayListener) and the Tkinter root window (if GUI is enabled).
    """
    if settings_instance.get("overlay.enabled", True):
        root = tk.Tk()
        gui_instance = MinimalOverlayGUI(root, settings_instance)
        root.overrideredirect(True)
        root.attributes("-topmost", True, "-alpha", 0.9)
        logger.info("MinimalOverlayGUI window created.")
        return gui_instance, root
    else:
        logger.info("GUI is disabled. No overlay listener will be attached.")
        return None, None

def run_app(headless: bool = False) -> Tuple[OverlayListener, CommandMode, ThreadPoolExecutor, Callable[[], None], GeminiAPI, SessionManager, Settings]:
    """
    Initializes and runs the main application components.

    Args:
        headless (bool): If True, runs the application without a GUI.

    Returns:
        Tuple[OverlayListener, CommandMode, ThreadPoolExecutor, Callable[[], None], GeminiAPI, SessionManager, Settings]:
        A tuple containing instances of the GUI listener, CommandMode, ThreadPoolExecutor,
        a shutdown callable, GeminiAPI, SessionManager, and Settings.
    """
    settings_obj = Settings()
    settings = settings_obj.settings

    if headless:
        settings["overlay.enabled"] = False
        logger.info("Running in headless mode. GUI is disabled.")
    
    gui, root = create_gui(settings_obj)

    def on_closing():
        """
        Handles the graceful shutdown of the application.
        Deactivates hotkeys, stops audio recording, shuts down thread pools,
        and quits the GUI.
        """
        logger.info("Initiating graceful shutdown...")
        cmd_mode.deactivate()
        audio_recorder.stop_auto_vad()
        shared_executor.shutdown(wait=True)
        if gui:
            gui.update(OverlayEvent.EXIT_APP, {})
        if root:
            root.quit()
        logger.info("Application shutdown complete.")

    if root:
        root.protocol("WM_DELETE_WINDOW", on_closing)

    session = SessionManager()
    logger.info(f"📁 Session folder created: {session.get_session_root()}")
    
    memory_box = MemoryBox(settings_obj.settings)
    
    llm_api = GeminiAPI(settings_obj.settings)
    
    dispatcher = LLMDispatcher(llm_api, gui_listener=gui)
    
    shared_executor = ThreadPoolExecutor(max_workers=4)

    audio_recorder = AudioRecorder(settings_obj.settings, session, dispatcher, shared_executor, memory_box, gui_listener=gui)
    screenshot = Screenshot(settings_obj.settings, session, memory_box)
    cmd_mode = CommandMode(audio_recorder, dispatcher, screenshot, shared_executor, settings_obj, memory_box, gui_listener=gui)
    cmd_mode.register_global_hotkey()

    if gui and hasattr(cmd_mode, 'get_hotkey_descriptions'):
        settings_obj.set("hotkey_descriptions", cmd_mode.get_hotkey_descriptions())
        if gui:
            gui.update(OverlayEvent.TOGGLE_CONTROLS, {})

    logger.info("✅ Stealth Assistant Running...")
    return gui, cmd_mode, shared_executor, on_closing, llm_api, session, settings_obj

if __name__ == "__main__":
    elevate()

    parser = argparse.ArgumentParser(description="Stealth Assistant Application")
    parser.add_argument("--headless", action="store_true", help="Run the application without a GUI.")
    args = parser.parse_args()

    gui_instance, cmd_mode_instance, shared_executor_instance, on_closing_callable, llm_api_instance, session_instance, settings_instance = run_app(headless=args.headless)
    
    try:
        if gui_instance and hasattr(gui_instance, 'root') and gui_instance.root:
            gui_instance.root.mainloop()
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt detected. Initiating shutdown.")
        on_closing_callable()
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
        on_closing_callable()
    finally:
        logger.info("Application shutting down.")

        try:
            llm_api_instance.save_chat_history_json(session_instance.get_session_root())
        except Exception as e:
            logger.error(f"❌ Failed to save chat_history.json: {e}")

        try:
            if settings_instance.get("semantic_chat_export", False):
                from utils.semantic_export import convert_chat_history
                raw_data = []
                for entry in llm_api_instance.get_chat_history() or []:
                    role = getattr(entry, "role", None)
                    parts = getattr(entry, "parts", [])
                    text = None

                    for part in parts:
                        text = getattr(part, "text", None)
                        if text:
                            break

                    if role and text:
                        raw_data.append({
                            "role": role,
                            "text": text
                        })

                logger.info(f"📜 Raw chat history (first 1 shown): {json.dumps(raw_data[:1], indent=2, ensure_ascii=False)}")
                if raw_data:
                    semantic_path = Path(session_instance.get_session_root()) / "semantic_chat.json"
                    convert_chat_history(raw_data, semantic_path)
                    logger.info(f"✅ Semantic chat history saved: {semantic_path}")
                else:
                    logger.warning("⚠️ No chat history found to export.")
            else:
                logger.info("ℹ️ Semantic export is disabled in config.")
        except Exception as e:
            logger.error(f"❌ Failed to save semantic_chat.json: {e}")