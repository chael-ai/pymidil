import click
from pymidil.cli.testing.options import TestOptions
from pymidil.cli.testing.runner import PytestRunner
from pymidil.cli.commands.console import console


@click.command("test")
@click.option("--coverage", "-c", is_flag=True, help="Run with coverage")
@click.option("--file", "-f", type=str, help="Run tests for a specific file or dir")
@click.option("--verbose", "-v", is_flag=True, help="Run in verbose mode")
@click.option("--html-cov", is_flag=True, help="Generate HTML coverage report")
def test_command(coverage, file, verbose, html_cov):
    """Run tests using pytest with MIDIL-style options."""
    console.print("🧪 Running MIDIL tests...", style="bold blue")
    options = TestOptions(
        coverage=coverage, file=file, verbose=verbose, html_cov=html_cov
    )
    runner = PytestRunner(options)
    runner.run()
