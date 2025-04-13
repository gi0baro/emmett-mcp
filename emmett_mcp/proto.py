import asyncio
import json
from collections.abc import Iterable

import httpx
import pydantic_core
from mcp_min import types
from mcp_min.exceptions import McpError
from mcp_min.server.exceptions import ResourceError
from mcp_min.server.resources.helpers import ReadResourceContents
from mcp_min.server.resources.types import (
    BinaryResource as _BinaryResource,
    DirectoryResource as _DirectoryResource,
    FileResource as _FileResource,
    HttpResource as _HTTPResource,
    TextResource as _TextResource,
)
from mcp_min.server.utilities.content import convert_to_content


class MCPInterrupt(Exception):
    def __init__(self, target):
        self.target = target


class MCPProto:
    def __init__(self, mod):
        self._mod = mod
        self._handlers_req = {
            types.CallToolRequest: self._tool_call,
            types.GetPromptRequest: self._prompt_get,
            types.InitializeRequest: self._initialize,
            types.ListPromptsRequest: self._prompt_list,
            types.ListResourcesRequest: self._resource_list,
            types.ListResourceTemplatesRequest: self._resource_template_list,
            types.ListToolsRequest: self._tool_list,
            types.ReadResourceRequest: self._resource_read,
        }
        self._handlers_notif = {
            types.InitializedNotification: self._initialized,
        }

    async def handle_message(self, session, message):
        if isinstance(message.root, types.JSONRPCRequest):
            request = types.ClientRequest.model_validate(
                message.root.model_dump(by_alias=True, mode="json", exclude_none=True)
            )
            return await self.handle_request(session, request.root)
        if isinstance(message.root, types.JSONRPCNotification):
            notification = types.ClientNotification.model_validate(
                message.root.model_dump(by_alias=True, mode="json", exclude_none=True)
            )
            if isinstance(notification.root, types.CancelledNotification):
                raise MCPInterrupt(notification.root.params.requestId)
            return await self.handle_notification(session, notification.root)
        return None

    async def handle_request(self, session, req):
        if not session.initialized:
            if type(req) is not types.InitializeRequest:
                return None

        if handler := self._handlers_req.get(type(req)):
            try:
                res = await handler(req)
            except McpError as err:
                res = err.error
            except Exception as err:
                res = types.ErrorData(code=0, message=str(err), data=None)
        else:
            res = types.ErrorData(
                code=types.METHOD_NOT_FOUND,
                message="Method not found",
            )
        return res

    async def handle_notification(self, session, notification):
        if handler := self._handlers_notif.get(type(notification)):
            try:
                await handler(session, notification)
            except Exception:
                pass

    async def _initialize(self, request):
        return types.ServerResult(
            types.InitializeResult(
                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                capabilities=types.ServerCapabilities(
                    prompts=types.PromptsCapability(listChanged=False),
                    resources=types.ResourcesCapability(subscribe=False, listChanged=False),
                    tools=types.ToolsCapability(listChanged=False),
                    logging=None,
                    experimental={},
                ),
                serverInfo=types.Implementation(
                    name="Emmett MCP",
                    version="unknown",
                ),
                instructions=None,
            )
        )

    async def _initialized(self, session, notification):
        session.initialized = True

    async def _prompt_list(self, request):
        prompts = self._mod._manager_prompts.list_prompts()
        res = [
            types.Prompt(
                name=prompt.name,
                description=prompt.description,
                arguments=[
                    types.PromptArgument(
                        name=arg.name,
                        description=arg.description,
                        required=arg.required,
                    )
                    for arg in (prompt.arguments or [])
                ],
            )
            for prompt in prompts
        ]
        return types.ServerResult(types.ListPromptsResult(prompts=res))

    async def _prompt_get(self, request):
        try:
            messages = await self._mod._manager_prompts.render_prompt(request.params.name, request.params.arguments)
            res = types.GetPromptResult(messages=pydantic_core.to_jsonable_python(messages))
        except Exception as e:
            raise ValueError(str(e))
        return types.ServerResult(res)

    async def _resource_list(self, request):
        resources = self._mod._manager_resources.list_resources()
        res = [
            types.Resource(
                uri=resource.uri,
                name=resource.name or "",
                description=resource.description,
                mimeType=resource.mime_type,
            )
            for resource in resources
        ]
        return types.ServerResult(types.ListResourcesResult(resources=res))

    async def _resource_template_list(self, request):
        templates = self._mod._manager_resources.list_templates()
        res = [
            types.ResourceTemplate(
                uriTemplate=template.uri_template,
                name=template.name,
                description=template.description,
            )
            for template in templates
        ]
        return types.ServerResult(types.ListResourceTemplatesResult(resourceTemplates=res))

    async def _resource_read(self, request):
        def create_content(data: str | bytes, mime_type: str | None):
            match data:
                case str() as data:
                    return types.TextResourceContents(
                        uri=request.params.uri,
                        text=data,
                        mimeType=mime_type or "text/plain",
                    )
                case bytes() as data:
                    import base64

                    return types.BlobResourceContents(
                        uri=request.params.uri,
                        blob=base64.b64encode(data).decode(),
                        mimeType=mime_type or "application/octet-stream",
                    )

        resource = await self._mod._manager_resources.get_resource(request.params.uri)
        if not resource:
            raise ResourceError(f"Unknown resource: {request.params.uri}")

        try:
            content = await resource.read()
            result = [ReadResourceContents(content=content, mime_type=resource.mime_type)]
        except Exception as e:
            raise ResourceError(str(e))

        match result:
            case str() | bytes() as data:
                content = create_content(data, None)
            case Iterable() as contents:
                contents_list = [
                    create_content(content_item.content, content_item.mime_type) for content_item in contents
                ]
                return types.ServerResult(
                    types.ReadResourceResult(
                        contents=contents_list,
                    )
                )
            case _:
                raise ValueError(f"Unexpected return type from read_resource: {type(result)}")

    async def _tool_list(self, request):
        tools = self._mod._manager_tools.list_tools()
        res = [
            types.Tool(
                name=info.name,
                description=info.description,
                inputSchema=info.parameters,
            )
            for info in tools
        ]
        return types.ServerResult(types.ListToolsResult(tools=res))

    async def _tool_call(self, request):
        try:
            result = await self._mod._manager_tools.call_tool(request.params.name, request.params.arguments or {})
            converted_result = convert_to_content(result)
            return types.ServerResult(types.CallToolResult(content=list(converted_result), isError=False))
        except Exception as e:
            return types.ServerResult(
                types.CallToolResult(
                    content=[types.TextContent(type="text", text=str(e))],
                    isError=True,
                )
            )


class MCPBinaryResource(_BinaryResource): ...


class MCPDirectoryResource(_DirectoryResource):
    async def read(self):
        try:
            files = await asyncio.get_event_loop().run_in_executor(None, self.list_files)
            file_list = [str(f.relative_to(self.path)) for f in files if f.is_file()]
            return json.dumps({"files": file_list}, indent=2)
        except Exception as e:
            raise ValueError(f"Error reading directory {self.path}: {e}")


class MCPFileResource(_FileResource):
    async def read(self):
        try:
            if self.is_binary:
                return await asyncio.get_event_loop().run_in_executor(None, self.path.read_bytes)
            return await asyncio.get_event_loop().run_in_executor(None, self.path.read_text)
        except Exception as e:
            raise ValueError(f"Error reading file {self.path}: {e}")


class MCPHttpResource(_HTTPResource):
    async def read(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(self.url)
            response.raise_for_status()
            return response.text


class MCPTextResource(_TextResource): ...
