"""Typed rule vocabulary. Serialized dictionaries remain compatible with Pack v1."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

Number = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhysicalRequirements(RuleModel):
    capabilities: list[StrictStr] = []
    min_mobility: Number = 0
    min_breath: Number = 0
    forbidden_injuries: list[StrictStr] = []


class ContextRequirements(RuleModel):
    any: list[Literal["conversation", "confrontation", "waiting"]] = []
    private_only: StrictBool = False


class StateEffects(RuleModel):
    pose: Literal["standing", "seated", "leaning_wall", "lying"] | None = None
    orientation: Literal["target", "away"] | None = None
    distance_delta: Annotated[float, Field(strict=True, ge=-.4, le=.4, allow_inf_nan=False)] | None = None
    transfer: Literal["right_to_left", "left_to_right"] | None = None
    clear_support: StrictBool = False


class WorldRequirements(RuleModel):
    min_realm: Literal["mortal", "qi_refining", "foundation", "golden_core"]
    min_stage: Annotated[int, Field(strict=True, ge=1, le=9)] = 1
    capability: StrictStr
    cost: Number
    control: Number
    destruction: Number
    min_intensity: Number
    target_dominance: StrictBool = False
    requires_active: list[StrictStr] = []
    activate: list[StrictStr] = []
    deactivate: list[StrictStr] = []


class RenderHints(RuleModel):
    subject: StrictStr
    verb: Annotated[str, Field(strict=True, min_length=1)]
    complement: StrictStr = ""
    alternate_verb: StrictStr | None = None
