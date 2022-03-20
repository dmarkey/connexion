import copy
import pathlib
import typing as t
from contextvars import ContextVar
from functools import partial

from starlette.routing import Router
from starlette.types import ASGIApp, Receive, Scope, Send

from connexion.apis.middleware_api import MiddlewareAPI
from connexion.lifecycle import MiddlewareRequest, MiddlewareResponse
from connexion.middleware import AppMiddleware
from connexion.operations import AbstractOperation
from connexion.resolver import Resolver

_default_fn: ContextVar[t.Callable] = ContextVar('DEFAULT_FN')

# Context variable that is set to call_next function with current request
_call_next_fn: ContextVar[t.Callable] = ContextVar('CALL_NEXT')


async def default_fn_callback(scope: Scope, receive: Receive, send: Send) -> None:
    """Callback to call next app as default when no matching route is found."""
    return await _default_fn.get()()


async def call_next_callback(operation: AbstractOperation, _request: MiddlewareRequest = None) \
        -> MiddlewareResponse:
    """
    Callback to call next app with current request. This function is registered as a method on
    an operation, which passes self as the first argument.
    """
    return await _call_next_fn.get()(operation)


class MiddlewareResolver(Resolver):

    def __init__(self, call_next: t.Callable) -> None:
        """Resolver that resolves each operation to the provided call_next function."""
        super().__init__()
        self.call_next = call_next

    def resolve_function_from_operation_id(self, operation_id: str) -> t.Callable:
        return self.call_next


class RoutingMiddleware(AppMiddleware):

    def __init__(self, app: ASGIApp) -> None:
        """Middleware that resolves the Operation for an incoming request and attaches it to the
        scope.

        :param app: app to wrap in middleware.
        """
        self.app = app
        # Pass unknown routes to next app
        self.router = Router(default=default_fn_callback)

    def add_api(
            self,
            specification: t.Union[pathlib.Path, str, dict],
            base_path: t.Optional[str] = None,
            arguments: t.Optional[dict] = None,
            **kwargs
    ) -> None:
        """Add an API to the router based on a OpenAPI spec.

        :param specification: OpenAPI spec as dict or path to file.
        :param base_path: Base path where to add this API.
        :param arguments: Jinja arguments to replace in the spec.
        """
        kwargs.pop("resolver", None)
        resolver = MiddlewareResolver(call_next_callback)
        api = MiddlewareAPI(specification, base_path=base_path, arguments=arguments,
                            resolver=resolver, default=default_fn_callback, **kwargs)
        self.router.mount(api.base_path, app=api.router)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Route request to matching operation, and attach it to the scope before calling the
        next app."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        default_fn = partial(self.app, copy.copy(scope), receive, send)
        _default_fn.set(default_fn)

        call_next = self._create_call_next(scope, receive, send)
        _call_next_fn.set(call_next)

        scope['app'] = 'dummy'
        await self.router(scope, receive, send)

    def _create_call_next(self, scope: Scope, receive: Receive, send: Send) -> t.Callable:
        """Create callable to call next app."""

        scope = scope.copy()

        async def attach_operation_and_call_next(
                operation: AbstractOperation,
        ) -> None:
            """Attach operation to scope and pass it to the next app"""
            scope["operation"] = operation
            return await self.app(scope, receive, send)

        return attach_operation_and_call_next
