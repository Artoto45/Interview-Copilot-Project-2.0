"""
Simulate Human Reading Behavior
===============================
This runs the full SmartTeleprompter Qt Widget and simulates
a human candidate reading the script back to it at 130 WPM,
with some stutters and pauses.

Run this script to VISUALLY see the new top-anchored 
scrolling logic in action!
"""

import sys
import os
import time
import random
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.teleprompter.qt_display import SmartTeleprompter

SAMPLE_SCRIPT = """Thank you for having me today. I am very excited to discuss how my background in software engineering and cloud infrastructure aligns perfectly with the Senior Backend Developer position at your company. 

Over the past five years, I have specialized in building scalable, high-throughput microservices using Python, Go, and Kubernetes. At my previous startup, I led a team of three engineers to refactor our monolithic legacy application into an event-driven architecture, reducing our latency by forty percent and cutting AWS costs by nearly twenty percent.

I'm particularly drawn to this role because of your team's commitment to open-source technologies and the aggressive roadmap you have for scaling the data pipeline. One of my proudest achievements was designing a similar real-time data ingestion pipeline that handled over ten thousand events per second without dropping a single payload.

I believe my technical skills, combined with my focus on clean code and robust CI/CD practices, would allow me to make an immediate impact on your upcoming platform launch. I'd love to hear more about the specific challenges your engineering team is facing right now.
"""

class HumanSimulator:
    def __init__(self, teleprompter):
        self.tp = teleprompter
        self.words = SAMPLE_SCRIPT.split()
        self.read_index = 0
        self.spoken_buffer = ""
        
        # We will dispatch the events via timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.speak_next_chunk)

    def start(self):
        # Push the full script to the prompter as if the LLM generated it instantly
        print("Uploading script to teleprompter...")
        self.tp._on_text_received(SAMPLE_SCRIPT)
        
        # Simulate the candidate starting to speak 2 seconds later
        print("Candidate will start speaking in 2 seconds...")
        QTimer.singleShot(2000, self.begin_speaking)

    def begin_speaking(self):
        print("Candidate starts speaking...")
        # A human reads ~2.5 words per second
        # We'll pulse every 500ms and read ~1-3 words
        self.timer.start(500)

    def speak_next_chunk(self):
        if self.read_index >= len(self.words):
            print("Candidate finished speaking.")
            self.timer.stop()
            # Close window 3 seconds after finishing
            QTimer.singleShot(3000, QApplication.instance().quit)
            return

        # Read 1 to 3 words
        chunk_size = random.randint(1, 4)
        chunk_words = self.words[self.read_index:self.read_index+chunk_size]
        self.read_index += chunk_size
        
        chunk = " ".join(chunk_words)
        
        # Introduce a "stutter" or slight mistake 10% of the time,
        # but the progress_tracker handles it!
        if random.random() < 0.1:
            chunk = "um, " + chunk + " uh, "
            
        self.spoken_buffer += " " + chunk
        
        # Send text to teleprompter
        self.tp.update_candidate_progress(self.spoken_buffer)
        
        # Print progress to console
        print(f"[{self.read_index}/{len(self.words)}] Spoken: {chunk}")
        print(f"   Scrollbar position: {self.tp.text_edit.verticalScrollBar().value()}")

def run_simulation():
    app = QApplication(sys.argv)
    
    tp = SmartTeleprompter()
    
    simulator = HumanSimulator(tp)
    simulator.start()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    run_simulation()
