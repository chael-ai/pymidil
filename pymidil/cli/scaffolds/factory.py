from pathlib import Path
from pymidil.cli.scaffolds.base import ProjectScaffolder
from pymidil.cli.scaffolds.fastapi import FastAPIServiceScaffolder
from pymidil.cli.scaffolds.lambda_function import LambdaFunctionScaffolder

_NO_USER_INPUT = False


class ProjectScaffolderFactory:
    """
    Factory class to create project scaffolders based on project type.
    """

    @staticmethod
    def create(project_type: str = "fastapi") -> "ProjectScaffolder":
        template_base = Path(__file__).parent.parent / "templates"
        if project_type == "fastapi":
            template_path = template_base / "cookiecutter-midil-project"
            return FastAPIServiceScaffolder(template_path, no_user_input=_NO_USER_INPUT)
        elif project_type == "lambda":
            template_path = template_base / "cookiecutter-midil-lambda"
            return LambdaFunctionScaffolder(template_path, no_user_input=_NO_USER_INPUT)
        else:
            raise ValueError(f"Unknown project type: {project_type}")


def scaffold_project(name: str, project_type: str = "fastapi") -> None:
    """
    Facade function to scaffold a new MIDIL project using the appropriate scaffolder.
    """
    scaffolder = ProjectScaffolderFactory.create(project_type)
    scaffolder.scaffold(name)
