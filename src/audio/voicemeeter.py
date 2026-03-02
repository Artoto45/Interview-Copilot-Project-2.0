"""
Voicemeeter Banana — Configuration Helper
==========================================
Provides utilities to verify and configure Voicemeeter Banana
for dual-channel audio routing:
    - Hardware Input 1 → Bus B1 (candidate microphone)
    - Virtual Input 1  → Bus B2 (interviewer / system audio)

Format: 16 kHz, 16-bit Mono (avoids re-sampling latency).
Recommended drivers: WDM or KS (lower latency than MME).
"""

import logging
import subprocess
from typing import Optional

try:
    import sounddevice as sd
except (ImportError, OSError):
    class _SoundDeviceStub:
        """Stub to keep module importable when PortAudio is unavailable."""

        @staticmethod
        def query_devices(*args, **kwargs):
            raise OSError("PortAudio library not found")

    sd = _SoundDeviceStub()

logger = logging.getLogger("audio.voicemeeter")


def _sounddevice_available() -> bool:
    try:
        sd.query_devices()
        return True
    except Exception:
        return False


class VoicemeeterConfig:
    """
    Helper to detect and validate Voicemeeter Banana configuration.

    This does NOT control Voicemeeter directly (that would require
    the Voicemeeter Remote API / COM interface).  Instead, it validates
    that the expected audio devices are present and correctly configured.
    """

    EXPECTED_DEVICES = {
        "user": "VoiceMeeter Out B1",
        "interviewer": "VoiceMeeter Out B2",
    }

    REQUIRED_SAMPLE_RATE = 16000
    REQUIRED_CHANNELS = 1

    @classmethod
    def check_installation(cls) -> dict:
        """
        Check if Voicemeeter Banana appears to be installed and running.

        Returns a status dict with details about each expected device.
        """
        result = {
            "installed": False,
            "devices_found": {},
            "warnings": [],
            "recommendations": [],
        }

        if not _sounddevice_available():
            result["warnings"].append(
                "sounddevice/PortAudio not available. Cannot inspect local audio devices."
            )
            return result

        all_devices = sd.query_devices()
        device_names = [d["name"] for d in all_devices]

        # Check for Voicemeeter devices
        for role, expected_name in cls.EXPECTED_DEVICES.items():
            found = any(
                expected_name.lower() in name.lower()
                for name in device_names
            )
            result["devices_found"][role] = {
                "expected": expected_name,
                "found": found,
            }
            if found:
                result["installed"] = True

        # Warnings if partially configured
        user_found = result["devices_found"]["user"]["found"]
        int_found = result["devices_found"]["interviewer"]["found"]

        if user_found and not int_found:
            result["warnings"].append(
                "Voicemeeter detected but Bus B2 (interviewer) not found. "
                "Ensure Virtual Input 1 is routed to Bus B2."
            )
        elif not user_found and not int_found:
            result["warnings"].append(
                "Voicemeeter Banana not detected. "
                "Audio will fall back to default system microphone."
            )
            result["recommendations"].extend([
                "1. Download Voicemeeter Banana from vb-audio.com",
                "2. Route Hardware Input 1 → Bus B1 (your microphone)",
                "3. Route Virtual Input 1 (VAIO) → Bus B2 (system audio)",
                "4. Set all to 16 kHz, 16-bit Mono",
                "5. Use WDM or KS drivers (not MME) for lower latency",
            ])

        return result

    @classmethod
    def get_optimal_settings(cls) -> dict:
        """
        Return recommended Voicemeeter settings for optimal performance.
        """
        return {
            "routing": {
                "Hardware Input 1": "Bus B1 (Candidate Microphone)",
                "Virtual Input 1 (VAIO)": "Bus B2 (Interviewer Audio)",
            },
            "format": {
                "sample_rate": "16000 Hz",
                "bit_depth": "16-bit",
                "channels": "Mono",
            },
            "drivers": {
                "recommended": "WDM or KS",
                "avoid": "MME (adds latency)",
            },
            "latency_tips": [
                "Set buffer size to 256-512 samples in Voicemeeter",
                "Use WDM-preferred drivers",
                "Close unnecessary audio apps to avoid conflicts",
                "Run Voicemeeter as administrator for best performance",
            ],
        }

    @classmethod
    def print_diagnostic(cls):
        """Print a formatted diagnostic report to the console."""
        status = cls.check_installation()

        print("\n" + "=" * 55)
        print("  VOICEMEETER BANANA — Diagnostic Report")
        print("=" * 55)

        for role, info in status["devices_found"].items():
            icon = "✓" if info["found"] else "✗"
            print(f"  {icon}  {role.upper():14s} → {info['expected']}")

        if status["warnings"]:
            print("\n  ⚠  Warnings:")
            for w in status["warnings"]:
                print(f"     {w}")

        if status["recommendations"]:
            print("\n  📋 Setup Guide:")
            for r in status["recommendations"]:
                print(f"     {r}")

        print()

        # List all input devices
        print("  Available Input Devices:")
        if not _sounddevice_available():
            print("    (sounddevice/PortAudio not available in this environment)")
            print("=" * 55 + "\n")
            return

        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                print(
                    f"    [{idx:2d}] {dev['name']} "
                    f"(ch={dev['max_input_channels']}, "
                    f"rate={int(dev['default_samplerate'])})"
                )
        print("=" * 55 + "\n")
