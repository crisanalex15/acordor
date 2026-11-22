"""Captura microfonului într-un ring buffer NumPy, fără să blocheze interfața."""

from __future__ import annotations

from threading import Lock

import numpy as np
import sounddevice as sd
from numpy.typing import NDArray

# Dispozitive pe care PortAudio le raportează ca input, dar nu sunt microfoane.
_NOT_A_MIC: tuple[str, ...] = (
    "mapper",
    "primary sound",
    "stereo mix",
    "pc speaker",
    "what u hear",
    "output",
    "speaker",
    "headphone",
    "steam streaming",
)


def _is_microphone(name: str) -> bool:
    lowered = name.lower()
    return not any(token in lowered for token in _NOT_A_MIC)


def list_input_devices() -> list[tuple[int, str]]:
    """
    Microfoanele reale, fiecare o singură dată.

    Pe Windows, PortAudio listează același dispozitiv pe MME, DirectSound,
    WASAPI și WDM-KS. Păstrăm doar WASAPI (API-ul modern, latență mică).
    """
    try:
        devices = sd.query_devices()
        apis = sd.query_hostapis()
    except OSError:
        return []
    wasapi = next((i for i, api in enumerate(apis) if "WASAPI" in str(api["name"])), None)
    host_id = wasapi if wasapi is not None else 0

    found: list[tuple[int, str]] = []
    seen: set[str] = set()
    for index, info in enumerate(devices):
        if int(info["hostapi"]) != host_id:
            continue
        if int(info["max_input_channels"]) <= 0 or int(info["max_output_channels"]) > 0:
            continue
        name = str(info["name"]).strip()
        if not name or not _is_microphone(name):
            continue
        key = "".join(ch for ch in name.lower() if ch.isalnum())
        if key in seen:
            continue
        seen.add(key)
        found.append((index, name))
    return found


def device_sample_rate(device_id: int | None) -> int:
    """
    Rata nativă a dispozitivului.

    WASAPI refuză 44100 Hz dacă mixerul Windows rulează la 48000 (PaErrorCode −9997),
    deci folosim exact rata raportată de dispozitiv.
    """
    try:
        rate = int(round(float(sd.query_devices(device_id, kind="input")["default_samplerate"])))
    except (OSError, ValueError, TypeError):
        rate = 48000
    return rate if rate > 0 else 48000


def _as_device_index(value: object) -> int | None:
    """sounddevice poate da int, None, −1 sau o pereche (input, output)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, np.integer)):
        index = int(value)
        return None if index < 0 else index
    return None


def default_input_device_id(inputs: list[tuple[int, str]]) -> int | None:
    """Microfonul implicit din Windows, căutat în lista filtrată `inputs`."""
    if not inputs:
        return None
    device = sd.default.device
    if hasattr(device, "input"):
        raw: object = device.input
    elif isinstance(device, (list, tuple)) and device:
        raw = device[0]
    else:
        raw = device

    index = _as_device_index(raw)
    ids = {item[0] for item in inputs}
    if index in ids:
        return index
    if index is not None:
        # implicitul e pe alt host API (de obicei MME) — îl căutăm după nume
        try:
            system_name = str(sd.query_devices(index)["name"]).strip().lower()
        except (OSError, ValueError):
            system_name = ""
        for device_id, label in inputs:
            if system_name and system_name in label.lower():
                return device_id
    return inputs[0][0]


def _raw_wasapi_settings(device_id: int | None) -> object | None:
    """
    Setări WASAPI în modul „raw”: fără procesarea audio a Windows-ului.

    Multe laptopuri (Intel Smart Sound, Realtek) aplică implicit noise suppression
    pe microfon. Filtrul tratează o notă ținută ca zgomot staționar și o atenuează
    până aproape de liniște (măsurat: −112 dB normal vs −66 dB raw, pe același
    microfon). Un tuner are nevoie de semnalul brut.

    sounddevice nu expune opțiunea, așa că o setăm direct în structura
    PaWasapiStreamInfo. Dacă API-ul intern lipsește, întoarcem None (mod normal).
    """
    try:
        info = sd.query_devices(device_id, kind="input")
        if "WASAPI" not in str(sd.query_hostapis(int(info["hostapi"]))["name"]):
            return None
        settings = sd.WasapiSettings()
        settings._streaminfo.streamOption = sd._lib.eStreamOptionRaw  # noqa: SLF001
        return settings
    except (AttributeError, OSError, ValueError, TypeError):
        return None


class AudioCapture:
    """
    Stream de intrare mono. Callback-ul (pe thread-ul PortAudio) doar copiază
    eșantioanele în buffer; toată analiza se face pe thread-ul principal.
    """

    def __init__(self, device: int | None = None, buffer_seconds: float = 1.0) -> None:
        self.device_id = device
        self.sample_rate = device_sample_rate(device)
        self._buffer_seconds = buffer_seconds
        self._lock = Lock()
        self._buffer: NDArray[np.float32] = np.zeros(1, dtype=np.float32)
        self._write_index = 0
        self._frames_written = 0
        self._stream: sd.InputStream | None = None
        self.raw_mode = False
        self._allocate_buffer()

    @property
    def running(self) -> bool:
        return self._stream is not None

    @property
    def frames_written(self) -> int:
        """Contor total de eșantioane primite — util ca să știm dacă a venit audio nou."""
        return self._frames_written

    def _allocate_buffer(self) -> None:
        with self._lock:
            self._buffer = np.zeros(max(1, int(self.sample_rate * self._buffer_seconds)), dtype=np.float32)
            self._write_index = 0

    def _on_audio(self, indata: NDArray[np.float32], frames: int, _time: object, _status: object) -> None:
        mono = indata.mean(axis=1) if indata.ndim > 1 else indata
        n = mono.shape[0]
        with self._lock:
            cap = self._buffer.size
            if n >= cap:
                self._buffer[:] = mono[-cap:]
                self._write_index = 0
            else:
                idx = self._write_index
                first = min(n, cap - idx)
                self._buffer[idx : idx + first] = mono[:first]
                if n > first:
                    self._buffer[: n - first] = mono[first:]
                self._write_index = (idx + n) % cap
            self._frames_written += n

    def start(self) -> None:
        if self._stream is not None:
            return
        self.sample_rate = device_sample_rate(self.device_id)
        self._allocate_buffer()
        settings = _raw_wasapi_settings(self.device_id)
        try:
            stream = self._open(settings)
        except sd.PortAudioError:
            if settings is None:
                raise
            settings = None
            stream = self._open(None)  # dispozitivul nu acceptă modul raw
        self.raw_mode = settings is not None
        stream.start()
        self._stream = stream

    def _open(self, settings: object | None) -> sd.InputStream:
        return sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device_id,
            callback=self._on_audio,
            extra_settings=settings,
        )

    def stop(self) -> None:
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None

    def set_device(self, device_id: int) -> None:
        """Repornește stream-ul pe alt microfon."""
        self.stop()
        self.device_id = device_id
        self.start()

    def get_window(self, n_samples: int) -> NDArray[np.float32]:
        """Ultimele `n_samples` eșantioane, în ordine cronologică."""
        with self._lock:
            buf = self._buffer
            n_samples = min(n_samples, buf.size)
            start = (self._write_index - n_samples) % buf.size
            if start + n_samples <= buf.size:
                return buf[start : start + n_samples].copy()
            return np.concatenate((buf[start:], buf[: n_samples - (buf.size - start)]))
