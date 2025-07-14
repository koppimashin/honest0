
__version__ = "0.1.0" # Explicit Versioning for the overlay module.

from abc import ABC, abstractmethod
from typing import Any, Dict, TypedDict, Optional
from enum import Enum
import re
from datetime import datetime
import textwrap
import logging
import tkinter as tk
from tkinter import ttk
import time
import sys
from config.settings import Settings

logger = logging.getLogger(__name__)

class OverlayListener(ABC):
    """
    Abstract Base Class (ABC) for an overlay listener.
    Any class that needs to receive updates from the application to control the overlay
    should inherit from this class and implement the `update` method.
    """
    @abstractmethod
    def update(self, event_type: 'OverlayEvent', payload: Dict[str, Any]) -> None:
        """
        Receives updates from other application components to control the overlay's state and display.

        Args:
            event_type (OverlayEvent): An enum member indicating the type of event that occurred.
            payload (Dict[str, Any]): A dictionary containing additional data relevant to the event.
        """
        pass

class OverlayEvent(Enum):
    """
    Defines a set of distinct events that can be dispatched to the `MinimalOverlayGUI`
    to trigger specific updates or actions.
    """
    RECORDING_STARTED   = "recording_started"   # Signals that audio recording has begun.
    RECORDING_STOPPED   = "recording_stopped"   # Signals that audio recording has ended.
    AUDIO_TICK          = "audio_tick"          # Provides periodic updates on audio recording duration.
    SCREENSHOT_ADDED    = "screenshot_added"    # Indicates a new screenshot has been captured.
    BUNDLE_SENT         = "bundle_sent"         # Confirms that an audio/image bundle has been dispatched to the LLM.
    STREAM_START        = "stream_start"        # Initiates the display of a new LLM reply stream.
    STREAM_CHUNK        = "stream_chunk"        # Provides a new chunk of text for the ongoing LLM reply stream.
    STREAM_END          = "stream_end"          # Signals the completion of an LLM reply stream.
    INVERT_COLORS       = "invert_colors"       # Toggles the color scheme of the overlay (e.g., dark to light).
    TOGGLE_CONTROLS     = "toggle_controls"     # Toggles the visibility of the overlay's control shortcuts.
    ADJUST_TRANSPARENCY = "adjust_transparency" # Adjusts the opacity level of the overlay window.
    RESIZE_WINDOW       = "resize_window"       # Resizes the overlay window dimensions.
    SCROLL              = "scroll"              # Scrolls the text content within the overlay.
    TOGGLE_MOUSE_FOLLOW = "toggle_mouse_follow" # Toggles whether the overlay window follows the mouse cursor.
    TOGGLE_VISIBILITY   = "toggle_visibility"   # Toggles the overall visibility of the overlay window.
    EXIT_APP            = "exit_app"            # Signals the overlay to initiate application shutdown.
    AUTO_VAD_TOGGLED    = "auto_vad_toggled"    # Indicates that Voice Activity Detection (VAD) auto-mode has been toggled.
    BUNDLE_CLEARED      = "bundle_cleared"      # Signals that the MemoryBox has been cleared of audio and images.

# Define TypedDicts for event payloads to ensure type safety and clarity of data structures.
class AudioTickPayload(TypedDict):
    """Payload for `AUDIO_TICK` event, containing the time delta."""
    delta: float

class StreamStartPayload(TypedDict, total=False):
    """Payload for `STREAM_START` event, indicating the mode and an optional request ID."""
    mode: str
    request_id: str

class StreamChunkPayload(TypedDict, total=False):
    """Payload for `STREAM_CHUNK` event, containing a text chunk and an optional request ID."""
    text: str
    request_id: str

class StreamEndPayload(TypedDict, total=False):
    """Payload for `STREAM_END` event, with an optional request ID."""
    request_id: str

class AdjustTransparencyPayload(TypedDict):
    """Payload for `ADJUST_TRANSPARENCY` event, specifying the transparency adjustment delta."""
    delta: float

class ResizeWindowPayload(TypedDict):
    """Payload for `RESIZE_WINDOW` event, specifying the window resize delta."""
    delta: int

class ScrollPayload(TypedDict):
    """Payload for `SCROLL` event, indicating the scroll direction."""
    direction: str

