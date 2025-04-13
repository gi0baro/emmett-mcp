from functools import wraps
from typing import Any, Callable, Optional, Type

from emmett_core.extensions import Extension

from .mcp import AppModule, MCPModule


def wrap_module_from_app(ext: Extension) -> Callable[..., MCPModule]:
    def rest_module_from_app(
        app,
        import_name: str,
        name: str,
        sse: bool = True,
        ws: bool = True,
        messages_path: Optional[str] = None,
        sse_path: Optional[str] = None,
        ws_path: Optional[str] = None,
        url_prefix: Optional[str] = None,
        hostname: Optional[str] = None,
        module_class: Optional[Type[MCPModule]] = None,
        **kwargs: Any,
    ) -> MCPModule:
        module_class = module_class or ext.config.default_module_class
        return module_class.from_app(
            ext,
            import_name,
            name,
            sse=sse,
            ws=ws,
            messages_path=messages_path,
            sse_path=sse_path,
            ws_path=ws_path,
            url_prefix=url_prefix,
            hostname=hostname,
            opts=kwargs,
        )

    return rest_module_from_app


def wrap_module_from_module(ext: Extension) -> Callable[..., MCPModule]:
    def rest_module_from_module(
        mod: AppModule,
        import_name: str,
        name: str,
        sse: bool = True,
        ws: bool = True,
        messages_path: Optional[str] = None,
        sse_path: Optional[str] = None,
        ws_path: Optional[str] = None,
        url_prefix: Optional[str] = None,
        hostname: Optional[str] = None,
        module_class: Optional[Type[MCPModule]] = None,
        **kwargs: Any,
    ) -> MCPModule:
        module_class = module_class or ext.config.default_module_class
        return module_class.from_module(
            ext,
            mod,
            import_name,
            name,
            sse=sse,
            ws=ws,
            messages_path=messages_path,
            sse_path=sse_path,
            ws_path=ws_path,
            url_prefix=url_prefix,
            hostname=hostname,
            opts=kwargs,
        )

    return rest_module_from_module


def wrap_method_on_obj(method, obj):
    @wraps(method)
    def wrapped(*args, **kwargs):
        return method(obj, *args, **kwargs)

    return wrapped
