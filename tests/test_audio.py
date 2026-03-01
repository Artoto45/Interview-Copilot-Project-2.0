"""
Test — Audio Capture Module
==============================
Tests for AudioCaptureAgent with mocked sounddevice.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.audio.capture import AudioCaptureAgent


class TestAudioCaptureAgent:
    """Tests for AudioCaptureAgent."""

    def test_init_defaults(self):
        """Agent initializes with correct defaults."""
        agent = AudioCaptureAgent()
        assert agent.sample_rate == 16000
        assert agent.chunk_ms == 100
        assert agent.blocksize == 1600  # 16000 * 100 / 1000
        assert not agent.is_running

    def test_init_custom(self):
        """Agent accepts custom parameters."""
        agent = AudioCaptureAgent(
            device_user="TestDevice1",
            device_interviewer="TestDevice2",
            sample_rate=48000,
            chunk_ms=200,
        )
        assert agent.device_user == "TestDevice1"
        assert agent.device_interviewer == "TestDevice2"
        assert agent.sample_rate == 48000
        assert agent.blocksize == 9600  # 48000 * 200 / 1000

    @patch("src.audio.capture.sd.query_devices")
    def test_resolve_device_found(self, mock_query):
        """Device resolution finds matching device."""
        mock_query.return_value = [
            {"name": "VoiceMeeter Out B1 (Virtual)", "max_input_channels": 2},
            {"name": "Microphone (Realtek)", "max_input_channels": 1},
        ]
        agent = AudioCaptureAgent()
        idx = agent._resolve_device("VoiceMeeter Out B1")
        assert idx == 0

    @patch("src.audio.capture.sd.query_devices")
    def test_resolve_device_not_found(self, mock_query):
        """Device resolution returns None when not found."""
        mock_query.return_value = [
            {"name": "Microphone (Realtek)", "max_input_channels": 1},
        ]
        agent = AudioCaptureAgent()
        idx = agent._resolve_device("VoiceMeeter Out B1")
        assert idx is None

    @patch("src.audio.capture.sd.query_devices")
    def test_list_available_devices(self, mock_query):
        """Lists only input devices."""
        mock_query.return_value = [
            {"name": "Mic1", "max_input_channels": 1, "default_samplerate": 44100},
            {"name": "Speaker", "max_input_channels": 0, "default_samplerate": 48000},
            {"name": "Mic2", "max_input_channels": 2, "default_samplerate": 16000},
        ]
        devices = AudioCaptureAgent.list_available_devices()
        assert len(devices) == 2
        assert devices[0]["name"] == "Mic1"
        assert devices[1]["name"] == "Mic2"

    def test_callback_user_puts_to_queue(self):
        """User callback puts data into user queue."""
        agent = AudioCaptureAgent()
        test_data = b"\x00\x01\x02\x03"
        agent._cb_user(test_data, 4, None, None)
        assert not agent.user_queue.empty()
        chunk = agent.user_queue.get_nowait()
        assert chunk == test_data

    def test_callback_interviewer_puts_to_queue(self):
        """Interviewer callback puts data into int queue."""
        agent = AudioCaptureAgent()
        test_data = b"\x04\x05\x06\x07"
        agent._cb_interviewer(test_data, 4, None, None)
        assert not agent.int_queue.empty()
        chunk = agent.int_queue.get_nowait()
        assert chunk == test_data


class TestVoicemeeterConfig:
    """Tests for VoicemeeterConfig helper."""

    @patch("src.audio.voicemeeter.sd.query_devices")
    def test_check_installation_not_found(self, mock_query):
        """Reports not installed when devices missing."""
        from src.audio.voicemeeter import VoicemeeterConfig

        mock_query.return_value = [
            {"name": "Microphone (Realtek)", "max_input_channels": 1},
        ]
        status = VoicemeeterConfig.check_installation()
        assert not status["installed"]
        assert len(status["warnings"]) > 0
        assert len(status["recommendations"]) > 0

    @patch("src.audio.voicemeeter.sd.query_devices")
    def test_check_installation_found(self, mock_query):
        """Reports installed when devices present."""
        from src.audio.voicemeeter import VoicemeeterConfig

        mock_query.return_value = [
            {"name": "VoiceMeeter Out B1", "max_input_channels": 2},
            {"name": "VoiceMeeter Out B2", "max_input_channels": 2},
        ]
        status = VoicemeeterConfig.check_installation()
        assert status["installed"]
        assert status["devices_found"]["user"]["found"]
        assert status["devices_found"]["interviewer"]["found"]

    def test_optimal_settings(self):
        """Returns expected optimal settings."""
        from src.audio.voicemeeter import VoicemeeterConfig

        settings = VoicemeeterConfig.get_optimal_settings()
        assert "routing" in settings
        assert "format" in settings
        assert settings["format"]["sample_rate"] == "16000 Hz"
