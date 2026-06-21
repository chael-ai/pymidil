from rich.panel import Panel
from rich.text import Text
from rich.console import Console
from pyfiglet import Figlet

console = Console()


def print_logo() -> None:
    width = console.size.width - 4
    figlet = Figlet(font="standard")
    ascii_art = figlet.renderText("midil")

    text = Text(ascii_art, style="bold magenta", justify="center")
    panel = Panel(
        text,
        title="⚡ Ingenuity ⚡",
        subtitle="by midil.io",
        border_style="magenta",
        padding=(1, 4),
        width=width,
        expand=True,
    )
    console.print(panel)
