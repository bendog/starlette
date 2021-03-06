from starlette.exceptions import ExceptionMiddleware
from starlette.lifespan import LifespanHandler
from starlette.requests import Request
from starlette.routing import Path, PathPrefix, Router
from starlette.types import ASGIApp, ASGIInstance, Receive, Scope, Send
from starlette.websockets import WebSocket
import asyncio
import inspect
import typing


def request_response(func):
    """
    Takes a function or coroutine `func(request, **kwargs) -> response`,
    and returns an ASGI application.
    """
    is_coroutine = asyncio.iscoroutinefunction(func)

    def app(scope: Scope) -> ASGIInstance:
        async def awaitable(receive: Receive, send: Send) -> None:
            request = Request(scope, receive=receive)
            kwargs = scope.get("kwargs", {})
            if is_coroutine:
                response = await func(request, **kwargs)
            else:
                response = func(request, **kwargs)
            await response(receive, send)

        return awaitable

    return app


def websocket_session(func):
    """
    Takes a coroutine `func(session, **kwargs)`, and returns an ASGI application.
    """

    def app(scope: Scope) -> ASGIInstance:
        async def awaitable(receive: Receive, send: Send) -> None:
            session = WebSocket(scope, receive=receive, send=send)
            kwargs = scope.get("kwargs", {})
            await func(session, **kwargs)

        return awaitable

    return app


class Starlette:
    def __init__(self, debug=False) -> None:
        self.router = Router(routes=[])
        self.lifespan_handler = LifespanHandler()
        self.app = self.router
        self.exception_middleware = ExceptionMiddleware(self.router, debug=debug)

    @property
    def debug(self) -> bool:
        return self.exception_middleware.debug

    @debug.setter
    def debug(self, value: bool) -> None:
        self.exception_middleware.debug = value

    def on_event(self, event_type: str):
        return self.lifespan_handler.on_event(event_type)

    def mount(self, path: str, app: ASGIApp, methods=None) -> None:
        prefix = PathPrefix(path, app=app, methods=methods)
        self.router.routes.append(prefix)

    def add_middleware(self, middleware_class: type, **kwargs: typing.Any) -> None:
        self.exception_middleware.app = middleware_class(self.app, **kwargs)

    def add_exception_handler(self, exc_class: type, handler) -> None:
        self.exception_middleware.add_exception_handler(exc_class, handler)

    def add_route(self, path: str, route, methods=None) -> None:
        if not inspect.isclass(route):
            route = request_response(route)
            if methods is None:
                methods = ["GET"]

        instance = Path(path, route, protocol="http", methods=methods)
        self.router.routes.append(instance)

    def add_websocket_route(self, path: str, route) -> None:
        if not inspect.isclass(route):
            route = websocket_session(route)

        instance = Path(path, route, protocol="websocket")
        self.router.routes.append(instance)

    def exception_handler(self, exc_class: type):
        def decorator(func):
            self.add_exception_handler(exc_class, func)
            return func

        return decorator

    def route(self, path: str, methods=None):
        def decorator(func):
            self.add_route(path, func, methods=methods)
            return func

        return decorator

    def websocket_route(self, path: str):
        def decorator(func):
            self.add_websocket_route(path, func)
            return func

        return decorator

    def __call__(self, scope: Scope) -> ASGIInstance:
        if scope["type"] == "lifespan":
            return self.lifespan_handler(scope)
        scope["app"] = self
        return self.exception_middleware(scope)
