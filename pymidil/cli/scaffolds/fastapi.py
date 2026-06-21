from pathlib import Path
from typing import Dict, Any
from cookiecutter.main import cookiecutter  # type: ignore
from rich.console import Console
from pymidil.cli.scaffolds.base import ProjectScaffolder

console = Console()


class FastAPIServiceScaffolder(ProjectScaffolder):
    """
    Concrete scaffolder using Cookiecutter.
    """

    def __init__(self, template_dir: Path, no_user_input: bool = False):
        self.template_dir = template_dir
        self.no_user_input = no_user_input

    def _get_extra_context(self, name: str) -> Dict[str, Any]:
        return {
            "project_name": name.replace("_", " ").replace("-", " ").title(),
            "project_slug": name.lower().replace(" ", "-").replace("_", "_"),
        }

    def _ensure_services_dir(self) -> Path:
        services_dir = Path.cwd() / "services"
        services_dir.mkdir(exist_ok=True)
        return services_dir

    def scaffold(self, name: str) -> None:
        template_path = self.template_dir
        extra_context = self._get_extra_context(name)
        services_dir = self._ensure_services_dir()

        try:
            result = cookiecutter(
                str(template_path),
                output_dir=str(services_dir),
                extra_context=extra_context,
                no_input=self.no_user_input,
                skip_if_file_exists=True,
            )
            service_name = Path(result).name

            console.print(f"✅ Project scaffolded at {result}", style="green")
            console.print(
                f"\n🎉 Your {service_name} service is ready!", style="bold blue"
            )
            console.print("📖 Check the README.md for next steps", style="cyan")
        except Exception as e:
            console.print(f"❌ Failed to create project: {e}", style="red")
