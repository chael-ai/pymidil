import click
from pymidil.cli.scaffolds import scaffold_project
from pymidil.cli.commands.console import console
from pymidil.cli.display import print_logo


@click.command("init")
@click.argument("name", required=False, default="midil-project")
@click.option(
    "--type",
    type=click.Choice(["fastapi", "lambda"]),
    default="fastapi",
    help="Type of project to scaffold (fastapi: FastAPI web service, lambda: AWS Lambda function)",
)
def init_command(name, type):
    """
    Scaffold a new MIDIL project structure.

    Parameters:
        name (str, optional): The name of your project. Defaults to 'midil-project'.
        type (str, optional): The type of project to scaffold.
            Choices are 'fastapi' (FastAPI web service) or 'lambda' (AWS Lambda function).
            Defaults to 'fastapi'.

    Examples:
        Create a FastAPI service:
            midil init my-api --type fastapi

        Create a Lambda function:
            midil init my-lambda --type lambda

        Use default name and type:
            midil init
    """
    print_logo()
    console.print(f"🚀 Scaffolding {type} project: [bold]{name}[/bold]", style="blue")
    scaffold_project(name, type)
