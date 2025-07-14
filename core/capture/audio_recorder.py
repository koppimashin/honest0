import soundcard as sc
import soundfile as sf
import webrtcvad
import threading
import time
import numpy as np
import logging
import warnings
import os
import datetime
from soundcard.mediafoundation import SoundcardRuntimeWarning
from utils.session_manager import SessionManager
from typing import Any
from core.capture.memory_box import MemoryBox
from interface.overlay import OverlayListener, OverlayEvent
warnings.simplefilter("once", SoundcardRuntimeWarning)

logger = logging.getLogger(__name__)

class AudioRecorder:
    """
    Manages audio recording, Voice Activity Detection (VAD), and dispatching audio
    data to the LLM. It supports both manual recording and automatic VAD-based recording.
    """
    def __init__(self, settings: dict, session: SessionManager, llm_dispatcher, executor, memory_box: MemoryBox, gui_listener: OverlayListener = None, sample_rate=16000, frame_duration=30, vad_aggressiveness=3):
        """
        Initializes the AudioRecorder with necessary dependencies and configurations.

        Args:
            settings (dict): Application settings.
            session (SessionManager): Manages session-specific data and paths.
            llm_dispatcher: Dispatches audio and image bundles to the LLM.
            executor: Thread pool executor for background tasks.
            memory_box (MemoryBox): Stores transient data like audio and screenshots.
            gui_listener (OverlayListener, optional): Listener for GUI events. Defaults to None.
            sample_rate (int, optional): Audio sample rate. Defaults to 16000.
            frame_duration (int, optional): Duration of each audio frame in milliseconds. Defaults to 30.
            vad_aggressiveness (int, optional): Aggressiveness level for VAD (0-3). Defaults to 3.
        """
        self.settings = settings
        self.session = session
        self.llm_dispatcher = llm_dispatcher
        self.executor = executor
        self.memory_box = memory_box
        self.gui_listener = gui_listener
        self.sample_rate = sample_rate
        self.frame_duration = frame_duration
        self.vad_aggressiveness = self.settings.get("vad_aggressiveness", vad_aggressiveness)
        self.vad_enabled = False
        self.vad = webrtcvad.Vad(self.vad_aggressiveness) if self.vad_enabled else None
        self.is_recording = False
        self.audio_data = []
        self.lock = threading.Lock()
        self.output_file_name = "output.wav"
        self.last_speech_time = None
        self.state = 'idle'
        self.auto_vad_enabled = False
        self.vad_thread = None
        self._vad_shutdown_requested = False
        self.silence_timeout = self.settings.get("vad_silence_threshold", 2.0)
        self._was_speaking = False
        self.anti_backchannel_enabled = True
        self.backchannel_duration_threshold = self.settings.get("backchannel_duration_threshold", 0.8)
        self.command_mode_ref = None
        self.llm_interaction_allowed = False
        self.last_vad_action_time = 0.0
        self._audio_already_saved = False
        self._utterance_id = 0

    def toggle_recording(self):
        """
        Toggles the manual recording state between idle, recording, and paused.
        Starts a new recording thread if currently idle.
        """
        with self.lock:
            if self.state == 'idle':
                assert not self._audio_already_saved, "Audio already marked as saved before new recording started."
                self.state = 'recording'
                self.audio_data = []
                self.is_recording = True
                self.last_speech_time = time.time()
                threading.Thread(target=self._record).start()
                logger.info("Recording started.")
                if self.gui_listener:
                    self.gui_listener.update(OverlayEvent.RECORDING_STARTED, {})
            elif self.state == 'recording':
                self.state = 'paused'
                logger.info("Recording paused.")
            elif self.state == 'paused':
                self.state = 'recording'
                self.last_speech_time = time.time()
                logger.info("Recording resumed.")

    def stop_recording(self):
        """
        Stops the current recording and sets the state to idle.
        Notifies the GUI that recording has stopped.
        """
        with self.lock:
            self.is_recording = False
            self.state = 'idle'
            logger.info("Recording stopped.")
            if self.gui_listener:
                self.gui_listener.update(OverlayEvent.RECORDING_STOPPED, {})

    def cancel_recording(self):
        """
        Cancels the current recording, clears buffered audio data, and sets the state to idle.
        Notifies the GUI that recording has stopped.
        """
        with self.lock:
            self.is_recording = False
            self.state = 'idle'
            self.audio_data = []
            logger.info("Recording cancelled.")
            if self.gui_listener:
                self.gui_listener.update(OverlayEvent.RECORDING_STOPPED, {})

    def _record(self):
        """
        Internal method to handle the actual audio recording process.
        It continuously records audio chunks, performs VAD if enabled,
        and buffers the audio data.
        """
        try:
            with sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True).recorder(
                samplerate=self.sample_rate,
                channels=[0, 1],
                blocksize=1024,
                exclusive_mode=False
            ) as mic:
                logger.info("Soundcard recorder started.")
                chunk_size = int(self.sample_rate * self.frame_duration / 1000)
                while self.is_recording:
                    if self.state != 'recording':
                        time.sleep(0.1)
                        continue
                    try:
                        frame = mic.record(numframes=chunk_size)

                        with self.lock:
                            if self.vad_enabled:
                                frame_mono = frame[:, 0] if frame.ndim > 1 else frame
                                frame_16bit = (frame_mono * 32767).astype(np.int16)

                                is_speech = self.vad.is_speech(frame_16bit.tobytes(), self.sample_rate)

                                if is_speech:
                                    self.audio_data.append(frame)
                                    self.last_speech_time = time.time()
                                    if not self._was_speaking:
                                        logger.info("🎙️ Speech detected.")
                                        self._was_speaking = True
                                else:
                                    if self._was_speaking:
                                        logger.info("🔇 Silence detected...")
                                        self._was_speaking = False
                            else:
                                self.audio_data.append(frame)
                                self.last_speech_time = time.time()
                                logger.debug("Recording (VAD disabled).")
                            
                            if self.gui_listener:
                                self.gui_listener.update(OverlayEvent.AUDIO_TICK, {"delta": self.frame_duration / 1000})

                        time.sleep(self.frame_duration / 1000)
                    except Exception as e:
                        logger.error(f"Error recording frame or processing VAD: {e}", exc_info=True)
                        self.is_recording = False
                        self.state = 'idle'
                        break

            logger.info("Soundcard recorder stopped.")
            if self.audio_data and self.state == 'idle':
                logger.debug(f"DEBUG: _record loop terminating. Audio data length before handling: {len(self.audio_data)}")
                self._handle_completed_utterance()
                self.clear_state()
        except Exception as e:
            logger.error(f"Error setting up or running soundcard recorder: {e}")

    def get_audio_bytes(self):
        """
        Retrieves the currently buffered audio data as WAV formatted bytes.

        Returns:
            bytes: WAV formatted audio data, or None if no audio is buffered.
        """
        with self.lock:
            if self.audio_data:
                concatenated_audio = np.concatenate(self.audio_data, axis=0)
                import io
                buffer = io.BytesIO()
                sf.write(buffer, concatenated_audio, self.sample_rate, format='WAV', subtype='PCM_16')
                buffer.seek(0)
                return buffer.getvalue()
            else:
                logger.debug("Audio data is empty in get_audio_bytes.")
            return None

    def _handle_completed_utterance(self):
        """
        Handles a completed audio utterance.
        Applies anti-backchanneling logic, saves the audio, moves it to MemoryBox,
        and dispatches it to the LLM if allowed.
        """
        with self.lock:
            logger.info(f"Handling utterance #{self._utterance_id}")
            if self._audio_already_saved:
                logger.warning("Audio already saved. Skipping duplicate processing.")
                return
            if not self.audio_data:
                logger.warning("Audio buffer is empty. Nothing to process.")
                return
            
            logger.debug("Audio buffer is not empty before concatenation.")

            concatenated_audio = np.concatenate(self.audio_data, axis=0)
            duration = len(concatenated_audio) / self.sample_rate

            if self.anti_backchannel_enabled and duration < self.backchannel_duration_threshold:
                logger.info(f"⏳ Skipping short backchannel audio ({duration:.2f}s < {self.backchannel_duration_threshold}s)")
                self.audio_data = []
                return

            filename = datetime.datetime.now().strftime("%H-%M-%S_audio.wav")
            output_path = self.session.get_audio_path(filename)
            if os.path.exists(output_path):
                logging.warning(f"⚠️ Overwriting existing audio file: {output_path}")
            
            start_write_time = time.perf_counter()
            sf.write(file=output_path, data=concatenated_audio, samplerate=self.sample_rate, format='WAV', subtype='PCM_16')
            end_write_time = time.perf_counter()
            write_duration = end_write_time - start_write_time
            if write_duration > 0.5:
                logger.warning(f"Slow audio write detected: {write_duration:.2f} seconds for {output_path}")
            logger.info(f"Audio saved to {output_path}")
            logger.debug("sf.write() was called.")
            self._audio_already_saved = True
            self._utterance_id += 1

            import io
            buffer = io.BytesIO()
            sf.write(buffer, concatenated_audio, self.sample_rate, format='WAV', subtype='PCM_16')
            buffer.seek(0)

            audio_bytes_for_memory_box = buffer.getvalue()

            self.memory_box.set_audio(audio_bytes_for_memory_box)
            logger.info("Audio data moved to MemoryBox.")

            logger.debug(f"LLM interaction allowed: {self.llm_interaction_allowed}")

            if self.llm_interaction_allowed:
                audio_to_send, images_to_send = self.memory_box.pop_bundle()
                self.executor.submit(self._dispatch_bundle_to_llm_thread, audio=audio_to_send, images=images_to_send, clear_memory_box=False, dispatch_mode="AutoVAD")
                logger.info("Auto-VAD: Audio bundle dispatched to LLM.")
                if self.gui_listener:
                    self.gui_listener.update(OverlayEvent.BUNDLE_SENT, {})
            else:
                logger.info("LLM interaction skipped: not allowed (waiting for Command Mode).")

            self.audio_data = []
            logger.info("Auto-VAD: Temporary audio data cleared after handling completed utterance.")

    def start_auto_vad(self):
        """
        Starts the automatic Voice Activity Detection (VAD) loop.
        If Auto-VAD is already active, it will log a warning and skip.
        """
        with self.lock:
            if self.auto_vad_enabled or (self.vad_thread and self.vad_thread.is_alive()):
                logger.warning("⚠️ Auto-VAD is already active or thread is running. Skipping start.")
                return
            self._vad_shutdown_requested = False
            self.auto_vad_enabled = True
            self.vad_thread = threading.Thread(target=self._auto_vad_loop, daemon=True)
            self.vad_thread.start()
            logger.info("🔁 Auto-VAD started.")
            if self.gui_listener:
                self.gui_listener.update(OverlayEvent.AUTO_VAD_TOGGLED, {"enabled": True})

    def stop_auto_vad(self):
        """
        Stops the automatic Voice Activity Detection (VAD) loop.
        Ensures any active recording is processed before shutdown.
        """
        if self.is_recording:
            logger.info("Auto-VAD stopping: Recording active, handling completed utterance before shutdown.")
            self._handle_completed_utterance()
        
        with self.lock:
            self.auto_vad_enabled = False
            self.is_recording = False
            self._vad_shutdown_requested = True
        
        self.cancel_recording()
        self.clear_state()
        
        if self.vad_thread and self.vad_thread.is_alive():
            if threading.current_thread() != self.vad_thread:
                self.vad_thread.join(timeout=1.0)
                if self.vad_thread.is_alive():
                    logger.warning("⚠️ Auto-VAD thread did not terminate within timeout.")
            else:
                logger.warning("⚠️ Attempted to join VAD thread from itself — skipping join.")
        self.vad = None
        logger.info("🛑 Auto-VAD stopped.")
        if self.gui_listener:
            self.gui_listener.update(OverlayEvent.AUTO_VAD_TOGGLED, {"enabled": False})

    def _auto_vad_loop(self):
        try:
            while self.auto_vad_enabled:
                if self._vad_shutdown_requested:
                    logger.info("Auto-VAD shutdown requested. Exiting loop.")
                    break

                chunk_size = int(self.sample_rate * self.frame_duration / 1000)

                try:
                    with sc.get_microphone(
                        id=str(sc.default_speaker().name),
                        include_loopback=True
                    ).recorder(
                        samplerate=self.sample_rate,
                        channels=[0, 1],          # Use stereo to avoid WASAPI mono bug
                        blocksize=1024,           # Set a stable block size
                        exclusive_mode=False      # Can be set to True for testing
                    ) as mic:
                        logger.info("🎙️ Auto-VAD listening loop started.")

                        while self.auto_vad_enabled:
                            if self._vad_shutdown_requested:
                                logger.info("Auto-VAD shutdown requested. Exiting inner loop.")
                                break

                            frame = mic.record(numframes=chunk_size)
                            frame_mono = frame[:, 0] if frame.ndim > 1 else frame
                            frame_16bit = (frame_mono * 32767).astype(np.int16)

                            if self.vad is None:
                                logger.warning("⚠️ Auto-VAD loop stopped: VAD instance was None.")
                                break

                            is_speech = self.vad.is_speech(frame_16bit.tobytes(), self.sample_rate)

                            if is_speech:
                                if not self.is_recording:
                                    current_time = time.monotonic()
                                    if current_time - self.last_vad_action_time > 0.2:
                                        self.toggle_recording()
                                        logger.info("Auto-VAD: Speech detected. Recording started.")
                                        self.last_vad_action_time = current_time
                                    else:
                                        logger.debug("Auto-VAD: Speech detected, but debouncing start_recording.")

                                self.last_speech_time = time.time()

                                if not self._was_speaking:
                                    logger.info("🎙️ Speech detected.")
                                    self._was_speaking = True

                            else:
                                if self._was_speaking:
                                    logger.info("🔇 Silence detected...")
                                    self._was_speaking = False

                                if self.is_recording and time.time() - self.last_speech_time > self.silence_timeout:
                                    current_time = time.monotonic()
                                    if current_time - self.last_vad_action_time > 0.2:
                                        self.stop_recording()
                                        logger.info("Auto-VAD: Silence timeout reached. Handling completed utterance...")
                                        self._handle_completed_utterance()
                                        self.clear_state() # NEW: Clear state after handling utterance in auto-VAD loop
                                        self.last_vad_action_time = current_time
                                    else:
                                        logger.debug("Auto-VAD: Silence detected, but debouncing stop_recording.")

                            time.sleep(self.frame_duration / 1000)

                except Exception as e:
                    logger.error(f"Error in auto-VAD listening loop: {e}", exc_info=True)
                    self.stop_auto_vad()

        finally:
            with self.lock:
                self.auto_vad_enabled = False
                logger.info("Auto-VAD loop exited. auto_vad_enabled set to False.")



    def toggle_anti_backchannel(self):
        if not self.auto_vad_enabled:
            logger.warning("🔁 Anti-backchannel toggle ignored — Auto-VAD not active.")
            return
        self.anti_backchannel_enabled = not self.anti_backchannel_enabled
        logger.info(
            f"🎚️ Anti-backchanneling {'enabled' if self.anti_backchannel_enabled else 'disabled'}."
        )

    # The process_audio method is no longer needed as its logic has been moved to _handle_completed_utterance
    # Keeping it as a placeholder for now, but it can be removed if no other parts of the code use it.
    def process_audio(self):
        logger.debug("process_audio called, but its logic has been moved to _handle_completed_utterance.")
        pass

    def clear_state(self):
        """
        Resets all relevant recording and VAD-related flags and buffers
        to their initial state.
        """
        with self.lock:
            logger.info("Clearing AudioRecorder state.")
            self.is_recording = False
            self.state = 'idle'
            self.audio_data = []
            self.last_speech_time = None
            self._was_speaking = False
            self._audio_already_saved = False
            self.last_vad_action_time = 0.0
            logger.info("AudioRecorder state cleared.")
            logger.debug("AudioRecorder state cleared.")

    def _dispatch_bundle_to_llm_thread(self, audio=None, images=None, clear_memory_box: bool = False, dispatch_mode: str = "Unknown"):
        """
        Dispatches the audio and/or image bundle to the LLM in a separate thread.

        Args:
            audio (bytes, optional): Audio data in bytes. Defaults to None.
            images (list, optional): List of image data. Defaults to None.
            clear_memory_box (bool, optional): Whether to clear MemoryBox after dispatch. Defaults to False.
            dispatch_mode (str, optional): Describes the dispatch mode (e.g., "AutoVAD", "CommandMode"). Defaults to "Unknown".
        """
        if not audio and not images:
            logger.warning(f"{dispatch_mode} dispatch aborted: empty bundle.")
            return
        logger.info(f"LLM thread: started (mode={dispatch_mode}, clear_memory_box={clear_memory_box})")
        try:
            response = self.llm_dispatcher.send_bundle(audio=audio, images=images)
            logger.info(f"LLM thread: full response:\n{response}")
        except Exception as e:
            logger.error(f"LLM dispatch thread failed: {e}")
        finally:
            if clear_memory_box:
                self.memory_box.clear()
            logger.info("LLM thread: finished")


if __name__ == '__main__':
    logger.info("AudioRecorder __main__ block executed. Requires settings object for full functionality.")

    def get_state(self) -> dict:
        """
        Returns a dictionary containing the current values of key state flags for debugging.

        Returns:
            dict: A dictionary with current state information.
        """
        with self.lock:
            return {
                "auto_vad_enabled": self.auto_vad_enabled,
                "is_recording": self.is_recording,
                "_audio_already_saved": self._audio_already_saved,
                "state": self.state,
                "_vad_shutdown_requested": self._vad_shutdown_requested,
                "last_vad_action_time": self.last_vad_action_time,
                "vad_enabled": self.vad_enabled,
                "audio_data_length": len(self.audio_data),
                "vad_thread_alive": self.vad_thread and self.vad_thread.is_alive()
            }