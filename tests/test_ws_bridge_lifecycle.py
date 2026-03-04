import asyncio
import threading
import time

from src.teleprompter.ws_bridge import TeleprompterBridge


class _NoopTeleprompter:
    def append_text(self, token: str):
        return

    def clear_text(self):
        return

    def update_candidate_progress(self, spoken_text: str, final_pass: bool = False):
        return


async def _fake_connect_loop(self):
    while self._running:
        await asyncio.sleep(0.001)


def _active_bridge_threads() -> list[threading.Thread]:
    return [
        t
        for t in threading.enumerate()
        if t.name == "teleprompter-bridge" and t.is_alive()
    ]


def test_bridge_start_stop_lifecycle_stress(monkeypatch):
    monkeypatch.setattr(
        TeleprompterBridge,
        "_connect_loop",
        _fake_connect_loop,
        raising=True,
    )

    teleprompter = _NoopTeleprompter()
    cycles = 60
    for _ in range(cycles):
        bridge = TeleprompterBridge(
            teleprompter=teleprompter,
            ws_url="ws://127.0.0.1:9999",
        )
        bridge.start()
        time.sleep(0.005)
        assert bridge.is_running
        bridge.stop()
        assert not bridge.is_running
        time.sleep(0.002)

    assert _active_bridge_threads() == []
