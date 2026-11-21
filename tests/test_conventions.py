import ast
import unittest
from pathlib import Path

import _path  # noqa: F401

PACKAGE = Path(_path.SCRIPTS)


class DocstringTest(unittest.TestCase):
    def test_every_function_and_class_has_a_docstring(self):
        """AGENTS.md: every function, method, and class has a short docstring."""
        missing = []
        for py in sorted(PACKAGE.rglob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                        and not ast.get_docstring(node):
                    missing.append(f"{py.relative_to(PACKAGE)}:{node.lineno} {node.name}")
        self.assertFalse(missing, "missing docstrings:\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
