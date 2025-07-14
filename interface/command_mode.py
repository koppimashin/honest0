"""
This module manages global hotkeys and command mode functionality for the Honest0 project.
It orchestrates interactions between audio recording, screenshot capture,
LLM dispatch, and the GUI overlay.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
import logging
import webrtcvad
import keyboard
import numpy as np
import soundfile as sf
import base64
import os
from typing import Any, Optional, List
from PIL import Image

from utils.spinner import spinner_inline
from core.capture.audio_recorder import AudioRecorder
from core.capture.screenshot import Screenshot
from core.dispatch.llm_dispatcher import LLMDispatcher
from core.capture.memory_box import MemoryBox
from interface.overlay import OverlayListener, OverlayEvent

logger = logging.getLogger(__name__)

# Defines a mapping from internal shortcut names to their corresponding action methods.
shortcut_actions = {
    "record_shortcut": "record_audio",
    "cancel_record_shortcut": "cancel_recording",
    "send_shortcut": "send_audio",
    "screenshot_shortcut": "take_screenshot",
    "toggle_vad_shortcut": "toggle_vad"
}

class CommandMode:
    """
    Manages global hotkeys and command mode functionality for the Honest0 project.
    This class is responsible for activating and deactivating command mode,
    registering and unregistering hotkeys, and handling various user commands
    such as audio recording, screenshot capture, and dispatching data to the LLM.
    It integrates with the audio recorder, screenshot module, LLM dispatcher,
    memory box, and the GUI overlay.
    """
    def __init__(self, audio_recorder: AudioRecorder, llm_dispatcher: LLMDispatcher, screenshot: Screenshot, executor: ThreadPoolExecutor, settings: Any, memory_box: MemoryBox, gui_listener: OverlayListener = None):
        """
        Initializes the CommandMode with instances of core components and application settings.

        Args:
            audio_recorder (AudioRecorder): An instance of the AudioRecorder for managing audio input.
            llm_dispatcher (LLMDispatcher): An instance of the LLMDispatcher for sending data to the LLM.
            screenshot (Screenshot): An instance of the Screenshot module for capturing screen images.
            executor (ThreadPoolExecutor): A thread pool executor for running background tasks asynchronously.
            settings (Any): The application settings object, used to retrieve hotkey configurations.
            memory_box (MemoryBox): An instance of the MemoryBox for staging audio and image data.
            gui_listener (OverlayListener, optional): An optional listener for GUI events,
                                                      used to update the overlay based on command mode actions.
        """
        self.settings = settings
        # Retrieve hotkey configurations from settings.
        self.global_hotkey = self.settings.get("global_hotkey")
        self.record_shortcut = self.settings.get("record_shortcut")
        self.cancel_record_shortcut = self.settings.get("cancel_record_shortcut")
        self.send_shortcut = self.settings.get("send_shortcut")
        self.screenshot_shortcut = self.settings.get("screenshot_shortcut")
        self.toggle_vad_shortcut = self.settings.get("toggle_vad_shortcut")
        self.anti_backchannel_shortcut = self.settings.get("anti_backchannel_shortcut")
        self.exit_shortcut = self.settings.get("exit_command_shortcut")
        self.gui_listener = gui_listener
        self.hotkey_handles = {} # Stores references to registered hotkeys for later unregistration.
        self._esc_in_progress = False # Flag to debounce the exit shortcut.

        self.active = False # Current state of command mode (active/inactive).
        self.lock = threading.Lock() # Lock to ensure thread-safe toggling of command mode.
        self.command_hotkeys = [] # List to hold command-specific hotkey objects.
        self.hook_ref = None # Reference to the global keyboard hook.

        # Core component instances.
        self.audio_recorder = audio_recorder
        self.screenshot = screenshot
        self.llm_dispatcher = llm_dispatcher
        self.executor = executor
        self.memory_box = memory_box

        # Set of allowed keys that are not suppressed when command mode is active.
        self.allowed_keys = {
            self.global_hotkey,
            self.record_shortcut,
            self.cancel_record_shortcut,
            self.send_shortcut,
            self.screenshot_shortcut,
            self.toggle_vad_shortcut,
            self.anti_backchannel_shortcut,
            self.exit_shortcut,
            'ctrl', 'shift', 'alt' # Common modifier keys.
        }
        # Add overlay-specific hotkeys to the allowed list.
        overlay_hotkeys = self.settings.get_overlay_hotkeys()
        for key_name, key_value in overlay_hotkeys.items():
            self.allowed_keys.add(key_value)
 
    def register_global_hotkey(self):
        """
        Registers the primary global hotkey that toggles the command mode.
        Also registers the global exit shortcut, which can deactivate command mode or exit the application.
        """
        logger.info("Registering global hotkey with keyboard")
        try:
            keyboard.add_hotkey(self.global_hotkey, self.toggle_command_mode)
            logger.info(f"Global hotkey registered: {self.global_hotkey}")
        except Exception as e:
            logger.error(f"❌ Error registering global hotkey: {e}")
        
        # Register the exit shortcut.
        keyboard.add_hotkey(self.exit_shortcut, self._handle_exit_shortcut)

    def toggle_command_mode(self, state: bool = None):
        """
        Activates or deactivates the command mode.
        When activated, it registers command-specific hotkeys and sets up a global keyboard hook
        to suppress other key presses, ensuring only allowed hotkeys are processed.
        When deactivated, it unregisters all command-specific hotkeys and re-registers the global hotkey.

        Args:
            state (bool, optional): If provided, explicitly sets the active state of command mode.
                                    If None, it toggles the current state.
        """
        with self.lock:
            if state is None:
                self.active = not self.active
            else:
                self.active = state
            
            logger.info(f"Toggling command mode: {self.active}")
            try:
                if self.active:
                    logger.info("✅ Command mode activated")
                    self.audio_recorder.llm_interaction_allowed = True
                    self.register_command_hotkeys()
                    # Hook into all keyboard events to suppress unwanted key presses.
                    self.hook_ref = keyboard.hook(self._global_key_handler)
                    self.register_dummy_suppression_keys()
                    if self.gui_listener:
                        self.gui_listener.update(OverlayEvent.TOGGLE_CONTROLS, {})
                else:
                    logger.info("❌ Command mode deactivated")
                    self.audio_recorder.llm_interaction_allowed = False
                    logger.debug(f"Hotkey handles before deactivation: {self.hotkey_handles.keys()}")
                    self.unregister_command_hotkeys()
                    if self.gui_listener:
                        self.gui_listener.update(OverlayEvent.TOGGLE_CONTROLS, {})
                    try:
                        # Attempt to remove the global hotkey if it was registered.
                        keyboard.remove_hotkey(self.global_hotkey)
                    except Exception:
                        pass # Ignore if hotkey was not found.
                    keyboard.unhook_all() # Unhook all global keyboard events.
                    self.hook_ref = None
                    time.sleep(0.05) # Small delay to ensure unhooking is complete.
                    self.register_global_hotkey() # Re-register the global hotkey for activation.
                    logger.debug("All hotkeys successfully unregistered.")
            except Exception as e:
                logger.error(f"❌ toggle_command_mode error: {e}")

    def safe_callback(self, fn):
        """
        A decorator-like method that wraps a hotkey callback function.
        It ensures that any exceptions raised within the callback are caught and logged,
        preventing the application from crashing due to unhandled hotkey errors.

        Args:
            fn (Callable): The original function to be wrapped.

        Returns:
            Callable: The wrapped function that includes error handling.
        """
        def wrapper():
            try:
                fn()
            except Exception as e:
                logger.error(f"❌ Error in hotkey callback {fn.__name__}: {e}")
        return wrapper

    def register_command_hotkeys(self):
        """
        Registers hotkeys for various command mode actions, such as recording audio,
        sending data, taking screenshots, and toggling VAD.
        It also dynamically registers hotkeys for GUI overlay controls if a GUI listener is present.
        Hotkeys are registered with `suppress=True` to prevent their default system behavior.
        """
        def add_hotkey(name, callback):
            """Helper function to add a hotkey and store its handle."""
            logger.info(f"Attempting to register hotkey: {name}")
            try:
                handle = keyboard.add_hotkey(name, self.safe_callback(callback), suppress=True)
                self.hotkey_handles[name] = handle
                logger.info(f"✅ Hotkey registered: {name}")
            except ValueError as e:
                logger.warning(f"⚠️ Skipping unmapped key '{name}': {e}")
            except Exception as e:
                logger.error(f"❌ Unexpected error registering key '{name}': {e}")

        overlay_hotkeys = self.settings.get_overlay_hotkeys()
        used_keys = set() # Keep track of keys already assigned to avoid conflicts.

        # Define core command hotkeys and their corresponding methods.
        core_hotkeys = {
            self.record_shortcut: self.record_audio,
            self.cancel_record_shortcut: self.cancel_recording,
            self.send_shortcut: self.send_audio,
            self.screenshot_shortcut: self.take_screenshot,
            self.toggle_vad_shortcut: self.toggle_vad,
            self.anti_backchannel_shortcut: self.toggle_anti_backchannel
        }

        # Register core hotkeys.
        for key_value, callback_fn in core_hotkeys.items():
            if key_value in used_keys:
                logger.warning(f"⚠️ Hotkey '{key_value}' for core command is already assigned. Skipping.")
                continue
            add_hotkey(key_value, callback_fn)
            used_keys.add(key_value)

        # Define a mapping for GUI overlay hotkeys to their update events.
        gui_hotkey_map = {
            "overlay_transparency_down": lambda: self.gui_listener.update(OverlayEvent.ADJUST_TRANSPARENCY, {"delta": -0.05}),
            "overlay_transparency_up": lambda: self.gui_listener.update(OverlayEvent.ADJUST_TRANSPARENCY, {"delta": 0.05}),
            "overlay_invert_colors": lambda: self.gui_listener.update(OverlayEvent.INVERT_COLORS, {}),
            "overlay_toggle_mouse_follow": lambda: self.gui_listener.update(OverlayEvent.TOGGLE_MOUSE_FOLLOW, {}),
            "overlay_toggle_visibility": lambda: self.gui_listener.update(OverlayEvent.TOGGLE_VISIBILITY, {}),
            "overlay_resize_up": lambda: self.gui_listener.update(OverlayEvent.RESIZE_WINDOW, {"delta": 50}),
            "overlay_resize_down": lambda: self.gui_listener.update(OverlayEvent.RESIZE_WINDOW, {"delta": -50}),
            "overlay_scroll_up": lambda: self.gui_listener.update(OverlayEvent.SCROLL, {"direction": "up"}),
            "overlay_scroll_down": lambda: self.gui_listener.update(OverlayEvent.SCROLL, {"direction": "down"}),
            "overlay_toggle_controls": lambda: self.gui_listener.update(OverlayEvent.TOGGLE_CONTROLS, {})
        }

        # Register GUI hotkeys if a listener is available.
        for name, key_value in overlay_hotkeys.items():
            if key_value in used_keys:
                logger.warning(f"⚠️ Hotkey '{key_value}' for '{name}' is already assigned. Skipping.")
                continue
            if name in gui_hotkey_map:
                add_hotkey(key_value, gui_hotkey_map[name])
                used_keys.add(key_value)
            else:
                logger.warning(f"⚠️ Overlay hotkey '{name}' found in config but no corresponding action defined.")

        logger.info("All command hotkeys registration attempts complete.")

    def unregister_command_hotkeys(self):
        """
        Unregisters all hotkeys that were previously registered for command mode.
        This is typically called when command mode is deactivated to clean up hotkey bindings.
        """
        for key, handle in self.hotkey_handles.items():
            try:
                handle() # Call the handle to unregister the hotkey.
            except Exception as e:
                logger.warning(f"⚠️ Failed to unregister hotkey '{key}': {e}")
        self.hotkey_handles.clear() # Clear the dictionary of handles.
        logger.info("Command hotkeys unregistered.")

    def deactivate(self):
        """
        Deactivates command mode and unhooks all associated hotkeys.
        This method provides a clean shutdown mechanism for the CommandMode instance.
        """
        logger.info("Deactivating CommandMode and unhooking hotkeys.")
        self.toggle_command_mode(state=False)

    def _handle_exit_shortcut(self):
        """
        Handles the global exit shortcut (e.g., 'esc' key press).
        If command mode is currently inactive, pressing this shortcut will exit the entire application.
        If command mode is active, it will deactivate command mode instead of exiting the application.
        A debounce mechanism is included to prevent accidental multiple activations from rapid key presses.
        """
        logger.debug(f"{self.exit_shortcut.upper()} key pressed. _handle_exit_shortcut triggered.")

        # Debounce mechanism to prevent multiple rapid exits.
        if self._esc_in_progress:
            logger.debug("Exit key press debounced.")
            return
        self._esc_in_progress = True

        try:
            if not self.active:
                logger.info(f"{self.exit_shortcut.upper()} pressed and Command Mode is inactive — exiting app.")
                if self.gui_listener:
                    self.gui_listener.update(OverlayEvent.EXIT_APP, {})
                else:
                    logger.warning("Overlay listener not found. Forcing hard exit.")
                    os._exit(0) # Force exit if GUI listener is not available for a graceful shutdown.
            else:
                logger.info(f"{self.exit_shortcut.upper()} pressed — deactivating Command Mode.")
                self.toggle_command_mode(False) # Deactivate command mode.
        finally:
            # Reset the debounce flag after a short delay.
            threading.Timer(0.2, lambda: setattr(self, "_esc_in_progress", False)).start()

    def _global_key_handler(self, event):
        """
        A global keyboard event handler that is hooked when command mode is active.
        Its primary purpose is to suppress (block) any key presses that are not explicitly
        defined in the `allowed_keys` set, ensuring that only command-specific hotkeys are processed.

        Args:
            event (keyboard.KeyboardEvent): The keyboard event object containing details about the key press.

        Returns:
            bool: True if the key event should be allowed to pass through to the system, False to suppress it.
        """
        if not self.active:
            return True # Do not suppress if command mode is inactive.

        if event.event_type == "down":
            logger.debug(f"DEBUG: Global hook received key down: {event.name}")

        if event.event_type == "down":
            if event.name not in self.allowed_keys:
                logger.info(f"🔒 Suppressed: {event.name}")
                return False # Suppress the key press.

        return True # Allow the key press if it's in the allowed list.

    def toggle_vad(self):
        """
        Toggles Voice Activity Detection (VAD) on or off within the audio recorder.
        When VAD is enabled, it initializes the VAD module; when disabled, it unloads it.
        It also starts or stops the audio recorder's auto-VAD functionality based on the new state.
        """
        logger.info("🎙️ Toggle VAD shortcut pressed")
        self.audio_recorder.vad_enabled = not self.audio_recorder.vad_enabled
        
        if self.audio_recorder.vad_enabled:
            # Initialize VAD with the configured aggressiveness level.
            self.audio_recorder.vad = webrtcvad.Vad(self.audio_recorder.vad_aggressiveness)
        else:
            self.audio_recorder.vad = None # Unload VAD.

        if self.audio_recorder.vad_enabled:
            self.audio_recorder.start_auto_vad()
        else:
            self.audio_recorder.stop_auto_vad()

        logger.info(f"VAD {'enabled' if self.audio_recorder.vad_enabled else 'disabled'}")

    def record_audio(self):
        """
        Initiates or toggles the audio recording process via the audio recorder.
        Notifies the GUI listener about the change in recording state.
        """
        logger.info("🎙️ Record audio shortcut pressed")
        self.audio_recorder.toggle_recording()
        self.gui_listener.update(OverlayEvent.RECORDING_STARTED, {})

    def cancel_recording(self):
        """
        Cancels any currently active audio recording and clears staged audio/images.
        """
        logger.info("🛑 Cancel recording shortcut pressed")
        self.audio_recorder.cancel_recording()
        self.memory_box.clear()  # Clear both audio and screenshots
        logger.info("Audio and image data cleared from MemoryBox.")

        if self.gui_listener:
            self.gui_listener.update(OverlayEvent.BUNDLE_CLEARED, {})

    def send_audio(self):
        """
        Stops any active audio recording, processes the recorded audio,
        stages it along with any captured images in the MemoryBox,
        and then dispatches this bundle of data to the LLM for processing.
        Notifies the GUI listener that a bundle has been sent.
        """
        logger.info("📤 Send audio shortcut pressed")
        if self.audio_recorder.state != 'idle':
            self.audio_recorder.stop_recording()
            logger.info("Audio recording stopped for sending.")
        
        # Process and stage recorded audio if available.
        if self.audio_recorder.audio_data:
            concatenated_audio = np.concatenate(self.audio_recorder.audio_data, axis=0)
            import io
            buffer = io.BytesIO()
            sf.write(buffer, concatenated_audio, self.audio_recorder.sample_rate, format='WAV', subtype='PCM_16')
            buffer.seek(0)
            audio_bytes = buffer.getvalue()
            self.memory_box.set_audio(audio_bytes)
            self.audio_recorder.audio_data = [] # Clear audio data after staging.

        # Retrieve the bundled audio and images from MemoryBox.
        audio_to_send, images_to_send = self.memory_box.pop_bundle()

        if audio_to_send or images_to_send:
            # Dispatch the bundle to the LLM in a separate thread.
            self.executor.submit(self.audio_recorder._dispatch_bundle_to_llm_thread, audio=audio_to_send, images=images_to_send, clear_memory_box=False, dispatch_mode="Manual")
            self.gui_listener.update(OverlayEvent.BUNDLE_SENT, {})
        else:
            logger.warning("MemoryBox is empty. Nothing to send for manual dispatch.")

    def take_screenshot(self):
        """
        Initiates the screenshot capture process.
        The actual screenshot capture and handling are performed asynchronously in a separate thread.
        Notifies the GUI listener that a screenshot has been added.
        """
        logger.info("📸 Take screenshot shortcut pressed")
        self.executor.submit(self._take_screenshot_impl)
        self.gui_listener.update(OverlayEvent.SCREENSHOT_ADDED, {})

    def _take_screenshot_impl(self):
        """
        Internal implementation for capturing and handling a screenshot.
        Captures the screenshot, and based on settings, either immediately dispatches it
        to the LLM for auto-analysis or adds it to the MemoryBox and saves it to a file asynchronously.
        """
        try:
            screenshot_image = self.screenshot.capture_screenshot()
            if screenshot_image:
                logger.info("Screenshot captured.")
                if self.gui_listener:
                    self.gui_listener.update(OverlayEvent.SCREENSHOT_ADDED, {})
                
                if self.settings.get("auto_analyze_screenshot"):
                    logger.info("Auto-analyze screenshot enabled. Dispatching immediately.")
                    self.memory_box.add_image(screenshot_image)
                    audio_to_send, images_to_send = self.memory_box.pop_bundle()
                    if audio_to_send or images_to_send:
                        self.executor.submit(self.audio_recorder._dispatch_bundle_to_llm_thread, audio=audio_to_send, images=images_to_send, clear_memory_box=False, dispatch_mode="AutoScreenshot")
                    else:
                        logger.warning("MemoryBox is empty after screenshot. Nothing to send for auto-analyze.")
                else:
                    self.memory_box.add_image(screenshot_image)
                    logger.info(f"Image added to MemoryBox. Current image count: {len(self.memory_box._images)}")
                    
                    image_quality = self.settings.get("image_quality", 75)
                    self.executor.submit(self.screenshot.save_screenshot_to_file, screenshot_image, image_quality)
            else:
                logger.error("❌ Failed to capture screenshot.")
        except Exception as e:
            logger.error(f"❌ Error in screenshot: {e}")
        finally:
            logger.info("✅ Screenshot logic complete")

    def toggle_anti_backchannel(self):
        """
        Toggles the anti-backchanneling feature in the audio recorder.
        This feature is designed to prevent very short, unintentional audio segments
        from being processed as valid input, improving the robustness of voice commands.
        This toggle only has an effect if auto-VAD is currently enabled.
        """
        if self.audio_recorder.auto_vad_enabled:
            self.audio_recorder.toggle_anti_backchannel()
        else:
            logger.warning("⚠️ Anti-backchannel toggle ignored — Auto-VAD not active.")

    def try_register_suppression_key(self, key):
        """
        Attempts to register a dummy hotkey for a given key to suppress its default system behavior.
        This is used to prevent unwanted key presses from interfering with command mode
        when the global keyboard hook is active. Failures are logged based on settings.

        Args:
            key (str): The string representation of the key to suppress (e.g., 'a', 'space', 'enter').
        """
        log_failures = self.settings.get("log_key_registration_failures", True)
        try:
            scan_codes = keyboard.key_to_scan_codes(key)
            if not scan_codes:
                if log_failures:
                    logger.warning(f"⚠️ No scan code for: {key}")
                return
            # Register a dummy hotkey that does nothing but suppresses the key.
            hk = keyboard.add_hotkey(key, lambda: None, suppress=True)
            self.hotkey_handles[key] = hk
        except ValueError as e:
            if log_failures:
                logger.warning(f"⚠️ Skipping unmapped key '{key}': {e}")
        except Exception as e:
            if log_failures:
                logger.error(f"❌ Could not register dummy suppressor for '{key}': {e}")

    def register_dummy_suppression_keys(self):
        """
        Registers dummy hotkeys for a comprehensive set of common keyboard keys.
        This is crucial for ensuring that when command mode is active, most key presses
        are suppressed, preventing them from interfering with the dedicated hotkey commands.
        Keys explicitly defined as command shortcuts are protected from suppression.
        """
        logger.info("Registering dummy suppression keys...")

        import string
        # Include all lowercase letters, digits, and common punctuation (excluding single quote).
        all_keys = set(string.ascii_lowercase + string.digits + string.punctuation.replace("'", "") + " ")

        # Add a set of special keys.
        special_keys = {
            'tab', 'caps lock', 'enter', 'space', 'backspace',
            'up', 'down', 'left', 'right',
            'home', 'end', 'insert', 'delete', 'page up', 'page down',
            'scroll lock', 'pause', 'print screen', 'num lock', 'menu',
            'shift', 'ctrl', 'alt', 'alt gr', 'windows',
            'esc'
        }

        # Add function keys (F1-F24).
        function_keys = {f'f{i}' for i in range(1, 25)}

        # Add Numpad keys.
        numpad_keys = {
            'num 0', 'num 1', 'num 2', 'num 3', 'num 4',
            'num 5', 'num 6', 'num 7', 'num 8', 'num 9',
            'add', 'subtract', 'multiply', 'divide', 'decimal', 'enter'
        }

        # Combine all key sets.
        all_keys.update(special_keys)
        all_keys.update(function_keys)
        all_keys.update(numpad_keys)

        # Define keys that should NOT be suppressed because they are command shortcuts.
        protected_keys = {
            self.record_shortcut,
            self.cancel_record_shortcut,
            self.send_shortcut,
            self.screenshot_shortcut,
            self.toggle_vad_shortcut,
            self.anti_backchannel_shortcut,
            self.exit_shortcut
        }

        log_failures = self.settings.get("log_key_registration_failures", True)

        # Iterate through all identified keys and attempt to register suppression hotkeys,
        # skipping those that are protected.
        for key in all_keys:
            if key in protected_keys:
                continue
            self.try_register_suppression_key(key)