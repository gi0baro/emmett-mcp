# Emmett-MCP

An extension for [Emmett](https://emmett.sh) and [Emmett55](https://github.com/emmett-framework/emmett55) to build [MCP servers](https://modelcontextprotocol.io).

> **Note**: Emmett-MCP only supports the [SSE transport](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports#http-with-sse).

## In a nutshell

```python
from emmett55 import App
from emmett_mcp import MCP, MCPModule

app = App(__name__)
mcp = app.use_extension(MCP)

mcp_server: MCPModule = app.mcp_module(__name__, "mcp", url_prefix="/mcp")

@mcp_server.resource("echo://{message}")
def echo_resource(message: str) -> str:
    return f"Resource echo: {message}"

@mcp_server.tool()
def echo_tool(message: str) -> str:
    return f"Tool echo: {message}"

@mcp_server.prompt()
def echo_prompt(message: str) -> str:
    return f"Please process this message: {message}"
```

## License

Emmett-MCP is released under BSD license. Check the LICENSE file for more details.
