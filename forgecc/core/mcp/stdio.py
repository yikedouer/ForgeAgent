"""MCP stdio transport."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from .config import MCPServerConfig
from .protocol import MCPProtocolError


class StdioMCPTransport:
    """MCP stdio transport using newline-delimited JSON-RPC messages."""

    def __init__(self, config: MCPServerConfig, process: Any | None = None):
        self.config = config
        self.process = process or self._start_process(config)

    def exchange(self, message: dict[str, Any]) -> dict[str, Any]:
        request_id = message.get("id")
        if request_id is None:
            raise ValueError("MCP stdio exchange requires a request id")
        self._write_message(message)
        while True:
            response = self._read_message()
            if response.get("id") is None:
                continue
            if response.get("id") != request_id:
                raise MCPProtocolError("MCP stdio response id did not match request id")
            return response

    def send(self, message: dict[str, Any]) -> None:
        self._write_message(message)

    def close(self) -> None:
        stdin = getattr(self.process, "stdin", None)
        if stdin is not None:
            try:
                stdin.close()
            except OSError:
                pass
        poll = getattr(self.process, "poll", None)
        terminate = getattr(self.process, "terminate", None)
        if callable(poll) and callable(terminate) and poll() is None:
            terminate()

    def _write_message(self, message: dict[str, Any]) -> None:
        stdin = getattr(self.process, "stdin", None)
        if stdin is None:
            raise MCPProtocolError("MCP stdio process has no stdin")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if "\n" in payload or "\r" in payload:
            raise MCPProtocolError("MCP stdio message must not contain embedded newlines")
        stdin.write(payload + "\n")
        stdin.flush()

    def _read_message(self) -> dict[str, Any]:
        stdout = getattr(self.process, "stdout", None)
        if stdout is None:
            raise MCPProtocolError("MCP stdio process has no stdout")
        line = stdout.readline()
        if line == "":
            raise MCPProtocolError("MCP stdio stream ended before a response")
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MCPProtocolError(f"MCP stdio produced invalid JSON: {exc.msg}") from exc
        if not isinstance(message, dict):
            raise MCPProtocolError("MCP stdio message must be an object")
        return message

    @staticmethod
    def _start_process(config: MCPServerConfig) -> subprocess.Popen:
        env = os.environ.copy()
        env.update(dict(config.env))
        return subprocess.Popen(
            [config.command, *config.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
