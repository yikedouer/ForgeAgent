"""Runtime transcript and event recording tests."""

from unittest.mock import MagicMock


class TestRuntimeRecorder:
    def test_main_agent_appends_message_and_writes_runtime_event(self):
        from forgecc.core.runtime import RuntimeRecorder

        append_event = MagicMock()
        transcript: list[dict] = []
        message = {"role": "user", "content": "Hello"}

        recorder = RuntimeRecorder(
            session_id=lambda: "session-1",
            is_sub_agent=False,
            append_message_event=append_event,
        )

        recorder.append(transcript, message)

        assert transcript == [message]
        append_event.assert_called_once_with("session-1", 0, message)

    def test_sub_agent_appends_message_without_runtime_event(self):
        from forgecc.core.runtime import RuntimeRecorder

        append_event = MagicMock()
        transcript: list[dict] = []

        recorder = RuntimeRecorder(
            session_id=lambda: "session-1",
            is_sub_agent=True,
            append_message_event=append_event,
        )

        recorder.append(transcript, {"role": "assistant", "content": "Answer"})

        assert transcript == [{"role": "assistant", "content": "Answer"}]
        append_event.assert_not_called()

    def test_runtime_event_failure_does_not_block_transcript_append(self):
        from forgecc.core.runtime import RuntimeRecorder

        logger = MagicMock()
        transcript: list[dict] = []
        append_event = MagicMock(side_effect=RuntimeError("disk full"))

        recorder = RuntimeRecorder(
            session_id=lambda: "session-1",
            is_sub_agent=False,
            append_message_event=append_event,
            logger=logger,
        )

        recorder.append(transcript, {"role": "user", "content": "Hello"})

        assert transcript == [{"role": "user", "content": "Hello"}]
        logger.warning.assert_called_once()