class MinimalOverlayGUI(OverlayListener):
    """
    Implements a minimal, always-on-top Tkinter overlay GUI for the Honest0 application.
    It displays status information, streams LLM responses, and provides configurable controls.
    """
    def __init__(self, root: tk.Tk, settings: Settings):
        """
        Initializes the MinimalOverlayGUI.

        Args:
            root (tk.Tk): The root Tkinter window.
            settings (Settings): The application settings object, used for configuration.
        """
        self.root = root
        self.settings = settings
        self.root.title("Honest0 Assistant Overlay") # Set a descriptive window title.
        self.root.overrideredirect(True) # Removes window decorations (title bar, borders).
        self.root.attributes("-topmost", True) # Ensures the window stays on top of others.

        overlay_config = self.settings.get_overlay_config()

        # Load overlay configuration settings.
        self.transparency = overlay_config.get("opacity", 0.92)
        self.font_family = overlay_config.get("font_family", "Courier")
        self.base_font_size = overlay_config.get("font_size", 10)
        self.font_scale = overlay_config.get("font_scale", 1.0)
        self.width = overlay_config.get("width", 800)
        self.height = overlay_config.get("height", 500)
        self.max_text_lines = overlay_config.get("max_text_lines", 500)
        self.prune_interval_chars = overlay_config.get("prune_interval_chars", 1000)
        self.prune_interval_seconds = overlay_config.get("prune_interval_seconds", 5)
        self.max_full_buffer_size = overlay_config.get("max_full_buffer_size", 50 * 1024)
        self.reply_markers_list = overlay_config.get("reply_markers", ["**REPLY**", "**ANSWER**"])
        self.show_raw_on_missing_marker = overlay_config.get("show_raw_on_missing_marker", True)

        # Load color scheme settings.
        colors_config = overlay_config.get("colors", {})
        self.colors_dark_bg = colors_config.get("background_dark", "black")
        self.colors_light_bg = colors_config.get("background_light", "white")
        self.colors_dark_text = colors_config.get("text_dark", "white")
        self.colors_light_text = colors_config.get("text_light", "black")
        self.colors_dark_status = colors_config.get("status_dark", "red")
        self.colors_light_status = colors_config.get("status_light", "darkred")

        # Compile regex for reply markers for efficient searching.
        reply_patterns = [re.escape(m.strip("* ")) for m in self.reply_markers_list]
        self.re_reply_marker = re.compile(r'(?im)^\*\*\s*(?:' + '|'.join(reply_patterns) + r')\s*\*\*')

        # Apply initial window geometry and attributes.
        self.root.geometry(f"{self.width}x{self.height}+300+200")
        self.root.attributes("-alpha", self.transparency)
        self.root.configure(bg=self.colors_dark_bg)

        # Initialize internal state variables for streaming and GUI management.
        self.reply_counter = 0
        self.accepting_reply_stream = False
        self.reply_seen = False
        self.full_buffer = ""
        self.last_n_chars_buffer = ""
        self.stream_active_lock = False
        self.prune_schedule_id = None
        self.is_typing = False
        self.typing_animation_id = None

        # Initialize GUI feature flags.
        self.is_dark = True
        self.follow_mouse = False
        self.recording = False
        self.audio_seconds = 0
        self.screenshot_count = 0
        self.window_visible = True
        self.controls_visible = False
        self.auto_vad = False

        # Build the user interface and update initial status.
        self._build_ui()
        self._update_status()

        # Bind event handlers for window resizing and mouse wheel scrolling.
        self.root.bind("<Configure>", self._on_resize)
        self.root.bind("<MouseWheel>", self._on_mousewheel)
        self.root.bind("<Button-4>", self._on_mousewheel) # For Linux/X11 mouse wheel up.
        self.root.bind("<Button-5>", self._on_mousewheel) # For Linux/X11 mouse wheel down.

    def _build_ui(self):
        """
        Constructs or reconstructs the main user interface elements of the overlay.
        This method clears existing widgets and sets up the grid layout for status,
        main text display, and controls.
        """
        # Destroy all existing widgets to allow for UI reconstruction (e.g., on theme change).
        for widget in self.root.winfo_children():
            widget.destroy()

        # Configure grid weights for responsive layout.
        self.root.grid_rowconfigure(0, weight=0) # Row for status labels (fixed height).
        self.root.grid_rowconfigure(1, weight=1) # Row for main content area (expands vertically).
        self.root.grid_columnconfigure(0, weight=1) # Single column (expands horizontally).

        # Calculate font sizes based on base size and scale.
        scaled_font_size = int(self.base_font_size * self.font_scale)
        controls_font_size = int(scaled_font_size * 0.9) # Slightly smaller font for controls.

        # Status label (top-left) for recording time and screenshot count.
        self.status_label = tk.Label(self.root, text="", bg=self.colors_dark_bg, fg=self.colors_dark_status, anchor="w", font=(self.font_family, scaled_font_size))
        self.status_label.grid(row=0, column=0, padx=5, pady=5, sticky="nw")
        # Typing indicator label (top-right) for LLM streaming status.
        self.typing_indicator_label = tk.Label(self.root, text="", bg=self.colors_dark_bg, fg=self.colors_dark_status, anchor="e", font=(self.font_family, scaled_font_size))
        self.typing_indicator_label.grid(row=0, column=0, padx=5, pady=5, sticky="ne") # Placed in same row, but sticky "ne" to align right.

        # Main content area frame, occupying the second row of the root window.
        self.main_content_area = tk.Frame(self.root, bg=self.colors_dark_bg)
        self.main_content_area.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="nsew")

        # Configure grid within main_content_area for reply header, main text, and controls.
        self.main_content_area.grid_columnconfigure(0, weight=1)
        self.main_content_area.grid_rowconfigure(0, weight=0) # Row for reply header (currently unused, but reserved).
        self.main_content_area.grid_rowconfigure(1, weight=1) # Row for main text frame (expands vertically).
        self.main_content_area.grid_rowconfigure(2, weight=0) # Row for controls frame (fixed height).


        # Main Text Frame, containing the Text widget and its scrollbar.
        self.main_text_frame = tk.Frame(self.main_content_area, bg=self.colors_dark_bg, highlightbackground="white", highlightthickness=1)
        self.main_text_frame.grid(row=1, column=0, sticky="nsew") # Placed in row 1 of main_content_area.

        # Text widget for displaying LLM replies and other textual content.
        self.main_text = tk.Text(self.main_text_frame, bg=self.colors_dark_bg, fg=self.colors_dark_text, wrap="word", font=(self.font_family, scaled_font_size), bd=0, highlightthickness=0)
        self.main_text.pack(side="left", fill="both", expand=True, padx=2, pady=2)

        # Configure ttk.Scrollbar styling for a consistent look.
        style = ttk.Style()
        style.theme_use('clam') # Use 'clam' theme for better customization.
        style.configure("TScrollbar",
                        background=self.colors_dark_bg, troughcolor=self.colors_dark_bg, bordercolor=self.colors_dark_bg,
                        arrowcolor=self.colors_dark_bg, lightcolor=self.colors_dark_bg, darkcolor=self.colors_dark_bg,
                        gripcount=0, relief="flat")
        style.map("Vertical.TScrollbar",
                  background=[('active', self.colors_dark_bg), ('!active', self.colors_dark_bg)],
                  troughcolor=[('active', self.colors_dark_bg), ('!active', self.colors_dark_bg)])

        # Vertical scrollbar for the main text area.
        self.text_scrollbar = ttk.Scrollbar(self.main_text_frame, command=self.main_text.yview, orient="vertical")
        self.text_scrollbar.pack(side="right", fill="y")
        self.main_text.config(yscrollcommand=self.text_scrollbar.set)
        self.main_text.config(state="disabled") # Initially disable text editing.

        # Controls frame for displaying hotkey shortcuts.
        self.controls_frame = tk.Frame(self.main_content_area, bg=self.colors_dark_bg, highlightbackground="white", highlightthickness=1)

        # Label within the controls frame to display formatted hotkey information.
        self.controls_label = tk.Label(
            self.controls_frame,
            text=self._format_controls(),
            bg=self.colors_dark_bg,
            fg="gray", # Default gray for controls text.
            font=(self.font_family, controls_font_size),
            anchor="w",
            justify="left",
            wraplength=self.width - 40 # Initial wraplength, adjusted dynamically on resize.
        )
        self.controls_label.pack(padx=5, pady=5, fill="x", expand=True)

        self._update_controls_layout() # Set initial layout based on self.controls_visible state.

    def _update_controls_layout(self):
        """
        Manages the visibility and grid layout of the main text frame and controls frame.
        When controls are visible, they occupy a separate row; otherwise, they are hidden.
        """
        # Ensure main_text_frame always occupies row 1 and expands.
        self.main_content_area.grid_rowconfigure(1, weight=1)
        self.main_text_frame.grid(row=1, column=0, sticky="nsew")

        if self.controls_visible:
            # If controls are visible, place controls_frame in row 2.
            self.main_content_area.grid_rowconfigure(2, weight=0) # Fixed height for controls row.
            self.controls_frame.grid(row=2, column=0, pady=(5,0), sticky="ew")
        else:
            # If controls are hidden, remove controls_frame from grid.
            self.controls_frame.grid_forget()
            self.main_content_area.grid_rowconfigure(2, weight=0) # Ensure row 2 has no weight when hidden.

        self.root.update_idletasks() # Force update of geometry information.
        self._on_resize() # Recalculate wraplength for controls label.

    def _on_resize(self, event=None):
        """
        Event handler for window resize events.
        Adjusts the `wraplength` of the controls label to fit the new window width.

        Args:
            event (tk.Event, optional): The Tkinter event object. Defaults to None.
        """
        if self.controls_visible and self.controls_frame.winfo_width() > 0:
            # If controls are visible, adjust wraplength based on controls frame width.
            self.controls_label.config(wraplength=self.controls_frame.winfo_width() - 10)
        elif not self.controls_visible and self.main_content_area.winfo_width() > 0:
            # If controls are hidden, adjust wraplength based on main content area width.
            self.controls_label.config(wraplength=self.main_content_area.winfo_width() - 20)

    def _on_mousewheel(self, event):
        """
        Event handler for mouse wheel scrolling.
        Scrolls the `main_text` widget content up or down.

        Args:
            event (tk.Event): The Tkinter event object containing mouse wheel details.

        Returns:
            str: "break" to stop the event from propagating further.
        """
        if event.delta: # For Windows/macOS.
            self.main_text.yview_scroll(int(-1*(event.delta/120)), "units")
        elif event.num == 4: # For Linux/X11 (scroll up).
            self.main_text.yview_scroll(-1, "units")
        elif event.num == 5: # For Linux/X11 (scroll down).
            self.main_text.yview_scroll(1, "units")
        return "break"

    def _format_controls(self):
        """
        Generates a formatted string of hotkey shortcuts and their descriptions.
        Combines core command hotkeys with overlay-specific hotkeys from settings.

        Returns:
            str: A pipe-separated string of "key: description" pairs.
        """
        overlay_hotkeys = self.settings.get_overlay_hotkeys()

        # Load core command hotkeys and their default descriptions.
        core_keys = {
            self.settings.get("record_shortcut", "r"): "record",
            self.settings.get("cancel_record_shortcut", "c"): "cancel_record",
            self.settings.get("send_shortcut", "s"): "send bundle",
            self.settings.get("screenshot_shortcut", "p"): "screenshot",
            self.settings.get("toggle_vad_shortcut", "v"): "toggle vad",
            self.settings.get("anti_backchannel_shortcut", "b"): "anti-backchannel",
            self.settings.get("exit_command_shortcut", "esc"): "exit"
        }

        # Define descriptions for overlay-specific hotkeys.
        overlay_labels = {
            "overlay_transparency_down": "transparency down",
            "overlay_transparency_up": "transparency up",
            "overlay_invert_colors": "invert colors",
            "overlay_toggle_mouse_follow": "mouse follow",
            "overlay_toggle_visibility": "hide/show window",
            "overlay_resize_up": "resize window up",
            "overlay_resize_down": "resize window down",
            "overlay_scroll_up": "scroll up",
            "overlay_scroll_down": "scroll down",
            "overlay_toggle_controls": "toggle controls"
        }

        # Merge overlay-specific hotkeys into the core_keys dictionary.
        for config_key, label in overlay_labels.items():
            key = overlay_hotkeys.get(config_key)
            if key:
                core_keys[key] = label

        # Format and join all hotkey descriptions.
        return " | ".join(f"{k}: {v}" for k, v in core_keys.items())

    def _adjust_transparency(self, delta: float):
        """
        Adjusts the transparency (alpha) of the overlay window.

        Args:
            delta (float): The amount to add to the current transparency (e.g., 0.05 for increase, -0.05 for decrease).
        """
        self.transparency = max(0.2, min(1.0, self.transparency + delta)) # Clamp transparency between 0.2 and 1.0.
        self.root.attributes("-alpha", self.transparency)

    def _invert_colors(self):
        """
        Toggles the color scheme of the overlay between dark and light modes.
        Updates background, foreground, and status colors for all relevant widgets.
        """
        self.is_dark = not self.is_dark # Toggle the dark mode flag.
        
        # Determine new colors based on the `is_dark` state.
        bg = self.colors_dark_bg if self.is_dark else self.colors_light_bg
        fg = self.colors_dark_text if self.is_dark else self.colors_light_text
        status_fg = self.colors_dark_status if self.is_dark else self.colors_light_status

        # Apply new colors to root window and labels.
        self.root.configure(bg=bg)
        self.status_label.configure(bg=bg, fg=status_fg)
        self.typing_indicator_label.configure(bg=bg, fg=status_fg) # Also update typing indicator.
        self.main_text.configure(bg=bg, fg=fg)
        self.controls_label.configure(bg=bg, fg=fg)

        # Update border colors for frames.
        border_color = self.colors_light_text if not self.is_dark else self.colors_dark_text
        self.main_text_frame.configure(highlightbackground=border_color)
        self.controls_frame.configure(highlightbackground=border_color)
        
        # Update scrollbar styling to match the new background.
        style = ttk.Style()
        style.configure("TScrollbar",
                        background=bg, troughcolor=bg, bordercolor=bg,
                        arrowcolor=bg, lightcolor=bg, darkcolor=bg)
        style.map("Vertical.TScrollbar",
                  background=[('active', bg), ('!active', bg)],
                  troughcolor=[('active', bg), ('!active', bg)])

    def _toggle_mouse_follow(self):
        """
        Toggles whether the overlay window automatically follows the mouse cursor.
        If enabled, it starts a loop to continuously update the window's position.
        """
        self.follow_mouse = not self.follow_mouse
        if self.follow_mouse:
            self._follow_mouse_loop()

    def _follow_mouse_loop(self):
        """
        Continuously updates the overlay window's position to follow the mouse cursor.
        This method is called repeatedly using `root.after` when `follow_mouse` is True.
        """
        if not self.follow_mouse:
            return # Stop the loop if mouse follow is deactivated.
        try:
            x = self.root.winfo_pointerx() # Get current mouse X coordinate.
            y = self.root.winfo_pointery() # Get current mouse Y coordinate.
            self.root.geometry(f"+{x}+{y}") # Set window position.
        except tk.TclError:
            # Handle cases where the Tkinter window might be closing.
            self.follow_mouse = False
            logger.debug("Tkinter error during mouse follow, stopping follow loop.")
        self.root.after(100, self._follow_mouse_loop) # Schedule next update after 100ms.

    def _toggle_visibility(self):
        """
        Toggles the overall visibility of the overlay window.
        Sets the window's alpha attribute to 0.0 (hidden) or its configured transparency (visible).
        """
        self.window_visible = not self.window_visible
        self.root.attributes("-alpha", self.transparency if self.window_visible else 0.0)

    def _toggle_controls_visibility(self):
        """
        Toggles the visibility of the controls frame, which displays hotkey shortcuts.
        Calls `_update_controls_layout` to re-render the UI based on the new visibility state.
        """
        self.controls_visible = not self.controls_visible
        self._update_controls_layout()

    def _resize_window(self, delta: int):
        """
        Resizes the overlay window by a given delta.
        Ensures the window dimensions stay within a minimum size and persists the new size to settings.

        Args:
            delta (int): The amount to add to both width and height (e.g., 50 for increase, -50 for decrease).
        """
        new_width = max(400, self.root.winfo_width() + delta) # Minimum width of 400.
        new_height = max(300, self.root.winfo_height() + delta) # Minimum height of 300.
        
        # Only update if dimensions actually changed to avoid unnecessary operations.
        if new_width != self.width or new_height != self.height:
            self.width = new_width
            self.height = new_height
            self.root.geometry(f"{self.width}x{self.height}") # Apply new geometry.
            self._on_resize() # Trigger resize handler to update wraplength.
            
            # Persist new dimensions to config.yaml for future sessions.
            self.settings.set("overlay.width", self.width)
            self.settings.set("overlay.height", self.height)
            logger.info(f"Window resized to {self.width}x{self.height} and saved to config.")
        else:
            logger.debug("Window resize delta resulted in no change or minimum reached.")

    def _update_status(self, flash_camera: bool = False):
        """
        Updates the status label with current recording time, screenshot count, and VAD status.
        Optionally flashes a camera icon when a screenshot is added.

        Args:
            flash_camera (bool, optional): If True, briefly shows a "📸" icon. Defaults to False.
        """
        camera = "📸" if flash_camera else "📷" # Choose camera icon based on flash_camera.
        if flash_camera:
            # Schedule a call to turn off the flash after a short delay.
            self.root.after(300, lambda: self._update_status(flash_camera=False))
        blink = "🔴" if self.recording and int(time.time() * 2) % 2 == 0 else "  " # Blinking red dot for recording.
        auto_text = " auto" if self.auto_vad else "" # " auto" suffix if auto-VAD is enabled.
        text = f"{blink} {self.audio_seconds:.1f}s   {camera} {self.screenshot_count // 2}{auto_text}" # Format status string.
        self.status_label.config(text=text)

    def _safe(self, fn, *args, **kwargs):
        """
        Ensures that a given function is executed on the main Tkinter thread.
        This is crucial for thread safety when updating GUI elements from other threads.

        Args:
            fn (Callable): The function to execute on the main thread.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.
        """
        self.root.after_idle(lambda: fn(*args, **kwargs))

    def update(self, event_type: OverlayEvent, payload: Dict[str, Any]):
        """
        The main entry point for other application components to send updates to the overlay.
        Dispatches the event and its payload to the appropriate internal handler method,
        ensuring all GUI operations are performed safely on the main Tkinter thread.

        Args:
            event_type (OverlayEvent): The type of event.
            payload (Dict[str, Any]): Additional data for the event.
        """
        try:
            if event_type == OverlayEvent.RECORDING_STARTED:
                self._safe(self._handle_recording_started)
            elif event_type == OverlayEvent.RECORDING_STOPPED:
                self._safe(self._handle_recording_stopped)
            elif event_type == OverlayEvent.BUNDLE_SENT:
                self._safe(self._handle_bundle_sent)
            elif event_type == OverlayEvent.AUDIO_TICK:
                payload: AudioTickPayload = payload
                self._safe(self._handle_audio_tick, payload["delta"])
            elif event_type == OverlayEvent.SCREENSHOT_ADDED:
                self._safe(self._handle_screenshot_added)
            elif event_type == OverlayEvent.STREAM_START:
                payload: StreamStartPayload = payload
                self._safe(self._handle_stream_start, payload.get('mode', 'LLM'), payload.get('request_id'))
            elif event_type == OverlayEvent.STREAM_CHUNK:
                payload: StreamChunkPayload = payload
                self._safe(self._handle_stream_chunk, event_type, payload)
            elif event_type == OverlayEvent.STREAM_END:
                payload: StreamEndPayload = payload
                self._safe(self._handle_stream_end, event_type, payload)
            elif event_type == OverlayEvent.INVERT_COLORS:
                self._safe(self._invert_colors)
            elif event_type == OverlayEvent.TOGGLE_CONTROLS:
                self._safe(self._toggle_controls_visibility)
            elif event_type == OverlayEvent.ADJUST_TRANSPARENCY:
                payload: AdjustTransparencyPayload = payload
                self._safe(self._adjust_transparency, payload["delta"])
            elif event_type == OverlayEvent.RESIZE_WINDOW:
                payload: ResizeWindowPayload = payload
                self._safe(self._resize_window, payload["delta"])
            elif event_type == OverlayEvent.SCROLL:
                payload: ScrollPayload = payload
                self._safe(self._handle_scroll, payload["direction"])
            elif event_type == OverlayEvent.TOGGLE_MOUSE_FOLLOW:
                self._safe(self._toggle_mouse_follow)
            elif event_type == OverlayEvent.TOGGLE_VISIBILITY:
                self._safe(self._toggle_visibility)
            elif event_type == OverlayEvent.EXIT_APP:
                self._safe(self.root.quit) # Signal Tkinter to quit its mainloop gracefully.
            elif event_type == OverlayEvent.AUTO_VAD_TOGGLED:
                self._safe(self._handle_auto_vad_toggle, payload.get("enabled", False))
            elif event_type == OverlayEvent.BUNDLE_CLEARED:
                self._safe(self._handle_bundle_cleared)
            else:
                logger.debug(f"Unrecognized OverlayEvent: {event_type.value}")
        except Exception as e:
            logger.error(f"Error handling overlay event {event_type.value}: {e}")

    def _handle_auto_vad_toggle(self, enabled: bool):
        """
        Handles the `AUTO_VAD_TOGGLED` event, updating the internal auto-VAD state
        and refreshing the status display.

        Args:
            enabled (bool): The new state of auto-VAD (True if enabled, False if disabled).
        """
        self.auto_vad = enabled
        self._update_status()

    def _handle_recording_started(self):
        """
        Handles the `RECORDING_STARTED` event.
        Sets the recording flag to True, resets audio seconds, and updates the status display.
        """
        self.recording = True
        self.audio_seconds = 0
        self._update_status()

    def _handle_recording_stopped(self):
        """
        Handles the `RECORDING_STOPPED` event.
        Sets the recording flag to False, resets audio seconds, and updates the status display.
        """
        self.recording = False
        self.audio_seconds = 0
        self._update_status()

    def _handle_bundle_sent(self):
        """
        Handles the `BUNDLE_SENT` event.
        Resets recording status, audio seconds, and screenshot count, then updates the status display.
        """
        self.recording = False
        self.audio_seconds = 0
        self.screenshot_count = 0
        self._update_status()

    def _handle_bundle_cleared(self):
        """
        Handles the `BUNDLE_CLEARED` event.
        Resets screenshot count and audio status when the MemoryBox is cleared.
        """
        logger.info("GUI: Bundle cleared — resetting screenshot count and audio status.")
        self.recording = False # Ensure recording status is reset
        self.audio_seconds = 0
        self.screenshot_count = 0
        self._update_status()

    def _handle_audio_tick(self, delta: float):
        """
        Handles the `AUDIO_TICK` event, incrementing the displayed audio duration
        and updating the status.

        Args:
            delta (float): The time increment in seconds.
        """
        self.audio_seconds += delta
        self._update_status()

    def _handle_screenshot_added(self):
        """
        Handles the `SCREENSHOT_ADDED` event, incrementing the screenshot count
        and triggering a brief camera icon flash in the status display.
        """
        self.screenshot_count += 1
        self._update_status(flash_camera=True)

    def _handle_stream_start(self, mode: str, request_id: Optional[str] = None):
        """
        Handles the `STREAM_START` event, preparing the overlay for a new LLM reply stream.
        Clears previous content, enables the text widget, and starts the typing indicator.

        Args:
            mode (str): The mode of the LLM interaction (e.g., 'LLM').
            request_id (Optional[str]): An optional ID for the request, useful for tracking.
        """
        try:
            if self.stream_active_lock:
                logger.warning("Stream start re-entrancy detected. Skipping new stream.")
                return
            self.stream_active_lock = True # Acquire lock to prevent re-entrancy.

            self.reply_counter += 1
            self.accepting_reply_stream = False
            self.reply_seen = False
            self.full_buffer = ""
            self.last_n_chars_buffer = ""
            self.main_text.config(state="normal") # Enable text widget for new stream content.

            timestamp = datetime.now().strftime("%I:%M %p")
            # The following lines are commented out as the reply header label is not currently used.
            # label = f"🗨️  Reply #{self.reply_counter} — {timestamp}"
            # self.reply_header_label.config(text=label)

            self.main_text.delete("1.0", "end") # Clear any previous content in the text widget.
            self.main_text.mark_set("stream_start", "1.0") # Set a mark at the beginning for new content.
            self.main_text.see("1.0") # Scroll to the top.

            self.is_typing = True # Activate typing indicator.
            self._update_typing_indicator()
            self._schedule_prune() # Schedule periodic pruning of the text buffer.
        except Exception as e:
            logger.error(f"Error in _handle_stream_start: {e}")
            raise # Re-raise to ensure finally block is hit for proper error handling.
        finally:
            # The lock is released in _handle_stream_end. This finally block is primarily
            # for ensuring cleanup if _handle_stream_end is called, not for this method's lock.
            pass

    def _handle_stream_chunk(self, event: OverlayEvent, payload: dict):
        """
        Handles the `STREAM_CHUNK` event, appending new text chunks to the display.
        It also detects reply markers to determine when to start displaying actual LLM replies.

        Args:
            event (OverlayEvent): The event type (should be `STREAM_CHUNK`).
            payload (dict): The payload containing the 'text' chunk.
        """
        text_chunk = payload.get("text", "")
        self.full_buffer += text_chunk
        self.full_buffer = self.full_buffer[-self.max_full_buffer_size:] # Truncate buffer to prevent excessive memory usage.

        combined_text = self.last_n_chars_buffer + text_chunk.lower() # Combine with last chars for marker detection.

        # Detect reply markers to start displaying the actual reply.
        if not self.reply_seen:
            for marker in [m.lower() for m in self.reply_markers_list]: # Check all configured reply markers.
                if marker in combined_text:
                    self.reply_seen = True
                    self.accepting_reply_stream = True
                    logger.debug("Entering REPLY stream.")
                    # If the marker is found, we might need to skip the part of the chunk that contains the marker.
                    # For simplicity, we'll just return here and let the next chunk handle the actual content.
                    self.last_n_chars_buffer = text_chunk[-50:] # Keep last N chars for next chunk.
                    self._update_typing_indicator()
                    return

        # If not yet in a REPLY section, skip this chunk
        if not self.accepting_reply_stream:
            logger.debug(f"Skipping non-REPLY chunk: {text_chunk[:50]}...")
            self.last_n_chars_buffer = text_chunk[-50:] # Keep last N chars for next chunk
            self._update_typing_indicator()
            return

        # Detect any section marker like ### TRANSCRIPTION, ### IMAGE, etc.
        if re.search(r'(?im)^\*\*[A-Z0-9\- ]+\*\*', text_chunk):
            self.accepting_reply_stream = False
            logger.debug(f"Exiting REPLY stream due to new section: {text_chunk.strip()}")
            self.last_n_chars_buffer = text_chunk[-50:]
            self._update_typing_indicator()
            return

        # Display only REPLY body
        self.main_text.insert("stream_start", text_chunk)
        self.main_text.see("1.0")
        self.last_n_chars_buffer = text_chunk[-50:] # Keep last N chars for next chunk
        self._update_typing_indicator()

        # Debounce pruning/redraw
        if len(self.full_buffer) % self.prune_interval_chars < len(text_chunk): # Check if we crossed a threshold
            self._schedule_prune()

    def _handle_stream_end(self, event: OverlayEvent, payload: dict):
        try:
            if self.prune_schedule_id:
                self.root.after_cancel(self.prune_schedule_id)
                self.prune_schedule_id = None

            # Final full-buffer check for REPLY marker if not seen during streaming
            if not self.reply_seen and self.re_reply_marker.search(self.full_buffer):
                self.reply_seen = True
                logger.warning("REPLY marker missed in stream but found in full buffer via regex. Chunking may need review.")

            if not self.reply_seen and self.show_raw_on_missing_marker:
                # If no reply marker was ever found and fallback is enabled, show the full_buffer
                self.main_text.config(state="normal")
                self.main_text.delete("1.0", "end") # Clear any partial content
                
                # Apply textwrap.dedent() for cleaner fallback
                content_to_display = textwrap.dedent(self.full_buffer).strip()
                timestamp = datetime.now().strftime("%I:%M %p")
                footer = f"\n\n— Reply #{self.reply_counter} — {timestamp}"
                self.main_text.insert("1.0", content_to_display + footer)
                
                # self.reply_header_label.config(text="[⚠️ Unstructured response]") # Visual feedback
                logger.debug("No REPLY marker found, displaying full buffer as fallback.")
            elif self.reply_seen:
                # If reply was seen (either during stream or via final regex check), extract and display only REPLY content
                self.main_text.config(state="normal")
                self.main_text.delete("1.0", "end") # Clear any partial content

                match = self.re_reply_marker.search(self.full_buffer)
                if match:
                    start = match.end()
                    next_section = re.search(r'(?im)^\*\*[A-Z0-9\- ]+\*\*', self.full_buffer[start:])
                    end = next_section.start() + start if next_section else len(self.full_buffer)
                    reply_only = self.full_buffer[start:end].strip()
                    matches = re.findall(r'(?im)^\*\*([A-Z0-9\- ]+)\*\*', self.full_buffer)
                    logger.debug(f"Detected sections: {matches}")
                    
                    reply_text = textwrap.dedent(reply_only).strip()
                    timestamp = datetime.now().strftime("%I:%M %p")
                    footer = f"\n\n— Reply #{self.reply_counter} — {timestamp}"
                    self.main_text.insert("1.0", reply_text + footer)
                    
                    logger.debug("REPLY stream ended. Displaying extracted reply.")
                else:
                    # This case should ideally not be hit if reply_seen is True, but as a safeguard
                    content_to_display = textwrap.dedent(self.full_buffer).strip()
                    timestamp = datetime.now().strftime("%I:%M %p")
                    footer = f"\n\n— Reply #{self.reply_counter} — {timestamp}"
                    self.main_text.insert("1.0", content_to_display + footer)
                    logger.warning("REPLY stream ended, but marker not found on final check despite reply_seen. Displaying full buffer.")
            else:
                # Case where no reply was seen and fallback is disabled
                self.main_text.delete("1.0", "end") # Clear any partial content
                # self.reply_header_label.config(text="[No structured reply]") # Visual feedback
                logger.debug("No REPLY marker found and fallback disabled. Displaying nothing.")

            self.main_text.config(state="disabled")
            self._prune_text() # Final prune after stream ends
        except Exception as e:
            logger.error(f"Error in _handle_stream_end: {e}")
            raise # Re-raise to ensure finally block is hit
        finally:
            self.stream_active_lock = False # Release the lock
            self.is_typing = False
            self._update_typing_indicator()

    def _handle_scroll(self, direction):
        if direction == "up":
            self.main_text.yview_scroll(-1, "units")
        elif direction == "down":
            self.main_text.yview_scroll(1, "units")

    def _prune_text(self):
        lines = int(self.main_text.index('end-1c').split('.')[0])
        if lines > self.max_text_lines:
            # Delete lines from the beginning to maintain the cap
            self.main_text.delete('1.0', f'{lines - self.max_text_lines + 1}.0') # +1 to delete the extra line

    def _schedule_prune(self):
        if self.prune_schedule_id:
            self.root.after_cancel(self.prune_schedule_id)
        self.prune_schedule_id = self.root.after(int(self.prune_interval_seconds * 1000), self._perform_prune_and_redraw)

    def _perform_prune_and_redraw(self):
        self._prune_text()
        self.root.update_idletasks() # Force redraw
        self.prune_schedule_id = None # Reset ID after execution

    def _update_typing_indicator(self):
        if self.typing_animation_id:
            self.root.after_cancel(self.typing_animation_id)
            self.typing_animation_id = None

        if self.is_typing:
            dots = "." * (int(time.time() * 2) % 4) # Animate 0 to 3 dots
            self.typing_indicator_label.config(text=f"Thinking{dots}")
            self.typing_animation_id = self.root.after(500, self._update_typing_indicator) # Schedule next frame
        else:
            self.typing_indicator_label.config(text="")