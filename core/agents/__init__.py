import importlib
import sys
from pathlib import Path


def extract_agent_reply(result: dict) -> str:
    msgs = result.get("messages", [])
    if msgs:
        return str(msgs[-1].content)
    return str(result)


def verify_working_code(work_dir: Path) -> str | None:
    """Import-check all Python files in working/. Returns error string or None."""
    importlib.invalidate_caches()
    for subdir in ("handlers", "tools", "subagents"):
        d = work_dir / subdir
        if not d.exists():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name == "__init__.py":
                continue
            module_name = f"working.{subdir}.{f.stem}"
            sys.modules.pop(module_name, None)
            try:
                importlib.import_module(module_name)
            except SyntaxError as e:
                return f"{f.name}: SyntaxError — {e}"
            except ImportError as e:
                return f"{f.name}: ImportError — {e}"
            except Exception as e:
                return f"{f.name}: {type(e).__name__} — {e}"
    return None
