# task_definition.py
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from scene_capture.demo.pddl_goal import Expr, parse_goal_pddl

@dataclass
class TaskCondition:
    """定義單一目標條件（舊版 tuple-goal 相容用）"""
    object_type: str
    property_name: str
    expected_value: Any

class TaskDefinition:
    def __init__(self, task_id: str, scene_id: str, instruction: str):
        self.task_id = task_id
        self.scene_id = scene_id
        self.instruction = instruction

        # Legacy goal format
        self.goal_conditions: List[TaskCondition] = []

        # New ALFRED-style PDDL goal format
        self.goal_pddl: Optional[str] = None
        self.goal_ast: Optional[Expr] = None

    def add_goal(self, object_type: str, property_name: str, expected_value: Any):
        """新增一個勝利條件（舊版 API，相容保留）"""
        self.goal_conditions.append(TaskCondition(object_type, property_name, expected_value))

    def set_goal_pddl(self, pddl_goal: str):
        """設定 PDDL goal（可傳入 (:goal <expr>) 或直接 <expr>）"""
        goal_ast = parse_goal_pddl(pddl_goal)
        self.goal_pddl = pddl_goal
        self.goal_ast = goal_ast

    def get_initial_config(self) -> Dict:
        return {
            'scene': self.scene_id,
            'gridSize': 0.25,
        }
