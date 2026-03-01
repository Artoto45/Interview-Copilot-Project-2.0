import asyncio
import base64
import json
import logging
import os
import sys
import wave

# Append project root just in case
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.transcription.deepgram_transcriber import DeepgramTranscriber
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simulator")

async def test_deepgram_isolation():
    from src.knowledge.question_filter import QuestionFilter
    filter_mod = QuestionFilter()

    logger.info("Setting up callbacks...")
    
    async def on_transcript(speaker: str, text: str):
        logger.info(f"CALLBACK RECEIVED [TRANSCRIPT]: {text}")
        if filter_mod.is_interview_question(text):
            logger.info("QUESTION FILTER: PASSED - Triggering AI Response")
        else:
            logger.info("QUESTION FILTER: REJECTED - Noise skipped")
        
    async def on_delta(speaker: str, text: str):
        logger.info(f"CALLBACK RECEIVED [DELTA]: {text}")
        
    async def on_speech_event(speaker: str, event: str):
        logger.info(f"CALLBACK RECEIVED [SPEECH EVENT]: {event}")

    # Initialize transcriber
    transcriber = DeepgramTranscriber(
        on_transcript=on_transcript,
        on_delta=on_delta,
        on_speech_event=on_speech_event,
    )

    audio_queue = asyncio.Queue()
    
    logger.info("Starting Transcriber...")
    await transcriber.start(audio_queue=audio_queue, speaker="interviewer")
    
    import pyttsx3
    import tempfile
    
    logger.info("Generating synthetic 16kHz audio file with pyttsx3...")
    engine = pyttsx3.init()
    temp_wav = tempfile.mktemp(suffix=".wav")
    engine.save_to_file("Hello. This is a very real synthetic test. Please tell me if you can transcribe my words right now.", temp_wav)
    engine.runAndWait()

    # The pyttsx3 output might not be 16kHz mono, but Deepgram Nova-3 is robust enough to try it
    with open(temp_wav, "rb") as f:
        audio_data = f.read()
    
    logger.info("Pumping actual voice audio...")
    chunk_size = 4096
    for i in range(0, len(audio_data), chunk_size):
        await audio_queue.put(audio_data[i:i+chunk_size])
        await asyncio.sleep(0.05)
        
    logger.info("Pumping silence to trigger VAD speech_final...")
    for _ in range(30):
        await audio_queue.put(b"\x00" * 4096)
        await asyncio.sleep(0.05)
    
    logger.info("Stopping Transcriber...")
    await transcriber.stop()
    os.remove(temp_wav)
    logger.info("Simulation finished")

if __name__ == "__main__":
    asyncio.run(test_deepgram_isolation())
