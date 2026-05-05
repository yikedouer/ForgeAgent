from forgecc.core.subagent_tools import resolve_sub_agent_tool_names


def test_resolve_sub_agent_tool_names_uses_available_tools_when_unconfigured() -> None:
    available = {"read_file", "write_file", "agent", "team"}

    assert resolve_sub_agent_tool_names(available, None) == {"read_file", "write_file"}


def test_resolve_sub_agent_tool_names_uses_configured_tools_when_present() -> None:
    configured = {"read_file", "missing_tool", "agent"}

    assert resolve_sub_agent_tool_names({"read_file"}, configured) == {"read_file", "missing_tool"}


def test_resolve_sub_agent_tool_names_intersects_allowed_tools() -> None:
    available = {"read_file", "write_file", "grep_search"}

    assert resolve_sub_agent_tool_names(available, None, ("read_file", "missing_tool")) == {"read_file"}


def test_resolve_sub_agent_tool_names_always_removes_recursive_tools() -> None:
    configured = {"read_file", "agent", "team"}

    assert resolve_sub_agent_tool_names({"read_file", "agent", "team"}, configured, configured) == {"read_file"}
