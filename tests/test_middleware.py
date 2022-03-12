
def test_routing_middleware(middleware_app):
    app_client = middleware_app.app.test_client()

    response = app_client.post("/v1.0/greeting/robbe")

    assert response.headers.get('operation_id') == 'fakeapi.hello.post_greeting', \
        response.status_code
