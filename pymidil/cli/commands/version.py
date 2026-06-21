import click
from pathlib import Path

from pymidil.version import __version__, __service_version__
from pymidil.cli.commands.console import console
from pymidil.cli.display import print_logo


@click.command("version")
@click.option(
    "-s",
    "--short",
    "short",
    default=False,
    is_flag=True,
    required=False,
    help="Display only the short version number.",
)
def version_command(short: bool) -> None:
    """
    Displays the version of the Midil package (and service if inside a service directory).
    """
    if short:
        console.print(
            f"[bold cyan]midil[/bold cyan] " f"[bold green]{__version__}[/bold green]"
        )
        return

    print_logo()

    path = Path.cwd()
    in_service_dir = "services" in path.parts

    # Build version info lines
    blocks = [
        [
            "[bold cyan]midil[/bold cyan]",
            f"  └── version: [bold green]{__version__}[/bold green]",
        ]
    ]

    if in_service_dir:
        try:
            services_idx = path.parts.index("services")
            service_name = path.parts[services_idx + 1]
        except (ValueError, IndexError):
            service_name = "Service"

        blocks.append(
            [
                f"[bold cyan]{service_name}[/bold cyan]",
                f"  └── version: [bold green]{__service_version__}[/bold green]",
            ]
        )
    msg = "\n\n".join("\n".join(block) for block in blocks)
    console.print(f"\n{msg}\n", justify="left")
