import ast
from pathlib import Path


source = Path("etm_sync_local.py").read_text(encoding="utf-8")
module = ast.parse(source, filename="etm_sync_local.py")
func_node = next(
    node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_build_article_variants"
)
func_module = ast.Module(body=[func_node], type_ignores=[])
namespace = {}
exec(compile(func_module, filename="etm_sync_local.py", mode="exec"), namespace)
_build_article_variants = namespace["_build_article_variants"]


def run_case(article, expected):
    actual = _build_article_variants(article)
    assert actual == expected, f"{article}: expected {expected}, got {actual}"
    print(f"OK: {article} -> {actual}")


if __name__ == "__main__":
    run_case("33110-5", ["33110-5", "33110"])
    run_case("613100230-1", ["613100230-1", "613100230"])
    run_case("MVA20-1-016-C", ["MVA20-1-016-C"])
    run_case("  33110-5  ", ["33110-5", "33110"])
    print("All variant tests passed.")
