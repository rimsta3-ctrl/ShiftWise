"""Data schema for the shift-scheduling problem.

This schema is the contract between the LLM (step 2) and the solver (step 1):
the LLM must produce a valid ScheduleProblem, the solver consumes it.
"""
from pydantic import BaseModel, Field, model_validator

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Unavailability(BaseModel):
    employee: str = Field(description="Employee name, exactly as written in `employees`")
    day: int = Field(ge=0, description="Day index, 0 = first day of the schedule (Monday)")


class ScheduleProblem(BaseModel):
    employees: list[str] = Field(min_length=1)
    num_days: int = Field(default=7, ge=1, le=31)
    shifts: list[str] = Field(default=["morning", "afternoon", "night"], min_length=1)
    min_staff_per_shift: int = Field(
        default=1,
        ge=0,
        description="Exact number of people on every shift, every day (the solver staffs each shift exactly)",
    )
    max_consecutive_days: int = Field(default=5, ge=1, description="Max working days in a row per employee")
    unavailable: list[Unavailability] = Field(default_factory=list)
    no_morning_after_night: bool = Field(default=True, description="Forbid a morning shift right after a night shift")

    @model_validator(mode="after")
    def _check_consistency(self):
        names = set(self.employees)
        if len(names) != len(self.employees):
            raise ValueError("duplicate employee names")
        for u in self.unavailable:
            if u.employee not in names:
                raise ValueError(f"unknown employee in unavailable: {u.employee}")
            if u.day >= self.num_days:
                raise ValueError(f"day {u.day} is outside the {self.num_days}-day horizon")
        return self


class ScheduleResult(BaseModel):
    status: str = Field(description="OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN")
    assignments: dict[str, dict[int, str]] = Field(
        default_factory=dict, description="employee -> {day index -> shift name}"
    )
    shift_gap: int | None = Field(default=None, description="max minus min number of shifts across employees")
    solve_time_s: float = 0.0
