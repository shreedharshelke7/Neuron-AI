"""Neuron AI Demo Launcher (Block 8).

Helps presenters and judges launch and test the 3 core pedagogical scenarios:
1. Math: Calculus parabola and derivative minimum (f(x) = x^2)
2. PDF: Closed-form formula derivation (sum of squares)
3. Code: Off-by-one indexing error (IndexError)

Usage:
    python demo/run_demo.py [scenario_number]
    python demo/run_demo.py --all
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parent

SCENARIOS = {
    "1": {
        "title": "Math / Calculus — Derivative of f(x) = x²",
        "file": DEMO_ROOT / "math" / "derivative_graph.html",
        "prompt": "What is the derivative of x squared and where is the minimum?",
        "intent": "Explain power rule f'(x)=2x, minimum at (0,0), and slope.",
    },
    "2": {
        "title": "Document / PDF — Sum of Squares Formula",
        "file": DEMO_ROOT / "pdf" / "formula_notes.html",
        "prompt": "Can you explain the formula for the sum of squares on my screen?",
        "intent": "Explain closed-form formula n(n+1)(2n+1)/6 and induction basis.",
    },
    "3": {
        "title": "Coding / Python — Off-By-One IndexError",
        "file": DEMO_ROOT / "coding" / "buggy_loop.py",
        "prompt": "Why is my loop crashing with an IndexError?",
        "intent": "Identify range(len+1) out-of-bounds access and recommend 0-index fix.",
    },
}


def launch_scenario(key: str) -> None:
    scenario = SCENARIOS[key]
    file_path = scenario["file"]
    print("\n" + "=" * 70)
    print(f"LAUNCHING SCENARIO {key}: {scenario['title']}")
    print("=" * 70)
    print(f"Opening context file: {file_path}")
    print(f"\nRecommended voice prompt:")
    print(f"  \"\"{scenario['prompt']}\"\"")
    print(f"\nExpected pedagogical action:")
    print(f"  {scenario['intent']}")
    print("-" * 70)
    print("Activation steps:")
    print("  1. Ensure the opened window is visible on screen.")
    print("  2. Say \"Hey Neuron\" (or press Ctrl+Shift+Space).")
    print("  3. Ask the voice question above.")
    print("  4. Press Escape to dismiss overlay or stop narration at any time.")
    print("=" * 70 + "\n")

    if file_path.suffix == ".html":
        webbrowser.open(file_path.as_uri())
    else:
        if sys.platform == "win32":
            os.startfile(str(file_path))
        else:
            webbrowser.open(file_path.as_uri())


def main() -> int:
    parser = argparse.ArgumentParser(description="Neuron AI Demo Scenario Launcher")
    parser.add_argument("scenario", nargs="?", choices=["1", "2", "3"], help="Scenario number (1, 2, or 3)")
    parser.add_argument("--all", action="store_true", help="Launch all three scenario contexts")
    args = parser.parse_args()

    if args.all:
        for k in ["1", "2", "3"]:
            launch_scenario(k)
        return 0

    if args.scenario:
        launch_scenario(args.scenario)
        return 0

    print("\n=== Neuron AI Demo Scenarios ===")
    for k, v in SCENARIOS.items():
        print(f"  [{k}] {v['title']}")
    print("  [A] All scenarios")
    print("  [Q] Quit")
    choice = input("\nSelect scenario to launch [1/2/3/A/Q]: ").strip().upper()

    if choice in SCENARIOS:
        launch_scenario(choice)
    elif choice == "A":
        for k in ["1", "2", "3"]:
            launch_scenario(k)
    elif choice in ("Q", "EXIT"):
        print("Cancelled.")
        return 0
    else:
        print(f"Invalid choice '{choice}'.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
