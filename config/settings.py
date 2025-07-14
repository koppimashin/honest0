import yaml
import os
import logging
from cerberus import Validator
from yaml.constructor import ConstructorError

logger = logging.getLogger(__name__)

class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise ConstructorError("Duplicate key found", key_node.start_mark)
            value = self.construct_object(value_node, deep=deep)
            mapping[key] = value
        return mapping

class Settings:
    DEFAULT_SETTINGS = {
        "global_hotkey": "ctrl+shift+a",
        "record_shortcut": "a",
        "cancel_record_shortcut": "b",
        "send_shortcut": "c",
        "screenshot_shortcut": "d",
        "toggle_vad_shortcut": "e",
        "anti_backchannel_shortcut": "f",
        "exit_command_shortcut": "g",
        "vad_aggressiveness": 3,
        "vad_silence_threshold": 1.5,
        "backchannel_duration_threshold": 1.3,
        "system_prompt_file": "system_prompt.txt",
        "auto_analyze_screenshot": False,
        "image_quality": 40,
        "log_key_registration_failures": True,
        "gemini_api_key": "",
        "gemini_model_name": "gemini-2.0-flash-001",
        "gemini_temperature": 0.2,
        "gemini_top_p": 0.85,
        "gemini_top_k": 20,
        "gemini_candidate_count": 1,
        "gemini_max_output_tokens": 1024,
        "gemini_stop_sequences": ["\n###END"],
        "gemini_presence_penalty": 0.05,
        "gemini_frequency_penalty": 0.05,
        "semantic_chat_export": True,
        "overlay": {
            "opacity": 0.92,
            "font_size": 10,
            "font_scale": 1.0,
            "width": 800,
            "height": 500,
            "max_text_lines": 500,
            "prune_interval_chars": 1000,
            "prune_interval_seconds": 5,
            "max_full_buffer_size": 51200,
            "reply_markers": ["**REPLY**", "**ANSWER**"],
            "show_raw_on_missing_marker": True,
            "colors": {
                "background_dark": "black",
                "background_light": "white",
                "text_dark": "white",
                "text_light": "black",
                "status_dark": "red",
                "status_light": "darkred"
            }
        },
        "overlay_hotkeys": {
            "overlay_transparency_down": "left",
            "overlay_transparency_up": "right",
            "overlay_invert_colors": "i",
            "overlay_toggle_mouse_follow": "m",
            "overlay_toggle_visibility": "h",
            "overlay_resize_up": "+",
            "overlay_resize_down": "-",
            "overlay_scroll_up": "up",
            "overlay_scroll_down": "down",
            "overlay_toggle_controls": "k"
        }
    }

    SCHEMA = {
        "global_hotkey": {"type": "string"},
        "record_shortcut": {"type": "string"},
        "cancel_record_shortcut": {"type": "string"},
        "send_shortcut": {"type": "string"},
        "screenshot_shortcut": {"type": "string"},
        "toggle_vad_shortcut": {"type": "string"},
        "anti_backchannel_shortcut": {"type": "string"},
        "exit_command_shortcut": {"type": "string"},
        "vad_aggressiveness": {"type": "integer", "min": 0, "max": 3},
        "vad_silence_threshold": {"type": "float", "min": 0.0},
        "backchannel_duration_threshold": {"type": "float", "min": 0.0},
        "system_prompt_file": {"type": "string"},
        "auto_analyze_screenshot": {"type": "boolean"},
        "image_quality": {"type": "integer", "min": 0, "max": 100},
        "log_key_registration_failures": {"type": "boolean"},
        "gemini_api_key": {"type": "string"},
        "gemini_model_name": {"type": "string"},
        "gemini_temperature": {"type": "float", "min": 0.0, "max": 1.0},
        "gemini_top_p": {"type": "float", "min": 0.0, "max": 1.0},
        "gemini_top_k": {"type": "integer", "min": 0},
        "gemini_candidate_count": {"type": "integer", "min": 1},
        "gemini_max_output_tokens": {"type": "integer", "min": 1},
        "gemini_stop_sequences": {"type": "list", "schema": {"type": "string"}},
        "gemini_presence_penalty": {"type": "float", "min": 0.0, "max": 2.0},
        "gemini_frequency_penalty": {"type": "float", "min": 0.0, "max": 2.0},
        "semantic_chat_export": {"type": "boolean"},
        "overlay": {
            "type": "dict",
            "schema": {
                "opacity": {"type": "float", "min": 0.0, "max": 1.0},
                "font_size": {"type": "integer", "min": 1},
                "font_scale": {"type": "float", "min": 0.1},
                "width": {"type": "integer", "min": 100},
                "height": {"type": "integer", "min": 100},
                "max_text_lines": {"type": "integer", "min": 1},
                "prune_interval_chars": {"type": "integer", "min": 0},
                "prune_interval_seconds": {"type": "integer", "min": 0},
                "max_full_buffer_size": {"type": "integer", "min": 0},
                "reply_markers": {"type": "list", "schema": {"type": "string"}},
                "show_raw_on_missing_marker": {"type": "boolean"},
                "colors": {
                    "type": "dict",
                    "schema": {
                        "background_dark": {"type": "string"},
                        "background_light": {"type": "string"},
                        "text_dark": {"type": "string"},
                        "text_light": {"type": "string"},
                        "status_dark": {"type": "string"},
                        "status_light": {"type": "string"}
                    }
                }
            }
        },
        "overlay_hotkeys": {
            "type": "dict",
            "schema": {
                "overlay_transparency_down": {"type": "string"},
                "overlay_transparency_up": {"type": "string"},
                "overlay_invert_colors": {"type": "string"},
                "overlay_toggle_mouse_follow": {"type": "string"},
                "overlay_toggle_visibility": {"type": "string"},
                "overlay_resize_up": {"type": "string"},
                "overlay_resize_down": {"type": "string"},
                "overlay_scroll_up": {"type": "string"},
                "overlay_scroll_down": {"type": "string"},
                "overlay_toggle_controls": {"type": "string"}
            }
        }
    }

    def __init__(self, config_file="config.yaml"):
        self.config_file = os.path.join(os.path.dirname(__file__), config_file)
        self.settings = self.load_settings()

    def _deep_merge(self, default, override):
        for key, value in override.items():
            if isinstance(value, dict) and key in default and isinstance(default[key], dict):
                default[key] = self._deep_merge(default[key], value)
            else:
                default[key] = value
        return default

    def load_settings(self):
        settings = self._deep_merge({}, self.DEFAULT_SETTINGS) # Start with a deep copy of defaults
        
        user_settings = {}
        try:
            with open(self.config_file, "r") as f:
                user_settings = yaml.load(f, Loader=UniqueKeyLoader)
        except FileNotFoundError:
            logger.warning(f"⚠️ config.yaml not found at {self.config_file}. Using default settings.")
        except ConstructorError as e:
            logger.error(f"❌ YAML parsing error in {self.config_file}: {e}")
        except yaml.YAMLError as e:
            logger.error(f"❌ YAML loading error in {self.config_file}: {e}")

        v = Validator(self.SCHEMA)
        if not v.validate(user_settings):
            logger.error(f"❌ Config validation failed for {self.config_file}:")
            for field, errors in v.errors.items():
                for error in errors:
                    logger.error(f"  - {field}: {error}")
            # Merge valid parts, invalid parts will be ignored or replaced by defaults
            valid_user_settings = v.validated(user_settings)
            if valid_user_settings:
                settings = self._deep_merge(settings, valid_user_settings)
            else:
                logger.warning("No valid user settings to merge. Using default settings entirely.")
        else:
            settings = self._deep_merge(settings, user_settings)

        # Load system prompt from file if specified
        if "system_prompt_file" in settings:
            prompt_path = os.path.join(os.path.dirname(self.config_file), settings["system_prompt_file"])
            try:
                with open(prompt_path, "r", encoding="utf-8") as pf:
                    settings["system_prompt"] = pf.read()
            except FileNotFoundError:
                logger.warning(f"⚠️ system_prompt file not found at {prompt_path}. Using fallback.")
                settings["system_prompt"] = "You are a helpful assistant."
        else:
            settings["system_prompt"] = "You are a helpful assistant." # Default if key is missing

        return settings

    def get(self, key, default=None):
        value = self.settings
        for k in key.split('.'):
            if isinstance(value, dict):
                value = value.get(k)
            else:
                value = None
                break
        
        if value is None and default is not None:
            logger.debug(f"Config key '{key}' not found, using default value: {default}")
            return default
        elif value is None and default is None:
            logger.debug(f"Config key '{key}' not found and no default provided.")
            return None
        return value

    def set(self, key, value):
        keys = key.split('.')
        d = self.settings
        for k in keys[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value
        self.save_settings()

    def save_settings(self):
        # Only save the difference from default settings to keep config.yaml clean
        # For simplicity, we'll save the full current settings for now.
        # A more advanced approach would compare with DEFAULT_SETTINGS and only save overrides.
        with open(self.config_file, "w") as f:
            yaml.safe_dump(self.settings, f, default_flow_style=False)

    def get_overlay_config(self):
        return self.get("overlay", {})

    def get_overlay_hotkeys(self):
        return self.get("overlay_hotkeys", {})