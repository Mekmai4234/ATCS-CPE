"""Test-only Google claims through the real nonce/session/CSRF/ownership flow."""

import time


async def login(client, app, sub):
    response = await client.get("/api/auth/challenge")
    assert response.status_code == 200, response.text
    challenge = response.json()
    app.state.auth.verifier = lambda credential, audience: {
        "sub": sub,
        "aud": audience,
        "iss": "https://accounts.google.com",
        "exp": time.time() + 300,
        "nonce": challenge["nonce"],
        "email": f"{sub}@example.test",
        "name": f"[FIXTURE] {sub}",
    }
    response = await client.post(
        "/api/auth/google",
        headers={"Origin": "http://localhost:3000"},
        json={"credential": "test-only", "csrf_token": challenge["csrf_token"]},
    )
    assert response.status_code == 200, response.text
    client.headers.update(
        {"Origin": "http://localhost:3000", "X-CSRF-Token": response.json()["csrf_token"]}
    )
    return response.json()["user"]


class OwnedRepository:
    """Scope direct fixture setup/assertions; HTTP requests still use actual sessions."""

    def __init__(self, repository, owner):
        self.repository, self.owner = repository, owner

    def __getattr__(self, name):
        value = getattr(self.repository, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            from youtube_backend.auth import actor_id

            token = actor_id.set(self.owner)
            try:
                return value(*args, **kwargs)
            finally:
                actor_id.reset(token)

        return call
