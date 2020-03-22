import asyncio
from collections import defaultdict
from functools import wraps
from json import dumps, loads
from string import ascii_letters, digits

from quart import (
    Quart,
    websocket,
    render_template,
    request,
    redirect,
    url_for,
    make_response,
)

from game import Game
from storage import Cookies, Users

VALID_USERNAME_CHARS = set(ascii_letters + digits + "_")

COOKIES = Cookies()
USERS = Users()

app = Quart(__name__)
app.games = dict()
app.game_connections = defaultdict(set)


def make_game(game_id):
    def destroy_game():
        del app.games[game_id]
        app.game_connections[game_id].clear()

    app.games[game_id] = Game(app.game_connections[game_id], when_finished=destroy_game)


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
    values = await request.values
    dest = values.get("dest")
    # TODO: This is (kinda) a security vulnerability -- malicious redirect.
    if "auth" in request.cookies and COOKIES.check(request.cookies["auth"]):
        return redirect(dest or "/")

    error = ""
    if values.get("acct_created"):
        error = "Thank you for creating an account! Please log in."

    COOKIES.prune()
    return await render_template("auth.html", dest=dest, error=error)


@app.route("/log_in", methods=["POST"])
async def authenticate():
    values = await request.values
    dest = values.get("dest")
    if "auth" in request.cookies and COOKIES.check(request.cookies["auth"]):
        return redirect(dest or "/")

    if not values.get("password") and values.get("username"):
        return redirect(url_for("log_in"))

    if not type(values["password"]) is str and type(values["username"]) is str:
        return redirect(url_for("log_in"))

    if len(values["password"]) > 1024:
        return await render_template(
            "auth.html", error="Password must be 1024 characters or shorter.", dest=dest
        )

    true_username = USERS.authenticate(values["username"], values["password"])
    if true_username is not None:
        resp = await make_response(redirect(values.get("dest") or "/"))
        resp.set_cookie(
            "auth",
            value=COOKIES.new(true_username),
            max_age=int(COOKIES.VALID_LENGTH.total_seconds()),
        )
        return resp
    else:
        return await render_template(
            "auth.html", error="Unknown username or incorrect password.", dest=dest
        )


@app.route("/log_out", methods=["POST"])
async def log_out():
    if "auth" in request.cookies:
        COOKIES.remove(request.cookies["auth"])
    response = redirect("/")
    response.set_cookie("auth", "", expires=0)
    return response


def collect_websocket(func):
    @wraps(func)
    async def wrapper(game_id, *args, **kwargs):
        queue = asyncio.Queue()
        username = COOKIES.user(websocket.cookies.get("auth"))
        app.game_connections[game_id].add((queue, username))
        try:
            return await func(queue, game_id, *args, **kwargs)
        finally:
            app.game_connections[game_id].discard((queue, username))

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
            await game.player_move(player_id, move, queue)

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


@app.route("/play/<int:game_id>/")
@authenticated
async def play(game_id):
    if game_id not in app.games:
        make_game(game_id)

    return await render_template("play.html", user=get_user(request), game_id=game_id)


def get_user(req):
    auth = req.cookies.get("auth")
    if auth is not None:
        return COOKIES.user(auth)


@app.route("/play/", methods=["GET"])
async def go_to_game():
    values = await request.values
    game_id = values.get("game_id")
    if game_id is None:
        return redirect(url_for("index"))
    return redirect(url_for("play", game_id=game_id))


@app.route("/sign_up", methods=["POST"])
async def register():
    values = await request.values
    dest = values.get("dest")
    if not values.get("password") and values.get("username"):
        return redirect(url_for("sign_up"))

    if not type(values["password"]) is str and type(values["username"]) is str:
        return redirect(url_for("sign_up"))

    if not all(c in VALID_USERNAME_CHARS for c in values["username"]):
        return await render_template(
            "register.html",
            error="Characters in username can be only letters, numbers, and underscore.",
            dest=dest,
        )

    if len(values["username"]) > 20:
        return await render_template(
            "register.html",
            error="Username must be shorter than 20 characters.",
            dest=dest,
        )

    if len(values["password"]) > 1024:
        return await render_template(
            "register.html",
            error="Password must be 1024 characters or shorter.",
            dest=dest,
        )

    error = USERS.register(values["username"], values["password"])
    if error is None:
        return redirect(url_for("log_in", acct_created=True))
    else:
        return await render_template("register.html", error=error)


@app.route("/sign_up", methods=["GET"])
async def sign_up():
    values = await request.values
    dest = values.get("dest")
    if "auth" in request.cookies and COOKIES.check(request.cookies["auth"]):
        return redirect(dest or "/")
    return await render_template("register.html")


@app.route("/", methods=["GET"])
async def index():
    return await render_template("index.html", user=get_user(request))


if __name__ == "__main__":
    app.run()
