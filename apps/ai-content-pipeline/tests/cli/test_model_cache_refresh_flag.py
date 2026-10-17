import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def _function_def(path: str, name: str) -> FunctionNode:
    module = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(module):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"Function {name} not found in {path}")


def _method_def(path: str, class_name: str, method_name: str) -> FunctionNode:
    """Like `_function_def`, but scoped to one class — the module may define
    more than one function/method with the same name (e.g. more than one
    `__init__`), and a plain top-level `ast.walk` would return whichever one
    it happens to encounter first."""
    module = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(module):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for member in node.body:
                if (
                    isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and member.name == method_name
                ):
                    return member
            raise AssertionError(
                f"Method {method_name} not found in class {class_name}"
            )
    raise AssertionError(f"Class {class_name} not found in {path}")


def _arg_names(function: FunctionNode) -> set[str]:
    return {arg.arg for arg in function.args.args}


def _pipeline_plan_keywords(function: FunctionNode) -> list[set[str]]:
    keywords = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name):
            continue
        if node.func.value.id == "pipeline" and node.func.attr == "plan":
            keywords.append({kw.arg for kw in node.keywords if kw.arg is not None})
    return keywords


def test_plan_commands_expose_refresh_model_cache_flag():
    commands = [
        ("apps/ai-content-pipeline/ai_content_pipeline/cli/commands/meta.py", "plan"),
        ("apps/ai-content-pipeline/ai_content_pipeline/cli/commands/fanvue.py", "plan"),
        ("apps/ai-content-pipeline/ai_content_pipeline/cli/commands/all.py", "run_all"),
        ("apps/ai-content-pipeline/ai_content_pipeline/cli/commands/all.py", "debug"),
    ]

    for path, function_name in commands:
        assert "refresh_model_cache" in _arg_names(_function_def(path, function_name))


def test_refresh_model_cache_flag_reaches_planning_pipeline():
    pipeline_plan = _function_def(
        "apps/ai-content-pipeline/ai_content_pipeline/cli/commands/pipeline.py", "plan"
    )
    planning_manager_init = _method_def(
        "apps/ai-content-pipeline/ai_content_pipeline/planning/planning_manager.py",
        "PlanningManager",
        "__init__",
    )
    execute_all = _function_def(
        "apps/ai-content-pipeline/ai_content_pipeline/cli/commands/all.py",
        "_execute_all",
    )

    assert "refresh_model_cache" in _arg_names(pipeline_plan)
    assert "refresh_model_cache" in _arg_names(planning_manager_init)
    assert "refresh_model_cache" in _arg_names(execute_all)

    for keywords in _pipeline_plan_keywords(execute_all):
        assert "refresh_model_cache" in keywords
