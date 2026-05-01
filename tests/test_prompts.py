from app.prompts import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_CALCULATOR,
    _trim_history_to_budget,
    build_calculator_messages,
    build_chat_messages,
    build_retrieval_query,
)


def test_system_prompt_states_role_and_disclaimer() -> None:
    lower = SYSTEM_PROMPT.lower()
    assert "interpreter" in lower
    assert "not a clinician" in lower or "not a doctor" in lower
    assert "whitebook" in lower
    assert "markdown" in lower


def test_build_retrieval_query_expands_short_followups() -> None:
    history = [
        {"role": "user", "content": "dosage for procainamide in WPW"},
        {"role": "assistant", "content": "Administer 20 mg/min until 17 mg/kg total dose."},
    ]
    expanded = build_retrieval_query("how should I administer it?", history)
    assert "Earlier user question" in expanded
    assert "Earlier assistant answer" in expanded
    assert "how should I administer it?" in expanded


def test_build_retrieval_query_passes_through_when_query_self_sufficient() -> None:
    query = "What is the recommended approach for unstable wide complex tachycardia?"
    expanded = build_retrieval_query(query, history=[])
    assert expanded == query


def test_trim_history_keeps_anchor_and_recent_turns() -> None:
    history = [
        {"role": "user", "content": "anchor question about WPW dosing"},
        {"role": "assistant", "content": "answer 1"},
        {"role": "user", "content": "follow-up 1"},
        {"role": "assistant", "content": "answer 2"},
        {"role": "user", "content": "follow-up 2"},
        {"role": "assistant", "content": "answer 3"},
        {"role": "user", "content": "latest question"},
    ]
    kept, dropped = _trim_history_to_budget(history, token_budget=20)
    assert kept[0]["content"].startswith("anchor")
    assert kept[-1]["content"] == "latest question"
    assert all(m in history for m in dropped)


def test_build_chat_messages_orders_correctly_and_injects_memory() -> None:
    history = [
        {"role": "user", "content": "long anchor turn " + "x" * 4_000},
        {"role": "assistant", "content": "long anchor reply " + "y" * 4_000},
        {"role": "user", "content": "follow-up"},
        {"role": "assistant", "content": "follow-up answer"},
    ]
    retrieved = [
        {"heading_context": "ProcainamideĀ", "text_content": "Administer 20 mg/min."},
    ]
    messages = build_chat_messages(
        query="how should I administer it?",
        history=history,
        retrieved_context=retrieved,
        thinking_mode=False,
    )

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert messages[-1]["role"] == "user"
    assert "/no_think" in messages[-1]["content"]
    assert "Administer 20 mg/min." in messages[-1]["content"]


def test_build_chat_messages_safe_when_history_is_empty() -> None:
    messages = build_chat_messages(
        query="What does the WhiteBook say about WPW?",
        history=[],
        retrieved_context=[],
        thinking_mode=True,
    )
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert "/think" in messages[-1]["content"]
    assert "No relevant WhiteBook context" in messages[-1]["content"]


def test_calculator_system_prompt_demands_tool_use() -> None:
    lower = SYSTEM_PROMPT_CALCULATOR.lower()
    assert "calculator" in lower
    assert "tool" in lower
    assert "never compute mentally" in lower


def test_build_calculator_messages_does_not_inject_retrieval() -> None:
    messages = build_calculator_messages(
        query="HEART score for 65F with no risk factors",
        history=[],
        thinking_mode=False,
    )
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT_CALCULATOR
    assert messages[-1]["role"] == "user"
    assert "Retrieved" not in messages[-1]["content"]
    assert "WhiteBook context" not in messages[-1]["content"]
    assert "/no_think" in messages[-1]["content"]


def test_build_calculator_messages_preserves_history() -> None:
    history = [
        {"role": "user", "content": "Calculate MAP for 120/80"},
        {"role": "assistant", "content": "MAP is approximately 93 mmHg."},
    ]
    messages = build_calculator_messages(
        query="Now CHA2DS2-VASc for the same 65F patient",
        history=history,
        thinking_mode=False,
    )
    contents = [m.get("content", "") for m in messages]
    assert any("MAP for 120/80" in c for c in contents)
    assert any("CHA2DS2-VASc" in c for c in contents)
