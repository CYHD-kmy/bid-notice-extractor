"""运行配置：受控数据环境与模型调用预算。

竞赛要求「须在封闭或半封闭数据环境中运行」。本模块集中声明所有环境约束，
让评审能一处看清"这个系统被允许做什么"。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# 项目根目录（core/ 的上一级）
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ModelConfig:
    """模型调用预算 —— 与 prototype/run_demo.py 的 BudgetedOllama 保持一致。"""
    name: str = "qwen3-vl:8b"
    endpoint: str = "http://localhost:11434"
    max_calls: int = 1              # 每次运行硬上限
    timeout_seconds: int = 55
    max_output_tokens: int = 1000
    num_ctx: int = 4096
    temperature: float = 0.0
    seed: int = 42
    keep_alive: int = 0             # 结束后卸载模型
    auto_retry: bool = False        # 不自动重试


@dataclass(frozen=True)
class DataConfig:
    """数据访问边界。"""
    allow_external_network: bool = False    # 除本机 Ollama 外不允许外网
    restrict_to_project_dir: bool = True    # 输入/输出必须位于项目目录内
    max_input_files: int = 2
    max_source_chars: int = 5000            # 轻量试跑上限
    require_text_layer: bool = True         # 无文本层直接报错（未接入 OCR）
    samples_dir: str = "samples"
    outputs_dir: str = "outputs"


@dataclass(frozen=True)
class CalcConfig:
    """计算规则。"""
    default_places: int = 2
    rounding: str = "ROUND_HALF_UP"
    forbid_float: bool = True               # 全程 Decimal
    allow_cross_unit: bool = False          # 单位不一致不自动换算


@dataclass(frozen=True)
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    data: DataConfig = field(default_factory=DataConfig)
    calc: CalcConfig = field(default_factory=CalcConfig)
    root: Path = ROOT

    # ---------------------------------------------------------------- 路径
    @property
    def samples(self) -> Path:
        return self.root / self.data.samples_dir

    @property
    def outputs(self) -> Path:
        return self.root / self.data.outputs_dir

    # ---------------------------------------------------------------- 守卫
    def ensure_inside(self, path: Path, what: str = "路径") -> Path:
        """强制路径位于项目目录内（半封闭数据环境的硬约束）。"""
        p = Path(path).resolve()
        if self.data.restrict_to_project_dir and not p.is_relative_to(self.root):
            raise PermissionError(f"{what}必须位于项目目录内：{p}")
        return p

    def describe(self) -> dict:
        """供 runtime.json / 报告"可复现性说明"使用。"""
        return {
            "model": {
                "name": self.model.name,
                "endpoint": self.model.endpoint,
                "max_calls_per_run": self.model.max_calls,
                "timeout_seconds": self.model.timeout_seconds,
                "max_output_tokens": self.model.max_output_tokens,
                "temperature": self.model.temperature,
                "seed": self.model.seed,
                "keep_alive": self.model.keep_alive,
                "auto_retry": self.model.auto_retry,
            },
            "data": {
                "allow_external_network": self.data.allow_external_network,
                "restrict_to_project_dir": self.data.restrict_to_project_dir,
                "max_input_files": self.data.max_input_files,
                "max_source_chars": self.data.max_source_chars,
                "require_text_layer": self.data.require_text_layer,
            },
            "calc": {
                "default_places": self.calc.default_places,
                "rounding": self.calc.rounding,
                "forbid_float": self.calc.forbid_float,
                "allow_cross_unit": self.calc.allow_cross_unit,
            },
            "python": _python_version(),
        }


def _python_version() -> str:
    import platform
    return platform.python_version()


DEFAULT = Config()
