# midil/core/testing/options.py
from dataclasses import dataclass
from typing import Optional


@dataclass
class TestOptions:
    coverage: bool = False
    file: Optional[str] = None
    verbose: bool = False
    html_cov: bool = False
