"""
Live Microphone Teleprompter Test
=================================
This script opens the SmartTeleprompter UI and connects your default
microphone directly to Deepgram for live transcription.

It skips the entire OpenAI LLM pipeline, allowing you to instantly 
verify how the teleprompter's UI tracks your voice, manages stutters,
and executes the smooth kinetic scrolling when reading.
"""

import sys
import os
import asyncio
import threading
from PyQt5.QtWidgets import QApplication

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.teleprompter.qt_display import SmartTeleprompter
from src.audio.capture import AudioCaptureAgent
from src.transcription.deepgram_transcriber import DeepgramTranscriber

SAMPLE_SCRIPT = """Thank you for having me today. I am very excited to discuss how my background in software engineering and cloud infrastructure aligns perfectly with the Senior Backend Developer position at your company. 

Over the past five years, I have specialized in building scalable, high-throughput microservices using Python, Go, and Kubernetes. At my previous startup, I led a team of three engineers to refactor our monolithic legacy application into an event-driven architecture, reducing our latency by forty percent and cutting AWS costs by nearly twenty percent.

I'm particularly drawn to this role because of your team's commitment to open-source technologies and the aggressive roadmap you have for scaling the data pipeline. One of my proudest achievements was designing a similar real-time data ingestion pipeline that handled over ten thousand events per second without dropping a single payload.
"""

class LiveMicTestRunner:
    def __init__(self, teleprompter):
        self.tp = teleprompter
        self.audio_agent = None
        self.transcriber = None
        
        self.committed_text = ""
        self.live_text = ""
        
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)

    def start(self):
        # Push sample text to the prompter
        self.tp._on_text_received(SAMPLE_SCRIPT)
        
        # Start background asyncio thread
        self.thread.start()

    def _run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._init_audio_pipeline())
        self.loop.run_forever()

    async def _init_audio_pipeline(self):
        # Start mic capture
        print("Starting AudioCaptureAgent (Microphone)...")
        self.audio_agent = AudioCaptureAgent()
        await self.audio_agent.start()
        
        # Start transcription
        print("Starting DeepgramTranscriber...")
        self.transcriber = DeepgramTranscriber(
            on_transcript=self._on_transcript,
            on_delta=self._on_delta,
            on_speech_event=self._on_speech_event
        )
        
        # Pipe user microphone (candidate) to Deepgram
        await self.transcriber.start(
            audio_queue=self.audio_agent.user_queue, 
            speaker="candidate"
        )
        print("Live Microphone Test Ready. Please start reading the text out loud!")

    async def _on_transcript(self, speaker: str, text: str):
        if self.committed_text:
            self.committed_text += " " + text
        else:
            self.committed_text = text
            
        self.live_text = ""
        self.tp.update_candidate_progress(self.committed_text)
        print(f"[TRANSCRIPT] {text}")

    async def _on_delta(self, speaker: str, text: str):
        self.live_text = text
        current_full = self.committed_text
        if current_full:
            current_full += " " + self.live_text.strip()
        else:
            current_full = self.live_text.strip()
            
        self.tp.update_candidate_progress(current_full)
        print(f"[DELTA] {text}")
        
    async def _on_speech_event(self, speaker: str, event: str):
        pass

def launch_live_test():
    app = QApplication(sys.argv)
    
    tp = SmartTeleprompter()
    tp.show()
    tp.raise_()
    tp.activateWindow()
    
    runner = LiveMicTestRunner(tp)
    runner.start()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    launch_live_test()
