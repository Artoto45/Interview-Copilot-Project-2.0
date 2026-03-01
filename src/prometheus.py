"""
Prometheus Metrics Export
=========================
Exports real-time metrics for prometheus scraping.
"""

from prometheus_client import Counter, Gauge, Histogram, start_http_server
import logging

logger = logging.getLogger("prometheus_export")

# Metrics definitions
response_latency = Histogram(
    'response_latency_ms', 
    'Response generation latency in milliseconds'
)
cache_hit_rate = Gauge(
    'cache_hit_rate', 
    'Current session prompt cache hit rate'
)
question_count = Counter(
    'questions_total', 
    'Total questions processed'
)

def start_metrics_server(port: int = 8000):
    """Start the Prometheus metrics exporter on the given port."""
    try:
        start_http_server(port)
        logger.info(f"Prometheus metrics server started on port {port}")
    except Exception as e:
        logger.warning(f"Failed to start Prometheus metrics server: {e}")
