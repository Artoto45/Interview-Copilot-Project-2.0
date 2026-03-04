import asyncio

import pytest

import main as coordinator


@pytest.mark.asyncio
async def test_fragment_gate_emits_clarification_after_hold(monkeypatch):
    sent_messages = []
    sent_tokens = []
    logged_entries = []

    async def fake_broadcast_message(message: dict):
        sent_messages.append(message)

    async def fake_broadcast_token(token: str):
        sent_tokens.append(token)

    def fake_log(question: str, response: str, q_type: str, metadata=None):
        logged_entries.append({
            "question": question,
            "response": response,
            "type": q_type,
            "metadata": metadata or {},
        })

    monkeypatch.setattr(coordinator, "broadcast_message", fake_broadcast_message)
    monkeypatch.setattr(coordinator, "broadcast_token", fake_broadcast_token)
    monkeypatch.setattr(coordinator, "_log_conversation", fake_log)
    monkeypatch.setattr(coordinator, "FRAGMENT_HOLD_MIN_S", 0.01)
    monkeypatch.setattr(coordinator, "FRAGMENT_HOLD_MAX_S", 0.01)

    # Reset mutable global state used by the gate.
    await coordinator._cancel_pending_fragment()
    old_q = coordinator.pipeline.total_questions
    old_r = coordinator.pipeline.total_responses
    coordinator.pipeline.total_questions = 0
    coordinator.pipeline.total_responses = 0

    try:
        await coordinator._schedule_fragment_gate(
            raw_question="during a challenging period and what tactics you used?",
            normalized_question="during a challenging period and what tactics you used?",
            analysis={
                "reason": "has_question_mark",
                "fragment_reason": "leading_fragment_marker",
            },
        )
        await asyncio.sleep(0.05)

        assert coordinator.pipeline.pending_fragment_payload is None
        assert coordinator.pipeline.pending_fragment_task is None
        assert coordinator.pipeline.total_questions == 1
        assert coordinator.pipeline.total_responses == 1

        assert any(msg.get("type") == "new_question" for msg in sent_messages)
        assert any(msg.get("type") == "response_end" for msg in sent_messages)
        merged_tokens = "".join(sent_tokens).lower()
        assert "only caught part of the question" in merged_tokens
        assert len(logged_entries) == 1
        assert logged_entries[0]["type"] == "fragment_clarification"
    finally:
        coordinator.pipeline.total_questions = old_q
        coordinator.pipeline.total_responses = old_r
        await coordinator._cancel_pending_fragment()
