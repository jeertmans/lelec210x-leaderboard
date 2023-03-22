import os

import eventlet
import markdown
from flask import Flask
from flask.cli import load_dotenv
from flask_apscheduler import APScheduler
from flask_socketio import SocketIO
from sqlalchemy.exc import OperationalError

from backend.models import DEFAULT_CONFIG_PATH, Config
from backend.models import db as database
from cli.config import config
from cli.sql import sql
from routes.index import index
from routes.leaderboard import leaderboard

eventlet.monkey_patch(thread=True, time=True)

load_dotenv(".flaskenv")


class PrefixMiddleware(object):
    def __init__(self, app, prefix=""):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        if environ["PATH_INFO"].startswith(self.prefix):
            environ["PATH_INFO"] = environ["PATH_INFO"][len(self.prefix) :]
            environ["SCRIPT_NAME"] = self.prefix
            return self.app(environ, start_response)
        else:
            start_response("404", [("Content-Type", "text/plain")])
            return ["This url does not belong to the app.".encode()]


app = Flask(__name__, template_folder="templates")
app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix=os.environ["FLASK_STATIC_PATH"])

config_path = app.config.get("CONFIG_PATH", DEFAULT_CONFIG_PATH)
try:
    app.config["CONFIG"] = Config.parse_file(config_path)
except FileNotFoundError:
    app.config["CONFIG"] = Config()
app.config["CONFIG_PATH"] = config_path
app.config["CONFIG_NEEDS_SAVE"] = False

app.config["SCHEDULER_API_ENABLE"] = True

app.config["DATABASE"] = database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["FLASK_DATABASE_URI"]
database.init_app(app)

with app.app_context():
    try:
        app.config["CONFIG"].rounds_config.restart()
    except OperationalError:
        # Fails if db was not initialized
        pass

scheduler = APScheduler()
scheduler.init_app(app)

# app.register_blueprint(admin, url_prefix="/admin")
app.register_blueprint(index, url_prefix="/index")
app.register_blueprint(leaderboard, url_prefix="/leaderboard")


app.cli.add_command(config)
app.cli.add_command(sql)


@app.route("/")
def _index():
    readme_file = open("README.md", "r")
    md_template_string = markdown.markdown(
        readme_file.read(), extensions=["fenced_code"]
    )

    return md_template_string


if os.environ["FLASK_RUN_HOST"].lower() == "localhost":
    socketio = SocketIO(
        app,
        async_mode="eventlet",
    )

else:
    socketio = SocketIO(
        app,
        cors_allowed_origins=os.environ["FLASK_RUN_HOST"],
        path=os.environ["FLASK_STATIC_PATH"] + "/socket.io/",
        async_mode="eventlet",
    )


@socketio.on("connect")
@scheduler.task("interval", id="update_client", seconds=1.0)
def update_leaderboard():
    """Updates periodically the leaderboard by fetching data from the database."""
    with scheduler.app.app_context():
        socketio.emit(
            "update_leaderboard", app.config["CONFIG"].get_leaderboard_status().dict()
        )


@scheduler.task("interval", id="save_config", seconds=5.0)
def save_config():
    """Saves periodically the config, if needed."""
    with scheduler.app.app_context():
        if app.config["CONFIG_NEEDS_SAVE"]:
            app.config["CONFIG"].save_to(app.config["CONFIG_PATH"])
            app.config["CONFIG_NEEDS_SAVE"] = False


if __name__ == "__main__":
    scheduler.start()
    socketio.run(app, port=os.environ["FLASK_RUN_PORT"])
