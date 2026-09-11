# Neuron AI — Live Demonstration Guide & Operator Runbook

> **Operator instructions for presenting Neuron AI to judges, investors, and educators.**

---

## 1. Quick Start / Pre-Flight Checklist

Before presenting live, run through this 60-second checklist:

1. **Verify Environment Readiness:**
   ```powershell
   .\run_neuron.ps1 -CheckReadiness
   ```
   Ensure all critical checks display `[PASS]`. If cloud API keys are not configured or the network is unstable, fallback mode will automatically protect the demo.

2. **Select Demo Execution Mode:**
   - **`auto` (Default & Recommended):** Attempts live Gemini reasoning first; seamlessly recovers with deterministic local scenarios if network or quota limits fail.
   - **`fallback` (100% Offline):** Zero network calls. Pure deterministic local demo execution. Ideal for stage presentations with flaky WiFi.
   - **`live`:** Direct Gemini API calls only.

3. **Launch Neuron Application:**
   ```powershell
   # Option A: Normal launch with auto mode
   .\run_neuron.ps1

   # Option B: Guaranteed 100% offline demo mode
   .\run_neuron.ps1 -DemoMode fallback

   # Option C: Launch directly using Windows batch file
   run_neuron.bat
   ```

---

## 2. Hardware & Setup Tips for Presenters

* **Microphone:** Use your built-in laptop mic or a standard headset.
* **Display Resolution:** Works at any resolution and scale factor (100%, 125%, 150%, 200%).
* **Audio Output:** Ensure system speakers or headphones are unmuted.
* **Screen Placement:** Keep your demo window (browser or code editor) visible on the primary display.

---

## 3. Step-by-Step Scenario Presentation Script

### Demo 1: Calculus ($f(x) = x^2$)
1. **Launch Context:**
   ```powershell
   python demo/run_demo.py 1
   ```
   *(This opens `demo/math/derivative_graph.html` in your default browser).*
2. **Explain the Scene to the Audience:**
   > *"Imagine a student studying calculus late at night. They're looking at this parabola graph and trying to remember how to find the minimum."*
3. **Trigger Neuron:**
   - Say: **"Hey Neuron"** *(or press `Ctrl+Shift+Space`)*
   - Status transitions to `LISTENING`.
4. **Speak the Question:**
   - Say clearly: **"What is the derivative of x squared and where is the minimum?"**
5. **Observe Automatic Workflow:**
   - Neuron automatically detects you stopped speaking (`TRANSCRIBING` → `THINKING`).
   - The HUD overlay highlights the equation $f(x) = x^2$ with a bounding box and points an arrow to $(0,0)$.
   - ElevenLabs voice speaks the mathematical explanation.
6. **Dismiss:**
   - Press **`Escape`**. The overlay vanishes immediately, and speech halts.

---

### Demo 2: Discrete Math Notes (Sum of Squares PDF)
1. **Launch Context:**
   ```powershell
   python demo/run_demo.py 2
   ```
2. **Present to Audience:**
   > *"Now the student switches to a discrete mathematics PDF with a dense theorem and proof."*
3. **Trigger:**
   - Say: **"Hey Neuron"** *(or press `Ctrl+Shift+Space`)*
4. **Speak:**
   - **"Can you explain the formula for the sum of squares on my screen?"**
5. **Observe:**
   - Overlay renders focus box around the formula and displays an induction step card while narrating the closed-form theorem.
6. **Dismiss:**
   - Press **`Escape`**.

---

### Demo 3: Coding Bug (Python IndexError)
1. **Launch Context:**
   ```powershell
   python demo/run_demo.py 3
   ```
2. **Present to Audience:**
   > *"Finally, the student is writing code in Python and encounters a runtime crash."*
3. **Trigger:**
   - Say: **"Hey Neuron"** *(or press `Ctrl+Shift+Space`)*
4. **Speak:**
   - **"Why is my loop crashing with an IndexError?"**
5. **Observe:**
   - Neuron identifies `range(len(scores) + 1)` and highlights the offending line with an explanation of 0-based indexing and the fix.
6. **Dismiss:**
   - Press **`Escape`**.

---

## 4. Keybinding & Controls Reference

| Input Trigger | Action | Behavior |
| :--- | :--- | :--- |
| **"Hey Neuron"** | Wake Word | Hands-free activation from IDLE state. |
| **`Ctrl+Shift+Space`** | Global Hotkey | Immediate activation from IDLE; stops recording during LISTENING. |
| **`Escape`** | Global Dismissal | Instantly dismisses overlay, cancels active workers, and silences TTS audio. |

---

## 5. Troubleshooting & FAQ

* **Q: Microphone didn't hear "Hey Neuron"?**  
  *A:* Press `Ctrl+Shift+Space` instead. The hotkey trigger is 100% deterministic and connects to the exact same pipeline.

* **Q: Conference WiFi is down or slow?**  
  *A:* Set `NEURON_DEMO_MODE=fallback` in `.env` or run `.\run_neuron.ps1 -DemoMode fallback`. Neuron will execute all 3 scenarios completely offline with instant latency and zero cloud calls.

* **Q: How do I inspect performance metrics?**  
  *A:* The in-memory `MetricsCollector` logs diagnostic events at `DEBUG` and `INFO` levels. Use `scripts/check_readiness.py` to inspect runtime configuration.
