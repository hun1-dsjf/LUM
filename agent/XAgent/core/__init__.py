"""XAgent 核心引擎（延迟导入避免循环依赖）。"""

__all__ = ["Agent", "EventCallback"]


def __getattr__(name):
    """按名称延迟导入，防止 core.skill_loader 触发 .agent 导入 → tools → 循环。"""
    if name in ("Agent", "EventCallback"):
        from .agent import Agent, EventCallback
        return locals()[name]
    raise AttributeError(f"module 'core' has no attribute {name!r}")
