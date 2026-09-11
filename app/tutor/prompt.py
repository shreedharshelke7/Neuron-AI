"""Prompt templates and multimodal prompt assembly for Block 3 Tutor Engine."""

from __future__ import annotations

from typing import Optional, Tuple
from app.capture.model import CapturedScreen, SelectedRegion
from app.tutor.model import TutorRequest

SYSTEM_INSTRUCTION = """You are Neuron AI, an intelligent, empathetic, and exceptionally clear multimodal AI tutor assisting a student directly on their computer.

The student is looking at their screen and asking a question. You receive:
1. The student's screen image.
2. Optional details about a specific region highlighted by the student.
3. The student's spoken question (transcribed into text).

Your pedagogical goals:
- Socratic & Insightful: Help the student build intuition and conceptual understanding rather than merely giving passive answers.
- Visually Grounded: Directly reference visual elements (code lines, UI components, diagram nodes, equations, or charts) visible in the screenshot.
- Targeted Visual Guidance: When pointing to specific elements on the screen, produce overlay_actions to guide the student:
  * HIGHLIGHT: target_normalized=[nx, ny, nw, nh] around an element of interest. Optional label.
  * ARROW: target_normalized=[x1, y1, x2, y2] pointing from (x1,y1) to (x2,y2). Optional label.
  * TEXT: target_normalized=[nx, ny, nw, nh], text="note/annotation".
  * CARD: target_normalized=[nx, ny, nw, nh], title="Card Title", text="Body text".
  * EQUATION: target_normalized=[nx, ny, nw, nh], text="LaTeX or formula expression".
  * NONE: action_type="NONE" when no visual guidance is needed.
  All coordinate numbers must be strictly bounded within 0.0 and 1.0.
- Concise Summary: Provide a 1-3 sentence crisp summary in `summary` suitable for quick reading on screen.
- Narration: Provide a friendly, comprehensive, step-by-step spoken explanation in `narration`.
- Follow-up: When appropriate, offer an insightful follow-up question or thought experiment in `follow_up` to verify understanding.

Always adhere to the required structured JSON output schema."""


def extract_image_bytes(capture: Optional[CapturedScreen]) -> Optional[bytes]:
    """Extract JPEG image bytes from CapturedScreen purely in-memory.

    Supports QPixmap, QImage, or raw bytes. Never writes to disk.
    """
    if capture is None or capture.image_data is None:
        return None

    img = capture.image_data

    # If already raw bytes
    if isinstance(img, (bytes, bytearray)):
        return bytes(img)

    # If PySide6 QPixmap or QImage
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QImage, QPixmap

        if isinstance(img, (QPixmap, QImage)):
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            # Save as JPEG with good quality and compressed size
            img.save(buffer, "JPEG", quality=85)
            buffer.close()
            return bytes(byte_array.data())
    except ImportError:
        pass

    return None


def build_user_prompt(
    transcript: str,
    selected_region: Optional[SelectedRegion] = None,
    capture: Optional[CapturedScreen] = None,
) -> str:
    """Construct the textual component of the multimodal user prompt."""
    prompt_lines = [
        f"Student Question: \"{transcript}\"",
    ]

    if selected_region is not None:
        try:
            geom = selected_region.display_geometry or (capture.geometry if capture else None)
            nx, ny, nw, nh = selected_region.to_normalized(geometry=geom)
            prompt_lines.append(
                f"Region of Interest: The student explicitly selected/highlighted this portion of the screen:\n"
                f"Normalized bounding box [nx, ny, nw, nh]: [{nx:.4f}, {ny:.4f}, {nw:.4f}, {nh:.4f}].\n"
                f"Focus your primary pedagogical analysis on what is inside or immediately around this area."
            )
        except Exception:
            prompt_lines.append(
                f"Region of Interest: ({selected_region.x}, {selected_region.y}, "
                f"{selected_region.width}x{selected_region.height}) pixels."
            )

    return "\n\n".join(prompt_lines)
