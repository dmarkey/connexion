import abc
import pathlib
import typing as t

import anyio
from starlette.types import ASGIApp, Receive, Scope, Send

from connexion.lifecycle import MiddlewareRequest, MiddlewareResponse
from connexion.operations import AbstractOperation


class AppMiddleware(abc.ABC):

    @abc.abstractmethod
    def add_api(self, specification: t.Union[pathlib.Path, str, dict], **kwargs) -> None:
        pass


RequestResponseEndpoint = t.Callable[[MiddlewareRequest], t.Awaitable[MiddlewareResponse]]
DispatchFunction = t.Callable[
    [MiddlewareRequest, AbstractOperation, RequestResponseEndpoint], t.Awaitable[MiddlewareResponse]
]


class BaseHTTPMiddleware:

    def __init__(self, app: ASGIApp, dispatch: DispatchFunction = None) -> None:
        """Base Middleware to subclass. Provides easy access to request and operation."""
        self.app = app
        self.dispatch_func = self.dispatch if dispatch is None else dispatch

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async with anyio.create_task_group() as task_group:
            call_next = self._create_call_next(scope, task_group)
            request = MiddlewareRequest(scope, receive=receive)
            operation = scope["operation"]
            response = await self.dispatch_func(request, operation, call_next)
            await response(scope, receive, send)
            await task_group.cancel_scope.cancel()

    async def dispatch(
        self,
            request: MiddlewareRequest,
            operation: AbstractOperation,
            call_next: RequestResponseEndpoint
    ) -> MiddlewareResponse:
        """Function to implement in subclass.

        def dispatch(...):
            # Manipulate request
            response = await call_next(request)
            # Manipulate response
            return response

        :param request: Incoming request.
        :param operation: Operation matching the incoming request.
        :param call_next: Utility function to call the next App.

        :return: Manipulated response
        """
        raise NotImplementedError()  # pragma: no cover

    def _create_call_next(self, scope: Scope, task_group: anyio.abc.TaskGroup) -> t.Callable:
        """Create callable to call next app."""

        async def call_next(request: MiddlewareRequest) \
                -> MiddlewareResponse:
            app_exc: t.Optional[Exception] = None
            send_stream, recv_stream = anyio.create_memory_object_stream()

            async def coro() -> None:
                nonlocal app_exc

                async with send_stream:
                    try:
                        await self.app(scope, request.receive, send_stream.send)
                    except Exception as exc:
                        app_exc = exc

            task_group.start_soon(coro)

            try:
                message = await recv_stream.receive()
            except anyio.EndOfStream:
                if app_exc is not None:
                    raise app_exc
                raise RuntimeError("No response returned.")

            assert message["type"] == "http.response.start"

            async def body_stream() -> t.AsyncGenerator[bytes, None]:
                async with recv_stream:
                    async for message in recv_stream:
                        assert message["type"] == "http.response.body"
                        yield message.get("body", b"")

                if app_exc is not None:
                    raise app_exc

            response = MiddlewareResponse(
                status_code=message["status"], content=body_stream()
            )
            response.raw_headers = message["headers"]
            return response

        return call_next
