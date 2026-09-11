"""Demo scenario 3: Off-by-one loop bug causing IndexError.

This script demonstrates a classic student mistake: looping through an array
using `<= len(items)` instead of `< len(items)` or `range(len(items))`.

To test with Neuron AI:
1. Open this file in your editor or IDE on screen.
2. Say "Hey Neuron" or press Ctrl+Shift+Space.
3. Ask: "Why is my loop crashing with an IndexError?"
4. Neuron will highlight line 19 and explain that indices are 0-indexed.
"""


def process_grades(scores: list[int]) -> list[str]:
    """Calculate letter grades for a list of student scores."""
    results = []

    # BUG HERE: Using `range(len(scores) + 1)` causes an off-by-one IndexError
    # on the final iteration when i == len(scores).
    for i in range(len(scores) + 1):  # <--- OFF-BY-ONE ERROR
        score = scores[i]
        if score >= 90:
            results.append("A")
        elif score >= 80:
            results.append("B")
        elif score >= 70:
            results.append("C")
        else:
            results.append("F")

    return results


if __name__ == "__main__":
    student_scores = [88, 92, 79, 95, 64]
    print("Processing scores:", student_scores)
    # The following call will raise IndexError: list index out of range
    try:
        grades = process_grades(student_scores)
        print("Grades:", grades)
    except IndexError as exc:
        print(f"\n[CRASH REPRODUCED] Caught expected error: {exc}")
        print("Neuron can visually identify this line and explain the fix in real time!")
