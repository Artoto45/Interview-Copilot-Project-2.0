import argparse
import asyncio
import json
import logging
import sys
import threading
from pathlib import Path

import websockets
from PyQt5.QtWidgets import QApplication

# Add parent path to import src
sys.path.append(str(Path(__file__).parent.parent))

from src.teleprompter.qt_display import SmartTeleprompter
from src.teleprompter.ws_bridge import TeleprompterBridge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mock_ws_server")

MOCK_PORT = 8766


class MockPipelineServer:
    """Mock WebSocket server to emulate the main pipeline for standalone testing."""
    
    def __init__(self, mode: str):
        self.mode = mode
        self.clients = set()

    async def ws_handler(self, websocket):
        self.clients.add(websocket)
        logger.info("Teleprompter connected to Mock Server")
        try:
            if self.mode == "demo":
                await self.run_demo()
            elif self.mode == "tracking":
                await self.run_tracking()
            elif self.mode == "interactive":
                await self.run_interactive()
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)

    async def broadcast(self, msg_type: str, **kwargs):
        if not self.clients:
            return
        msg = {"type": msg_type}
        msg.update(kwargs)
        data = json.dumps(msg)
        for ws in self.clients:
            await ws.send(data)

    async def send_token_stream(self, text: str, delay: float = 0.05):
        words = text.split(" ")
        for i, word in enumerate(words):
            token = word + " " if i < len(words) - 1 else word
            await self.broadcast("token", data=token)
            await asyncio.sleep(delay)

    async def run_demo(self):
        await asyncio.sleep(2)
        await self.broadcast("new_question")
        await asyncio.sleep(0.5)
        text = "Hello! I am running in **demo mode**. [PAUSE] This is just a test."
        await self.send_token_stream(text)
        await self.broadcast("response_end")

    async def run_tracking(self):
        await asyncio.sleep(2)
        await self.broadcast("new_question")
        
        script = "This is a test of the voice tracking system. We want to ensure it scrolls correctly."
        await self.send_token_stream(script)
        await self.broadcast("response_end")
        
        await asyncio.sleep(1)
        words = script.split(" ")
        for w in words:
            await self.broadcast("subtitle_delta", speaker="candidate", text=w + " ")
            await asyncio.sleep(0.3)

    async def run_interactive(self):
        loop = asyncio.get_running_loop()
        print("\n=== INTERACTIVE MODE ===")
        print("Type a message to send to the teleprompter.")
        print("Type 'clear' to send a new_question event.")
        print("Type 'q' to quit.\n")
        
        while True:
            text = await loop.run_in_executor(None, input, "Msg: ")
            if text.lower() == 'q':
                break
            if text.lower() == 'clear':
                await self.broadcast("new_question")
                continue
            
            await self.send_token_stream(text)
            await self.broadcast("response_end")

    async def start(self):
        async with websockets.serve(self.ws_handler, "127.0.0.1", MOCK_PORT):
            logger.info(f"Mock server running on ws://127.0.0.1:{MOCK_PORT}")
            logger.info(f"Mode: {self.mode}")
            await asyncio.Future()  # run forever


def run_mock_server(mode: str):
    server = MockPipelineServer(mode)
    asyncio.run(server.start())


def main():
    parser = argparse.ArgumentParser(description="Standalone Teleprompter Runner")
    parser.add_argument(
        "--mode", 
        choices=["demo", "tracking", "interactive"], 
        default="demo",
        help="Mode for the mock WebSocket server"
    )
    args = parser.parse_args()

    # Start the mock server in a background thread
    server_thread = threading.Thread(target=run_mock_server, args=(args.mode,), daemon=True)
    server_thread.start()

    # Create PyQt5 App and Teleprompter
    app = QApplication(sys.argv)
    tp = SmartTeleprompter(wpm=150)
    tp.show()

    # Create and start the WebSocket bridge pointing to the local mock server
    bridge = TeleprompterBridge(teleprompter=tp, ws_url=f"ws://127.0.0.1:{MOCK_PORT}")
    bridge.start()

    # Run Qt event loop
    exit_code = app.exec_()
    
    bridge.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
