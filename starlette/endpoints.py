import asyncio
import typing
import json
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.websockets import WebSocket
from starlette.responses import Response, PlainTextResponse
from starlette.types import Receive, Send, Scope


class HTTPEndpoint:
    def __init__(self, scope: Scope) -> None:
        assert scope["type"] == "http"
        self.scope = scope

    async def __call__(self, receive: Receive, send: Send) -> None:
        request = Request(self.scope, receive=receive)
        kwargs = self.scope.get("kwargs", {})
        response = await self.dispatch(request, **kwargs)
        await response(receive, send)

    async def dispatch(self, request: Request, **kwargs: typing.Any) -> Response:
        handler_name = "get" if request.method == "HEAD" else request.method.lower()
        handler = getattr(self, handler_name, self.method_not_allowed)
        if asyncio.iscoroutinefunction(handler):
            response = await handler(request, **kwargs)
        else:
            response = handler(request, **kwargs)
        return response

    async def method_not_allowed(
        self, request: Request, **kwargs: typing.Any
    ) -> Response:
        # If we're running inside a starlette application then raise an
        # exception, so that the configurable exception handler can deal with
        # returning the response. For plain ASGI apps, just return the response.
        if "app" in self.scope:
            raise HTTPException(status_code=405)
        return PlainTextResponse("Method Not Allowed", status_code=405)


class WebSocketEndpoint:

    encoding = None  # May be "text", "bytes", or "json".

    def __init__(self, scope: Scope) -> None:
        assert scope["type"] == "websocket"
        self.scope = scope

    async def __call__(self, receive: Receive, send: Send) -> None:
        websocket = WebSocket(self.scope, receive=receive, send=send)
        kwargs = self.scope.get("kwargs", {})
        await self.on_connect(websocket, **kwargs)

        close_code = None

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.receive":
                    data = await self.decode(websocket, message)
                    await self.on_receive(websocket, data)
                elif message["type"] == "websocket.disconnect":
                    close_code = message.get("code", 1000)
                    return
        finally:
            await self.on_disconnect(websocket, close_code)

    async def decode(self, websocket, message):

        if self.encoding == "text":
            if "text" not in message:
                await websocket.close(code=1003)
                raise RuntimeError("Expected text websocket messages, but got bytes")
            return message["text"]

        elif self.encoding == "bytes":
            if "bytes" not in message:
                await websocket.close(code=1003)
                raise RuntimeError("Expected bytes websocket messages, but got text")
            return message["bytes"]

        elif self.encoding == "json":
            if "bytes" not in message:
                await websocket.close(code=1003)
                raise RuntimeError(
                    "Expected JSON to be transferred as bytes websocket messages, but got text"
                )
            return json.loads(message["bytes"].decode("utf-8"))

        assert (
            self.encoding is None
        ), f"Unsupported 'encoding' attribute {self.encoding}"
        return message["text"] if "text" in message else message["bytes"]

    async def on_connect(self, websocket, **kwargs):
        """Override to handle an incoming websocket connection"""
        await websocket.accept()

    async def on_receive(self, websocket, data):
        """Override to handle an incoming websocket message"""

    async def on_disconnect(self, websocket, close_code):
        """Override to handle a disconnecting websocket"""
