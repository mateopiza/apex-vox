"""Retries only when they can help; parallel chunks keep the timeline in order."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
import requests

from app.config import settings
from app.services import deepgram_service, groq_service
from app.services.audio_engine import AudioChunkInfo
from app.services.groq_service import GroqTranscriptionError, retry_delay


def _chunk(tmp_path: Path, index: int = 0, start: float = 0.0) -> AudioChunkInfo:
    path = tmp_path / f"c{index}.mp3"
    path.write_bytes(b"audio")
    return AudioChunkInfo(
        chunk_index=index, file_path=path, local_start_sec=0.0, local_end_sec=10.0, global_start_sec=start,
        global_end_sec=start + 10.0, source_file_name=f"{index}.mp3", file_sequence_index=index,
    )


class StatusError(Exception):
    def __init__(self, status: int, headers: dict | None = None) -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status
        self.response = SimpleNamespace(headers=headers or {})


def _client(*outcomes: Any) -> SimpleNamespace:
    calls: List[dict] = []
    queue = list(outcomes)

    def create(**kwargs):
        calls.append(kwargs)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return SimpleNamespace(calls=calls, audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))


OK = {"segments": [{"start": 0.0, "end": 1.0, "text": "Hola."}], "text": "Hola."}


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list:
    waited: list = []
    monkeypatch.setattr(groq_service.time, "sleep", waited.append)
    return waited


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422])
def test_requests_that_cannot_succeed_are_not_retried(tmp_path: Path, sleeps: list, status: int) -> None:
    client = _client(StatusError(status))
    with pytest.raises(GroqTranscriptionError):
        groq_service.transcribe_chunk(_chunk(tmp_path), client=client)
    assert len(client.calls) == 1
    assert sleeps == []


@pytest.mark.parametrize("failure", [StatusError(429), StatusError(500), StatusError(503), ConnectionError("down")])
def test_passing_failures_are_retried(tmp_path: Path, sleeps: list, failure: Exception) -> None:
    client = _client(failure, OK)
    assert groq_service.transcribe_chunk(_chunk(tmp_path), client=client)[0]["text"] == "Hola."
    assert len(client.calls) == 2


def test_retry_after_is_respected_and_capped(tmp_path: Path, sleeps: list) -> None:
    client = _client(StatusError(429, {"retry-after": "7"}), StatusError(429, {"retry-after": "9999"}), OK)
    groq_service.transcribe_chunk(_chunk(tmp_path), client=client)
    assert sleeps == [7.0, 60.0]


def test_retry_delay_backs_off_without_a_header() -> None:
    assert retry_delay(1, 500, {}) == 1.0
    assert retry_delay(3, 500, {}) == 4.0
    assert retry_delay(9, 500, {}) == 8.0
    assert retry_delay(9, None, None, cap=6.0) == 6.0
    assert retry_delay(1, 500, {"retry-after": "soon"}) == 1.0
    assert retry_delay(1, 401, {"retry-after": "1"}) is None


def test_sdk_does_not_retry_on_its_own() -> None:
    assert groq_service.get_groq_client("gsk_test").max_retries == 0


def _segment_for(chunk: AudioChunkInfo) -> list:
    return [{"start": 0.5, "end": 1.0, "text": f"Fragmento {chunk.chunk_index}."}]


def test_parallel_chunks_run_at_once_and_stay_in_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "GROQ_PARALLEL_CHUNKS", 3)
    running, peak, lock = [0], [0], threading.Lock()
    prompts = []

    def fake(chunk, model=None, language=None, prompt=None, api_key=None, client=None):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            prompts.append(prompt)
        time.sleep(0.05 * (5 - chunk.chunk_index))  # the first chunks finish last
        with lock:
            running[0] -= 1
        return _segment_for(chunk)

    monkeypatch.setattr(groq_service, "transcribe_chunk", fake)
    chunks = [_chunk(tmp_path, i, start=i * 10.0) for i in range(5)]
    segments = groq_service.transcribe_chunks_sequence(chunks, prompt_hint="Reunión de consejo", api_key="gsk_test")

    assert peak[0] == 3
    assert [s.text for s in segments] == [f"Fragmento {i}." for i in range(5)]
    assert [s.global_start for s in segments] == [i * 10.0 + 0.5 for i in range(5)]
    assert [s.id for s in segments] == list(range(5))
    assert set(prompts) == {"Reunión de consejo"}


def test_one_at_a_time_keeps_context_between_chunks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "GROQ_PARALLEL_CHUNKS", 1)
    prompts = []

    def fake(chunk, model=None, language=None, prompt=None, api_key=None, client=None):
        prompts.append(prompt)
        return _segment_for(chunk)

    monkeypatch.setattr(groq_service, "transcribe_chunk", fake)
    groq_service.transcribe_chunks_sequence([_chunk(tmp_path, i) for i in range(2)], api_key="gsk_test")
    assert prompts == [None, "Fragmento 0."]


def test_a_failed_chunk_fails_the_job_and_cancels_the_rest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "GROQ_PARALLEL_CHUNKS", 2)
    started = []

    def fake(chunk, model=None, language=None, prompt=None, api_key=None, client=None):
        started.append(chunk.chunk_index)
        if chunk.chunk_index == 0:
            raise GroqTranscriptionError("provider down")
        time.sleep(0.2)
        return _segment_for(chunk)

    monkeypatch.setattr(groq_service, "transcribe_chunk", fake)
    with pytest.raises(GroqTranscriptionError):
        groq_service.transcribe_chunks_sequence([_chunk(tmp_path, i) for i in range(8)], api_key="gsk_test")
    time.sleep(0.3)
    assert len(started) < 8


def test_progress_callback_stops_a_parallel_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "GROQ_PARALLEL_CHUNKS", 2)
    monkeypatch.setattr(
        groq_service, "transcribe_chunk", lambda chunk, **kw: _segment_for(chunk)
    )

    def stop(idx, total, message):
        raise TimeoutError("over the limit")

    with pytest.raises(TimeoutError):
        groq_service.transcribe_chunks_sequence(
            [_chunk(tmp_path, i) for i in range(3)], api_key="gsk_test", progress_callback=stop
        )


# Deepgram ------------------------------------------------------------------


def _deepgram_response(status: int, text: str = "{}", headers: dict | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = text.encode()
    response.headers.update(headers or {})
    return response


def _deepgram_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *replies: requests.Response) -> list:
    calls: list = []
    queue = list(replies)
    waited: list = []

    def post(*args, **kwargs):
        calls.append(kwargs)
        return queue.pop(0)

    monkeypatch.setattr(deepgram_service.requests, "post", post)
    monkeypatch.setattr(deepgram_service.time, "sleep", waited.append)
    monkeypatch.setattr(deepgram_service, "get_deepgram_api_key", lambda key=None: "dg")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"audio")
    try:
        result = deepgram_service.call_deepgram_listen(audio)
    except deepgram_service.DeepgramServiceError as exc:
        result = exc
    return [result, calls, waited]


def test_deepgram_does_not_retry_a_bad_key_or_leak_the_body(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result, calls, waited = _deepgram_call(monkeypatch, tmp_path, _deepgram_response(401, "secret detail"))
    assert isinstance(result, deepgram_service.DeepgramServiceError)
    assert len(calls) == 1 and waited == []
    assert "secret detail" not in str(result)


def test_deepgram_retries_rate_limits_with_retry_after(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result, calls, waited = _deepgram_call(
        monkeypatch, tmp_path, _deepgram_response(429, headers={"Retry-After": "5"}), _deepgram_response(200, '{"ok": 1}')
    )
    assert result == {"ok": 1}
    assert len(calls) == 2 and waited == [5.0]
