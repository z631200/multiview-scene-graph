"""Fixed FloorPlan1 cooking demo and its action plan."""

from scene_capture.demo.task_definition import TaskDefinition

GOAL_PDDL = """
(:goal
    (and
        (forall (?re # receptacle)
            (not (opened ?re))
        )
        (exists (?r # receptacle)
            (and
                (receptacleType ?r BowlType)
                (exists (?ct # receptacle)
                    (and
                        (receptacleType ?ct CounterTopType)
                        (inReceptacle ?r ?ct)
                    )
                )
            )
        )
        (exists (?r # receptacle)
            (exists (?o # object)
                (and
                    (receptacleType ?r BowlType)
                    (objectType ?o PotatoSlicedType)
                    (inReceptacle ?o ?r)
                    (isCooked ?o True)
                )
            )
        )
    )
)
"""

ACTION_PLAN = [
    ('ShowDetail', 'bowl'),
    ('Wait', 1),
    ('RotateLeft', 90),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('LookDown', 15),
    ('LookDown', 15),
    ('RotateRight', 45),
    ('OpenObject', 'drawer'),
    ('ShowDetail', 'knife'),
    ('PickupObject', 'knife'),
    ('CloseObject', 'drawer'),
    ('RotateLeft', 45),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('RotateRight', 45),
    ('SliceObject', 'potato'),
    ('PutObject', 'CounterTop'),
    ('RotateLeft', 135),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('RotateLeft', 90),
    ('PickupObject', 'bowl'),
    ('RotateLeft', 90),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('RotateLeft', 45),
    ('MoveAhead', 0.25),
    ('PutObject', 'CounterTop'),
    ('PickupObject', 'PotatoSliced'),
    ('PutObject', 'bowl'),
    ('PickupObject', 'PotatoSliced'),
    ('PutObject', 'bowl'),
    ('PickupObject', 'PotatoSliced'),
    ('PutObject', 'bowl'),
    ('PickupObject', 'bowl'),
    ('RotateLeft', 135),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('MoveAhead', 0.25),
    ('RotateRight', 90),
    ('LookUp', 15),
    ('LookUp', 15),
    ('OpenObject', 'microwave'),
    ('PutObject', 'microwave'),
    ('CloseObject', 'microwave'),
    ('ToggleObjectOn', 'microwave'),
    ('Wait', 1),
    ('ToggleObjectOff', 'microwave'),
    ('OpenObject', 'microwave'),
    ('PickupObject', 'bowl'),
    ('CloseObject', 'microwave'),
    ('RotateLeft', 135),
    ('MoveAhead', 0.25),
    ('RotateLeft', 45),
    ('PutObject', 'CounterTop'),
    ('MoveBack', 0.25),
    ('Wait', 1),
    ('Done', None),
]

def build_task():
    task = TaskDefinition("task_cook_potato", "FloorPlan1", "Cook a potato")
    task.set_goal_pddl(GOAL_PDDL)
    return task
