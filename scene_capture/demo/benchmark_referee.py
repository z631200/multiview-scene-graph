# benchmark_referee.py
from __future__ import annotations
from typing import Any, Dict

from scene_capture.demo.task_definition import TaskDefinition
from scene_capture.demo.pddl_goal import GoalEvaluator

class Referee:
    def check_success(self, task: TaskDefinition, current_metadata) -> Dict[str, Any]:
        """If task.goal_ast exists -> evaluate PDDL; else fallback to legacy tuple-goals."""
        objects = current_metadata['objects']

        # 1) PDDL goal (preferred)
        if task.goal_ast is not None:
            evaluator = GoalEvaluator(objects)
            ok, details = evaluator.eval(task.goal_ast)
            return {'is_success': ok, 'details': details}

        # 2) Legacy tuple-goals
        if not task.goal_conditions:
            return {'is_success': False, 'details': {'error': 'No goal configured'}}
        goals_by_type = {}
        for cond in task.goal_conditions:
            goals_by_type.setdefault(cond.object_type, []).append(cond)

        final_details = {}
        all_types_met = True

        for obj_type, conditions in goals_by_type.items():
            candidates = [obj for obj in objects if obj.get('objectType') == obj_type]
            type_success = False

            for obj in candidates:
                obj_meets_all = True
                for cond in conditions:
                    actual_val = obj.get(cond.property_name)
                    is_met = False

                    if cond.property_name == 'parentReceptacles':
                        if isinstance(actual_val, list):
                            is_met = any(cond.expected_value in rid for rid in actual_val if isinstance(rid, str))
                        elif isinstance(actual_val, str):
                            is_met = (cond.expected_value in actual_val)
                        else:
                            is_met = False
                    elif actual_val == cond.expected_value:
                        is_met = True

                    if not is_met:
                        obj_meets_all = False
                        break

                if obj_meets_all:
                    type_success = True
                    break

            status_key = f'All_Conditions_For_{obj_type}'
            final_details[status_key] = type_success
            if not type_success:
                all_types_met = False

        return {'is_success': all_types_met, 'details': final_details}

    def evaluate_step(self, action_result):
        if not action_result['success']:
            return f"裁判判定: 動作失敗 ({action_result['message']})"
        return '裁判判定: 動作執行成功'
