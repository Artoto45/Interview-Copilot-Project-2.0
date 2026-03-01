"""
Alert Manager
================
Enforces Service Level Objectives (SLOs) such as P95 latency and
cache hit rates for the interview copilot session.
"""

import logging

logger = logging.getLogger("alerting")

class AlertManager:
    def __init__(self):
        self.slos = {
            "p95_latency_ms": 5000,
            "cache_hit_rate": 0.75,
            "error_rate": 0.05
        }
    
    def check_metrics(self, session):
        """Check session metrics against SLOs and alert if breached."""
        if not session.questions:
            return
            
        # P95 latency
        latencies = sorted([q.duration_ms for q in session.questions])
        p95 = latencies[int(len(latencies) * 0.95)]
        
        if p95 > self.slos["p95_latency_ms"]:
            logger.critical(
                f"SLO Breach: P95 {p95:.0f}ms exceeds target "
                f"{self.slos['p95_latency_ms']}ms"
            )
            # Optional: send to Slack or PagerDuty
        
        # Cache hit rate
        if session.cache_hit_rate < self.slos["cache_hit_rate"]:
            logger.warning(
                f"SLO Warning: Cache hit rate {session.cache_hit_rate:.1%} "
                f"below target {self.slos['cache_hit_rate']:.1%}"
            )
