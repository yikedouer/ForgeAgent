"""核心层：Engine、LLM Provider、运行时设置、权限系统、错误层级。"""

from .engine import Engine
from .providers import Provider, Completion, Invocation
from .settings import Settings
from .permissions import PermissionMode, PermissionEnforcer
from .hooks import HookResult, clear_hooks, emit_hook, load_hook_file, register_hook
from .mcp import (
    MCPClient, MCPProtocolError, MCPServerConfig, MCPTool, MCPTransport,
    StdioMCPTransport, parse_mcp_servers,
)
from .errors import (
    ForgeError, ProviderError, ContextWindowError,
    AuthenticationError, RateLimitedError,
    ToolError, PermissionDenied,
)

__all__ = [
    "Engine", "Provider", "Completion", "Invocation", "Settings",
    "PermissionMode", "PermissionEnforcer",
    "HookResult", "clear_hooks", "emit_hook", "load_hook_file", "register_hook",
    "MCPClient", "MCPProtocolError", "MCPServerConfig", "MCPTool",
    "MCPTransport", "StdioMCPTransport", "parse_mcp_servers",
    "ForgeError", "ProviderError", "ContextWindowError",
    "AuthenticationError", "RateLimitedError",
    "ToolError", "PermissionDenied",
]
