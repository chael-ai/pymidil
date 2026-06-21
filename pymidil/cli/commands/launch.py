import click
from pymidil.cli.launchers.uvicorn import UvicornLauncher
from pymidil.cli.display import print_logo
from pymidil.version import __version__, __service_version__
from pymidil.cli.display import console
from pymidil.settings import ApiSettings
from typing import Optional


@click.command("launch")
@click.option("--port", required=False, type=int, help="Port to run the server on")
@click.option("--reload", is_flag=True, help="Reload the server on code changes")
@click.option("--host", required=False, help="Host to run the server on")
def launch_command(port: Optional[int], reload: bool, host: Optional[str]):
    """Launch a MIDIL service from the current directory.
    Priority: CLI > ENV/Settings > Default
    """
    print_logo()

    api_settings = ApiSettings().api
    # Only use settings if CLI did not provide a value
    resolved_port = port if port else api_settings.server.port
    resolved_host = host if host else api_settings.server.host

    if port is None or host is None:
        missing = []
        if not port:
            missing.append(f"port to {resolved_port}")
        if not host:
            missing.append(f"host to {resolved_host}")
        missing_str = " and ".join(missing)
        console.print(
            f"[yellow]Warning: API settings are not configured. Setting default {missing_str}[/yellow]"
        )

    launcher = UvicornLauncher(port=resolved_port, host=resolved_host, reload=reload)
    app_name = launcher.project_dir.name

    console.print(
        f"\n"
        f"[dim]🛸 [bold magenta]Launching[/bold magenta] "
        f"[bold white]{app_name}[/bold white] "
        f"[bold green](v{__service_version__})[/bold green]\n"
        f"   using [bold white]midil[/bold white] "
        f"[bold green](v{__version__})[/bold green]\n"
        f"   on [bold yellow]http://{resolved_host}:{resolved_port}[/bold yellow]\n\n"
        f"✨ [italic magenta]Sit back, relax, and watch the magic happen![/italic magenta][/dim]\n",
        justify="center",
    )

    launcher.run()
