import asyncio
from functools import wraps
from json import dumps, loads

from quart import (
    Quart,
    websocket,
    render_template,
    request,
    redirect,
    url_for,
    make_response,
)

from game import Game, NUM_AGENTS_DICT
from storage import Cookies

COOKIES = Cookies()

app = Quart(__name__)
app.connected_websockets = set()
app.games = dict()

app.games[42] = Game(app.connected_websockets)


def authenticated(route):
    """Wrap a function that needs to be authenticated."""

    @wraps(route)
    async def auth_wrapper(*args, **kwargs):
        if "auth" in request.cookies and COOKIES.check(request.cookies["auth"]):
            return await route(*args, **kwargs)
        return redirect(url_for("log_in", dest=request.url))

    return auth_wrapper


@app.route("/log_in", methods=["GET"])
async def log_in():
    dest = (await request.values).get("dest")
    # TODO: This is (kinda) a security vulnerability -- malicious redirect.
    if "auth" in request.cookies and COOKIES.check(request.cookies["auth"]):
        return redirect(dest or url_for("play"))

    COOKIES.prune()
    return await render_template("auth.html", dest=dest)


@app.route("/log_in", methods=["POST"])
async def authenticate():
    values = await request.values
    if "auth" in request.cookies and COOKIES.check(request.cookies["auth"]):
        return redirect(values.get("dest") or url_for("play"))
    if values.get("password", "") == "hunter2":
        resp = await make_response(redirect(values.get("dest") or url_for("play")))
        resp.set_cookie(
            "auth",
            value=COOKIES.new(values.get("username")),
            max_age=int(COOKIES.VALID_LENGTH.total_seconds()),
        )
        return resp
    else:
        return await render_template(
            "auth.html", error="Incorrect password.", dest=values.get("dest")
        )


def collect_websocket(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        queue = asyncio.Queue()
        username = COOKIES.user(websocket.cookies.get("auth"))
        app.connected_websockets.add((queue, username))
        try:
            return await func(queue, *args, **kwargs)
        finally:
            app.connected_websockets.remove((queue, username))

    return wrapper


@app.websocket("/play/<int:game_id>/ws")
@collect_websocket
async def ws(queue, game_id):
    game = app.games.get(game_id)
    if game is None:
        return

    player_id = COOKIES.user(websocket.cookies.get("auth"))

    if not game.can_join(player_id):
        return

    async def consumer():
        while True:
            data = await websocket.receive()
            try:
                move = loads(data)
            except ValueError:
                continue
            await game.player_move(player_id, move)

    async def producer():
        while True:
            data = await queue.get()
            await websocket.send(dumps(data))

    consumer_task = asyncio.ensure_future(consumer())
    producer_task = asyncio.ensure_future(producer())
    try:
        await asyncio.gather(consumer_task, producer_task)
    finally:
        consumer_task.cancel()
        producer_task.cancel()


@app.route("/")
@authenticated
async def play():
    auth = request.cookies["auth"]
    user = COOKIES.user(auth)
    return await render_template("play.html", user=user)


if __name__ == "__main__":
    app.run(host="0.0.0.0")
