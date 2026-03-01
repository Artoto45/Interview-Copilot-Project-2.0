"""
Session Metrics & Logging
==========================
Tracks interview session metrics including latency, cache hit rates,
and exports them to JSON for observability.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

@dataclass
class QuestionMetrics:
    question_text: str
    question_type: str
    duration_ms: float
    cache_hit: bool
    timestamp: str

@dataclass
class SessionMetrics:
    session_id: str
    start_time: str
    questions: list[QuestionMetrics]
    
    @property
    def avg_latency_ms(self) -> float:
        if not self.questions:
            return 0.0
        return sum(q.duration_ms for q in self.questions) / len(self.questions)
    
    @property
    def cache_hit_rate(self) -> float:
        if not self.questions:
            return 0.0
        hits = sum(1 for q in self.questions if q.cache_hit)
        return hits / len(self.questions)
    
    def save(self, output_path: Path):
        data = {
            "session_id": self.session_id,
            "avg_latency_ms": self.avg_latency_ms,
            "cache_hit_rate": self.cache_hit_rate,
            "questions": [asdict(q) for q in self.questions]
        }
        output_path.write_text(json.dumps(data, indent=2))
