import json

from starlette.exceptions import \
    ExceptionMiddleware as StarletteExceptionMiddleware
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from connexion.exceptions import problem


class ExceptionMiddleware(StarletteExceptionMiddleware):

    def http_exception(self, request: Request, exc: HTTPException) -> Response:
        connexion_response = problem(title=exc.detail,
                                     detail=exc.detail,
                                     status=exc.status_code,
                                     headers=exc.headers)

        return Response(
            content=json.dumps(connexion_response.body),
            status_code=connexion_response.status_code,
            media_type=connexion_response.mimetype,
            headers=connexion_response.headers
        )
