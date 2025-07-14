"""
This module provides an interface for interacting with the Google Gemini API,
inheriting from `BaseLLMAPI`. It handles multimodal input (audio and images),
manages chat history, and streams responses from the Gemini model.
"""

import google.generativeai as genai
from google.generativeai import types
from PIL import Image
from io import BytesIO
import base64
import os
import logging
import datetime
import json
import threading
import time
from typing import Any, Optional, List

from services.base_api import BaseLLMAPI

# Configure basic logging for the module.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GeminiAPI(BaseLLMAPI):
    """
    A concrete implementation of `BaseLLMAPI` for interacting with the Google Gemini model.
    It supports sending multimodal inputs (audio and images) and managing conversational context.
    """
    def __init__(self, settings: dict):
        """
        Initializes the GeminiAPI client.

        Args:
            settings (dict): A dictionary containing application settings, including
                             Gemini API key, model name, and generation configurations.
        """
        self.settings = settings
        self.chat = None # Initialize chat session to None.

        # Retrieve and configure Gemini API key.
        self.gemini_api_key = self.settings.get("gemini_api_key")
        genai.configure(api_key=self.gemini_api_key)

        # Load system prompt from a file or fallback to settings/default.
        self.system_prompt = "You are a helpful AI assistant."  # Default fallback.
        system_prompt_file = self.settings.get("system_prompt_file", "system_prompt.txt")
        # Construct the path to the system prompt file relative to the current script.
        system_prompt_path = os.path.join(os.path.dirname(__file__), '..', 'config', system_prompt_file)

        try:
            logging.info(f"Loading system prompt from: {system_prompt_path}")
            with open(system_prompt_path, "r", encoding="utf-8") as f:
                self.system_prompt = f.read()
            logging.info("System prompt loaded successfully.")
        except FileNotFoundError:
            logging.warning(f"System prompt file not found at '{system_prompt_path}'.")
            fallback = self.settings.get("system_prompt")
            if fallback:
                self.system_prompt = fallback
                logging.info("System prompt loaded from config.json.")
            else:
                logging.warning("Using default system prompt.")

        # Initialize the GenerativeModel with specified configurations.
        self.gemini_model_name = self.settings.get("gemini_model_name", "gemini-2.0-flash-001")
        self.model = genai.GenerativeModel(
            model_name=self.gemini_model_name,
            system_instruction=self.system_prompt,
            generation_config=types.GenerationConfig(
                temperature=self.settings.get("gemini_temperature", 0.2),
                top_p=self.settings.get("gemini_top_p", 0.85),
                top_k=self.settings.get("gemini_top_k", 20),
                candidate_count=self.settings.get("gemini_candidate_count", 1),
                max_output_tokens=self.settings.get("gemini_max_output_tokens", 1024),
                stop_sequences=self.settings.get("gemini_stop_sequences", ["\n###END"]),
                # Optional parameters, commented out by default.
                # presence_penalty=self.settings.get("gemini_presence_penalty", 0.05),
                # frequency_penalty=self.settings.get("gemini_frequency_penalty", 0.05),
            )
        )

        # Start a new chat session with an empty history.
        self.chat = self.model.start_chat(history=[])
        logging.info("GeminiAPI initialized in chat mode (default).")
        self.timeout = self.settings.get("gemini_stream_timeout", 15)

    def _stream_with_timeout(self, stream: Any, timeout: int) -> str:
        """
        Helper method to consume a generator stream with a timeout.
        This is used to prevent the application from hanging indefinitely
        if the LLM stream does not complete.

        Args:
            stream (Any): The generator stream to consume.
            timeout (int): The maximum time in seconds to wait for the stream to complete.

        Returns:
            str: The concatenated result from the stream. Returns partial result on timeout.
        """
        result = []
        done = threading.Event() # Event to signal completion of the stream reading thread.
        start_time = time.time() # Record start time for timeout calculation.

        def read():
            """Internal function to read from the stream in a separate thread."""
            try:
                for chunk in stream:
                    if hasattr(chunk, "text"):
                        result.append(chunk.text)
                        logging.debug(f"[GeminiAPI] Stream chunk: {repr(chunk.text)}")
                    else:
                        logging.warning("Gemini chunk missing 'text' field.")
            finally:
                done.set() # Signal that reading is complete (or an error occurred).

        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        finished = done.wait(timeout) # Wait for the 'done' event or timeout.
        duration = time.time() - start_time # Calculate the actual duration.

        if not finished:
            logging.error("Gemini stream timed out after %s seconds.", timeout)
            return "".join(result).strip()  # Return any partial result on timeout.
        else:
            full_result = "".join(result).strip()
            logging.info(f"LLM stream duration: {duration:.2f}s")
            logging.info(f"LLM returned {len(full_result)} characters in {len(result)} chunks")
            logging.info("Gemini stream completed successfully.")
            return full_result

    def send_multimodal(self, audio: Optional[bytes] = None, images: Optional[List[Image.Image]] = None):
        """
        Sends multimodal content (audio and/or images) to the Gemini model.
        This method constructs the appropriate payload and yields text chunks
        as they are received from the streaming API response.

        Args:
            audio (Optional[bytes]): Optional audio data in WAV format bytes.
            images (Optional[List[Image.Image]]): Optional list of PIL Image objects.

        Yields:
            str: Text chunks from the Gemini model's response.

        Raises:
            ValueError: If neither audio nor images are provided.
            Exception: If there is an error during the API call.
        """
        if not audio and not images:
            raise ValueError("At least one of audio or images must be provided.")

        # Construct the initial prompt parts based on the input types.
        prompt_parts = [
            "You will receive input via audio and/or image.",
            "Always include the following sections, formatted in Markdown:"
        ]

        if audio:
            prompt_parts.append("First, give your spoken REPLY based on the audio input. Then, provide a complete TRANSCRIPTION of what you heard.")
        if images:
            prompt_parts.append("Give your spoken REPLY based on the  image and provide a detailed IMAGE-N-DESCRIPTION.")

        prompt_parts.append("**REPLY**\n<Your spoken reply with 5-12 lines goes here>\n")

        if audio:
            prompt_parts.append("**TRANSCRIPTION**\n<Verbatim transcript of the audio input>\n")
        if images:
            for i in range(len(images)):
                prompt_parts.append(f"**IMAGE-{i+1}-DESCRIPTION**\n<Description of image {i+1} in detail>\n")

        # Create the initial payload with the constructed prompt.
        payload = [{"text": "\n".join(prompt_parts)}]

        # Add audio and image parts to the payload.
        if audio:
            payload.append({"mime_type": "audio/wav", "data": audio})
        if images:
            for img in images:
                buffered = BytesIO()
                img.save(buffered, format="PNG") # Save PIL Image to a BytesIO buffer as PNG.
                payload.append({"mime_type": "image/png", "data": buffered.getvalue()})

        try:
            logging.info("Sending multimodal content to Gemini API...")
            # Send the message to the chat model with streaming enabled.
            response_stream = self.chat.send_message(payload, stream=True)
            
            # Yield each chunk of text as it arrives from the stream.
            for chunk in response_stream:
                if hasattr(chunk, "text"):
                    logging.info(f"[GeminiAPI] Stream chunk: {repr(chunk.text)}")
                    yield chunk.text # Yield the text chunk.
                else:
                    logging.warning("Gemini chunk missing 'text' field.")
            
            logging.info("Multimodal content stream completed successfully.")
        except Exception as e:
            logging.error(f"Error sending multimodal content to Gemini API: {e}")
            raise # Re-raise the exception for upstream handling.

    def get_chat_history(self) -> Optional[list]:
        """
        Retrieves the current chat history from the Gemini model.

        Returns:
            Optional[list]: A list of chat messages if a chat session is active, otherwise None.
        """
        return self.chat.history if self.chat else None

    def save_chat_history_json(self, session_dir: str):
        """
        Saves the current chat history to a JSON file within the specified session directory.

        Args:
            session_dir (str): The directory path where the chat history JSON file will be saved.
        """
        if not self.chat or not self.chat.history:
            logging.info("No chat history to save.")
            return

        filename = os.path.join(session_dir, "chat_history.json")

        history_data = []
        for message in self.chat.history:
            role = message.role
            parts = message.parts

            part_data = {}
            if parts:
                part = parts[0] # Assuming each message has at least one part.
                if hasattr(part, "text") and part.text:
                    part_data["text"] = part.text
                elif hasattr(part, "inline_data"):
                    # Handle inline multimedia data (e.g., images sent by the model).
                    part_data["text"] = "<inline multimedia data>"
                    part_data["mime_type"] = getattr(part.inline_data, "mime_type", "unknown")

            entry = {
                "role": role,
                "timestamp": datetime.datetime.now().isoformat(), # Add current timestamp.
                **part_data # Unpack part_data into the entry.
            }
            history_data.append(entry)

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(history_data, f, indent=2, ensure_ascii=False) # Pretty print JSON.
            logging.info(f"💾 Chat history saved to {filename}")
        except Exception as e:
            logging.error(f"❌ Failed to save chat history to JSON: {e}")