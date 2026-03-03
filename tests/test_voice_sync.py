import os
import json
from src.teleprompter.progress_tracker import estimate_char_progress

def test_progress():
    script = (
        "So, basically, I've been working in software engineering for about five years now. "
        "What I really enjoy is building scalable systems that make a real difference."
    )
    
    # Simulate a stream of candidate speech coming from Deepgram
    spoken_chunks = [
        "so basically i've been",
        "so basically dev been working",
        "so basically dev been working in software engineering for",
        "in software engineering for about five years now",
        "five years now what i really enjoy is building",
        "what i really enjoy is building suitable systems that",
        "scalable systems that make a real difference"
    ]
    
    results = {
        "script_length": len(script),
        "steps": []
    }
    
    current_index = 0
    for chunk in spoken_chunks:
        progress = estimate_char_progress(script, chunk)
        current_index = max(current_index, progress)
        
        step_data = {
            "spoken": chunk,
            "progress": progress,
            "index": current_index,
            "read": script[:current_index] if current_index > 0 else ""
        }
        results["steps"].append(step_data)
        
    with open("tests/sync_output.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    test_progress()
