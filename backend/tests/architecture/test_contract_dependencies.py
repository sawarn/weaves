import ast
from pathlib import Path

CONTRACT_ROOT = Path(__file__).parents[2] / "weaves" / "product" / "contracts"
FORBIDDEN_IMPORT_ROOTS = {
    "weaves.api",
    "weaves.worker",
    "weaves.infrastructure",
    "weaves.persistence",
    "weaves.runtime",
}


def test_product_contracts_do_not_depend_on_runtime_or_infrastructure():
    violations = []
    for path in CONTRACT_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                violations.extend(
                    (path, alias.name)
                    for alias in node.names
                    if any(
                        alias.name == root or alias.name.startswith(root + ".")
                        for root in FORBIDDEN_IMPORT_ROOTS
                    )
                )
                continue
            else:
                continue
            if any(
                module == root or module.startswith(root + ".")
                for root in FORBIDDEN_IMPORT_ROOTS
            ):
                violations.append((path, module))
    assert not violations, f"Product contracts cross a forbidden boundary: {violations}"
