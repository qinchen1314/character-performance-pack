"""Character Performance Pack public package."""

from .build import PackBuildError, PackBuildResult, build_pack
from .engine import PerformanceEngine
from .ontology.pack import PerformancePack
from .renderer import ChineseNovelRenderer, ConstrainedLLMRenderer
from .prompt_brief import (
    BriefBuildConfig,
    GenerationBriefAdapter,
    PromptBriefAdapter,
    PromptBriefBuilder,
    PythonGenerationBriefAdapter,
    estimate_prompt_tokens,
)
from .extraction import (
    HybridBehaviorExtractor,
    LLMBehaviorExtractor,
    RuleBasedBehaviorExtractor,
)

__all__ = [
    "PackBuildError", "PackBuildResult", "build_pack", "PerformanceEngine", "PerformancePack",
    "ChineseNovelRenderer", "ConstrainedLLMRenderer", "BriefBuildConfig",
    "GenerationBriefAdapter", "PromptBriefAdapter", "PromptBriefBuilder",
    "PythonGenerationBriefAdapter", "estimate_prompt_tokens",
    "HybridBehaviorExtractor", "LLMBehaviorExtractor", "RuleBasedBehaviorExtractor",
]
__version__ = "0.5.0"
