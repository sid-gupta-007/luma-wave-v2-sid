from __future__ import annotations

import threading

import numpy as np
import pyaudiowpatch as pyaudio

FFT_SIZE = 4096
BUFFER_SIZE = 4096


class AudioEngine:
    """Captures a selected WASAPI output's loopback signal without recording a mic."""

    def __init__(self) -> None:
        self.pa: pyaudio.PyAudio | None = None
        self.stream = None
        self.device_label = "Not started"
        self.error = ""
        self.sample_rate = 48000
        self.channels = 2
        self._samples = np.zeros(FFT_SIZE, dtype=np.float32)
        self._lock = threading.Lock()

    @staticmethod
    def loopback_devices() -> list[dict]:
        pa = pyaudio.PyAudio()
        try:
            return [dict(item) for item in pa.get_loopback_device_info_generator()]
        finally:
            pa.terminate()

    def start(self, requested_device: str) -> None:
        self.stop()
        self.error = ""
        self.pa = pyaudio.PyAudio()
        try:
            devices = [dict(item) for item in self.pa.get_loopback_device_info_generator()]
            if not devices:
                raise RuntimeError("No WASAPI loopback devices were found.")
            chosen = next((d for d in devices if str(d["index"]) == requested_device), None)
            if chosen is None:
                chosen = dict(self.pa.get_default_wasapi_loopback())
            self.sample_rate = int(chosen.get("defaultSampleRate", 48000))
            self.channels = max(1, int(chosen.get("maxInputChannels", 2)))
            self.device_label = chosen["name"].replace(" [Loopback]", "")
            self.stream = self.pa.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=chosen["index"],
                frames_per_buffer=BUFFER_SIZE,
                stream_callback=self._callback,
            )
            self.stream.start_stream()
        except Exception as exc:
            self.error = f"Audio unavailable: {exc}"
            self.stop(keep_error=True)

    def _callback(self, data, frame_count, time_info, status):
        try:
            values = np.frombuffer(data, dtype=np.float32)
            if self.channels > 1:
                values = values.reshape(-1, self.channels).mean(axis=1)
            with self._lock:
                self._samples = np.concatenate((self._samples, values))[-FFT_SIZE:]
        except Exception as exc:
            self.error = f"Audio callback failed: {exc}"
        return (None, pyaudio.paContinue)

    def spectrum(self, bands: int) -> np.ndarray:
        with self._lock:
            samples = self._samples.copy()
        if not np.any(samples):
            return np.zeros(bands, dtype=np.float32)
        fft = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
        frequencies = np.fft.rfftfreq(len(samples), 1 / self.sample_rate)
        edges = np.geomspace(40, min(16000, self.sample_rate / 2), bands + 1)
        values = np.zeros(bands, dtype=np.float32)
        for index in range(bands):
            region = fft[(frequencies >= edges[index]) & (frequencies < edges[index + 1])]
            if len(region):
                values[index] = float(np.log1p(region.max()) / 8.2)
        return np.clip(values, 0, 1)

    def stop(self, keep_error: bool = False) -> None:
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
        if self.pa:
            try:
                self.pa.terminate()
            except Exception:
                pass
        self.stream = self.pa = None
        if not keep_error:
            self.error = ""


