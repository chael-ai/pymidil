from pathlib import Path
from pymidil.cli.scaffolds.base import ProjectScaffolder


class LambdaFunctionScaffolder(ProjectScaffolder):
    """
    Concrete scaffolder using Cookiecutter.
    """

    def __init__(self, template_dir: Path, no_user_input: bool = False):
        self.template_dir = template_dir
        self.no_user_input = no_user_input

    def scaffold(self, name: str) -> None:
        # TODO: Implement lambda project scaffolding
        raise NotImplementedError("Lambda project scaffolding is not implemented yet")
