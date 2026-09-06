"""Strategy formulas.

Each strategy is a pure function from match state to a result object. They
take their tunable coefficients in a `WeightSet`, never read configuration
themselves, and never mutate their inputs.
"""

from kalchas_core.strategies import (
    delta_5min,
    delta_goal,
    omega,
    pressure_index,
    rule_of_three,
)

__all__ = ["delta_5min", "delta_goal", "omega", "pressure_index", "rule_of_three"]
