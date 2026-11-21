"""Seeded random problem generator, so every benchmark run sees exactly the same instances."""
import random

from models import ScheduleProblem, Unavailability


def random_problem(
    n_employees: int,
    num_days: int,
    min_staff: int,
    max_consecutive: int = 5,
    p_unavailable: float = 0.1,
    seed: int = 0,
) -> ScheduleProblem:
    """Each (employee, day) pair is independently unavailable with probability p_unavailable."""
    # A string seed is hashed deterministically by `random` (unlike hash(), it ignores PYTHONHASHSEED)
    rng = random.Random(f"{n_employees}-{num_days}-{min_staff}-{max_consecutive}-{p_unavailable}-{seed}")
    employees = [f"E{i + 1}" for i in range(n_employees)]
    unavailable = [
        Unavailability(employee=e, day=d) for e in employees for d in range(num_days) if rng.random() < p_unavailable
    ]
    return ScheduleProblem(
        employees=employees,
        num_days=num_days,
        min_staff_per_shift=min_staff,
        max_consecutive_days=max_consecutive,
        unavailable=unavailable,
    )
