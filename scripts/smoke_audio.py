"""Manual developer smoke test for Block 2 microphone capture.

Verifies real hardware microphone access, in-memory buffering, and safe metadata.
Does NOT persist audio, play audio, or perform STT.
"""

from __future__ import annotations

from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.audio.errors import AudioError
from app.audio.recorder import SoundDeviceAudioCaptureService


def run_smoke_test() -> int:
    """Execute interactive hardware microphone smoke test."""
    print("=" * 60)
    print("NEURON AI — BLOCK 2 MICROPHONE CAPTURE SMOKE TEST")
    print("=" * 60)
    print("This development tool tests real Windows microphone capture.")
    print("Guarantees:")
    print("  - Microphone opens ONLY during explicit recording window")
    print("  - Audio is held ephemeral in memory (NO disk files)")
    print("  - NO raw audio bytes logged or printed")
    print("  - NO STT performed")
    print("-" * 60)

    try:
        input("Press [Enter] to start 3-second recording (or Ctrl+C to abort)... ")
    except (KeyboardInterrupt, EOFError):
        print("\nSmoke test cancelled.")
        return 0

    service = SoundDeviceAudioCaptureService()
    print("\n[1/3] Initialized SoundDeviceAudioCaptureService (mic is CLOSED)")
    assert not service.is_recording, "Service must not record before start_recording()"

    try:
        print("[2/3] Calling start_recording() — please speak into microphone...")
        service.start_recording()

        for remaining in (3, 2, 1):
            print(f"      Recording... {remaining}s remaining", flush=True)
            time.sleep(1.0)

        print("[3/3] Calling stop_recording()...")
        result = service.stop_recording()

        print("\n" + "=" * 60)
        print("RECORDING SUCCESSFUL — SAFE METADATA:")
        print(f"  recording succeeded : True")
        print(f"  duration            : {result.duration_seconds:.3f} s")
        print(f"  sample rate         : {result.sample_rate} Hz")
        print(f"  channels            : {result.channels}")
        print(f"  sample width        : {result.sample_width} bytes ({result.encoding})")
        print(f"  byte count          : {result.byte_count} bytes")
        print(f"  in-memory only      : True")
        print(f"  is_empty            : {result.is_empty}")
        print("=" * 60)
        return 0

    except AudioError as err:
        print(f"\n[ERROR] Audio error encountered: {type(err).__name__}: {err}")
        service.cancel_recording()
        return 1
    except Exception as exc:
        print(f"\n[ERROR] Unexpected error: {type(exc).__name__}: {exc}")
        service.cancel_recording()
        return 1


if __name__ == "__main__":
    sys.exit(run_smoke_test())
