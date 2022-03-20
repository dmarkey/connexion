import copy
import pathlib
import typing as t
from contextvars import ContextVar
from functools import partial

from starlette.routing import Router
from starlette.types import ASGIApp, Receive, Scope, Send

from connexion.apis.middleware_api import SwaggerUIAPI
from connexion.middleware import AppMiddleware

_default_fn: ContextVar[t.Callable] = ContextVar('DEFAULT_FN')


async def default_fn_callback(scope: Scope, receive: Receive, send: Send) -> None:
    """Callback to call next app as default when no matching route is found."""
    return await _default_fn.get()()


class SwaggerUIMiddleware(AppMiddleware):

    def __init__(self, app: ASGIApp) -> None:
        """Middleware that hosts a swagger UI.

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
        api = SwaggerUIAPI(specification, base_path=base_path, arguments=arguments,
                           default=default_fn_callback, **kwargs)
        self.router.mount(api.base_path, app=api.router)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Set call to next app with copy of current scope as default function when the router
        # does not find a matching route.
        # Unfortunately we cannot just pass the next app as default, since the router manipulates
        # the scope when descending into mounts, losing information about the base path.
        default_fn = partial(self.app, copy.copy(scope), receive, send)
        _default_fn.set(default_fn)
        await self.router(scope, receive, send)
