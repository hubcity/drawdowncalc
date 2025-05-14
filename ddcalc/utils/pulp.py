import pulp

# Helper function to implement min(a, b) using Big M
# result = min(a,b) -> result <= a, result <= b
# a <= result + M*y, b <= result + M*(1-y) where y is binary
def add_min_constraints(prob, result_var, a_var, b_var, M, base_name):
    y = pulp.LpVariable(f"{base_name}_min_ind", cat=pulp.LpBinary)
    prob += result_var <= a_var, f"{base_name}_min_le_a"
    prob += result_var <= b_var, f"{base_name}_min_le_b"
    prob += a_var <= result_var + M * y, f"{base_name}_min_ge_a"
    prob += b_var <= result_var + M * (1 - y), f"{base_name}_min_ge_b"


def add_max_constraints(prob, result_var, a_var, b_var, M, base_name):
    """
    Adds constraints to model: result_var = max(a_var, b_var).

    Uses a binary indicator variable (y) and Big M formulation.
    Logic:
    y = 1 if a_var >= b_var, y = 0 if a_var < b_var (approximated)

    1. result_var >= a_var
    2. result_var >= b_var
    3. Link y:
       a_var - b_var >= -M * (1 - y)
       a_var - b_var <= M * y
    4. Enforce equality:
       result_var <= a_var + M * (1 - y)  (If y=1, result_var <= a_var)
       result_var <= b_var + M * y      (If y=0, result_var <= b_var)

    Args:
        prob: The PuLP LpProblem instance.
        result_var: The LpVariable that will hold max(a_var, b_var).
        a_var: The first LpVariable or expression.
        b_var: The second LpVariable or expression.
        M: A sufficiently large constant (Big M).
        base_name: A string prefix for naming the auxiliary binary variable.
    """
    y = pulp.LpVariable(f"{base_name}_max_ind", cat=pulp.LpBinary)
    # Epsilon not typically needed here unless very strict separation is required
    # epsilon = 1e-4

    # 1 & 2: Basic bounds
    prob += result_var >= a_var, f"{base_name}_max_ge_a"
    prob += result_var >= b_var, f"{base_name}_max_ge_b"

    # 3: Link y to which variable is potentially larger
    # If a >= b, then y=1 is possible/required
    prob += a_var - b_var >= -M * (1 - y), f"{base_name}_max_link1"
    # If a < b (approx a <= b), then y=0 is possible/required
    prob += a_var - b_var <= M * y, f"{base_name}_max_link2"
    # To enforce strict a < b for y=0, use:
    # prob += a_var - b_var <= M * y - epsilon, f"{base_name}_max_link2_strict"

    # 4: Enforce equality using y
    prob += result_var <= a_var + M * (1 - y), f"{base_name}_max_le_a_M"
    prob += result_var <= b_var + M * y, f"{base_name}_max_le_b_M"


def add_if_then_constraint(prob, condition_expr, consequence_expr, M, base_name):
    """
    Adds constraints to model: IF condition_expr > 0 THEN consequence_expr <= 0.

    Uses a binary indicator variable (y) and Big M formulation.
    We model condition_expr > 0 as condition_expr >= epsilon for a small epsilon.

    Logic:
    1. Link y to condition: condition_expr >= epsilon implies y = 1.
       - condition_expr >= epsilon - M * (1 - y)  (If y=1, forces condition_expr >= epsilon)
       - condition_expr <= (epsilon - delta) + M * y # (If y=0, forces condition_expr < epsilon). Use 0 for simplicity:
       - condition_expr <= M * y                 (If y=0, forces condition_expr <= 0)
    2. Enforce consequence if y=1:
       - consequence_expr <= M * (1 - y) (If y=1, forces consequence_expr <= 0)

    Args:
        prob: The PuLP LpProblem instance.
        condition_expr: A PuLP linear expression. The 'IF' part evaluates if this is > 0.
        consequence_expr: A PuLP linear expression. The 'THEN' part enforces this <= 0.
        M: A sufficiently large constant (Big M).
        base_name: A string prefix for naming the auxiliary binary variable.
    """
    y = pulp.LpVariable(f"{base_name}_if_then_ind", cat=pulp.LpBinary)
    # Small positive tolerance to model the strict inequality "> 0"
    # Adjust epsilon if needed based on the scale of your condition_expr values
    epsilon = 1e-4

    # 1. Link y=1 if condition_expr >= epsilon.
    #    If y=1, this forces condition_expr >= epsilon.
    #    If y=0, this becomes condition_expr >= epsilon - M (relaxed).
    prob += condition_expr >= epsilon - M * (1 - y), f"{base_name}_if_link_lower"

    # Link y=0 if condition_expr < epsilon (approximated by condition_expr <= 0)
    #    If y=0, this forces condition_expr <= 0.
    #    If y=1, this becomes condition_expr <= M (relaxed).
    prob += condition_expr <= M * y, f"{base_name}_if_link_upper"
    # Alternative for stricter condition_expr < epsilon when y=0:
    # prob += condition_expr <= (epsilon - delta) + M * y # where delta is another small positive value

    # 2. Enforce consequence_expr <= 0 if y=1.
    #    If y=1, this forces consequence_expr <= 0.
    #    If y=0, this becomes consequence_expr <= M (relaxed).
    prob += consequence_expr <= M * (1 - y), f"{base_name}_then_enforced"