import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("metrics.voice_tracking")

class VoiceTrackingMetrics:
    """
    Colector de métricas para medir latencias en Voice Tracking / Teleprompter.
    Mide:
        - Latencia de transcripción
        - Latencia del filtro de preguntas
        - Latencia total del pipeline por utterance
    """

    def __init__(self, session_id: Optional[str] = None):
        if not session_id:
            session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.session_id = session_id
        self.metrics: List[Dict] = []
        self._current_utterance: Dict = {}

    def record_speech_stopped(self):
        """Marca el momento exacto en que VAD detecta que se detuvo el habla."""
        self._current_utterance['speech_stopped_time'] = time.perf_counter()

    def record_transcript_ready(self):
        """Calcula latencia desde que paró de hablar hasta que está listo el transcript final."""
        if 'speech_stopped_time' in self._current_utterance:
            latency = time.perf_counter() - self._current_utterance['speech_stopped_time']
            self._current_utterance['transcription_latency_s'] = round(latency, 4)

    def record_filter_latency(self, duration_s: float):
        """Registra el tiempo que tardó el QuestionFilter."""
        self._current_utterance['filter_latency_s'] = round(duration_s, 4)

    def record_pipeline_end(self, total_duration_s: float, question_text: str):
        """Registra latencia total y guarda el utterance en el historial."""
        self._current_utterance['total_pipeline_latency_s'] = round(total_duration_s, 4)
        self._current_utterance['question'] = question_text
        self._current_utterance['timestamp'] = datetime.now().isoformat()
        
        self.metrics.append(self._current_utterance.copy())
        self._current_utterance.clear()

    def reset_utterance(self):
        """Limpia estado temporal si se cancela el procesamiento."""
        self._current_utterance.clear()

    def export_to_json(self) -> str:
        """Exporta las métricas recopiladas a un archivo JSON."""
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True, parents=True)
        filepath = log_dir / f"voice_tracking_{self.session_id}.json"
        
        payload = {
            "session_id": self.session_id,
            "exported_at": datetime.now().isoformat(),
            "total_utterances": len(self.metrics),
            "metrics": self.metrics
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Métricas exportadas a: {filepath}")
        return str(filepath)
