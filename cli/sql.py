import click
from flask import current_app as app
from flask.cli import with_appcontext

from backend.models import Submission


@click.group()
@click.help_option("-h", "--help")
def sql():
    """Performs operations on the SQL database."""


@sql.command()
@with_appcontext
def init():
    """Initialize the SQL database."""
    db = app.config["DATABASE"]
    db.create_all()
    click.secho("Successfully initiliazed the database.", fg="green")


@click.group()
@click.help_option("-h", "--help")
def submissions():
    """Performs operations on the Submission table."""


@submissions.command()
@with_appcontext
def clear():
    """Clear all submissions."""
    Submission.clear()


@submissions.command()
@with_appcontext
def show():
    """Show all submissions."""
    for submission in Submission.query.all():
        click.echo(submission)


sql.add_command(submissions)
