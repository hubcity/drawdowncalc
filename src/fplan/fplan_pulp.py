#!/usr/bin/env python3

import argparse
import re
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
# import scipy.optimize # No longer needed
import pulp                     # Use PuLP

# Required Minimal Distributions from IRA starting with age 73
# last updated for 2024
RMD = [27.4, 26.5, 25.5, 24.6, 23.7, 22.9, 22.0, 21.1, 20.2, 19.4,  # age 72-81
       18.5, 17.7, 16.8, 16.0, 15.3, 14.5, 13.7, 12.9, 12.2, 11.5,  # age 82-91
       10.8, 10.1,  9.5,  8.9,  8.4,  7.8,  7.3,  6.8,  6.4,  6.0,  # age 92-101
        5.6,  5.2,  4.9,  4.6,  4.3,  4.1,  3.9,  3.7,  3.5,  3.4,  # age 102+
        3.3,  3.1,  3.0,  2.9,  2.8,  2.7,  2.5,  2.3,  2.0,  2.0]

def agelist(str_val):
    for x in str_val.split(','):
        m = re.match(r'^(\d+)(-(\d+)?)?$', x)
        if m:
            s = int(m.group(1))
            e = s
            if m.group(2):
                e = m.group(3)
                if e:
                    e = int(e)
                else:
                    e = 120
            for a in range(s,e+1):
                yield a
        else:
            raise Exception("Bad age " + str_val)

class Data:
    def load_file(self, file):
        # global vper # Not needed with PuLP variables
        with open(file) as conffile:
            d = tomllib.loads(conffile.read())
        self.i_rate = 1 + d.get('inflation', 0) / 100       # inflation rate: 2.5 -> 1.025
        self.r_rate = 1 + d.get('returns', 6) / 100         # invest rate: 6 -> 1.06

        self.startage = d['startage']
        self.endage = d.get('endage', max(96, self.startage+5))

        # 2023 tax table (could predict it moves with inflation?)
        # married joint at the moment, can override in config file
        default_taxrates = [[0,      10],
                            [22000,  12],
                            [89450 , 22],
                            [190750, 24],
                            [364200, 32],
                            [462500, 35],
                            [693750, 37]]
        default_stded = 27700
        default_state_taxrates = [[0, 0]]
        default_cg_taxrates = [[0,        0],
                               [89250,   15],
                               [553850,  20]]

        tmp_taxrates = default_taxrates
        tmp_state_taxrates = default_state_taxrates
        tmp_cg_taxrates = default_cg_taxrates

        if 'taxes' in d:
            tmp_taxrates = d['taxes'].get('taxrates', default_taxrates)
            tmp_state_taxrates = d['taxes'].get('state_rate', default_state_taxrates)
            tmp_cg_taxrates = d['taxes'].get('cg_taxrates', default_cg_taxrates)
            if (type(tmp_state_taxrates) is not list):
                tmp_state_taxrates = [[0, tmp_state_taxrates]]
            self.stded = d['taxes'].get('stded', default_stded)
            self.state_stded = d['taxes'].get('state_stded', self.stded)
            self.nii = d['taxes'].get('nii', 250000)
        else:
            self.stded = default_stded
            self.state_stded = default_stded
            self.nii = 250000
        self.taxrates = [[x,y/100.0] for (x,y) in tmp_taxrates]
        cutoffs = [x[0] for x in self.taxrates][1:] + [float('inf')]
        self.taxtable = list(map(lambda x, y: [x[1], x[0], y], self.taxrates, cutoffs))
        self.state_taxrates = [[x,y/100.0] for (x,y) in tmp_state_taxrates]
        cutoffs = [x[0] for x in self.state_taxrates][1:] + [float('inf')]
        self.state_taxtable = list(map(lambda x, y: [x[1], x[0], y], self.state_taxrates, cutoffs))
        self.cg_taxrates = [[x,y/100.0] for (x,y) in tmp_cg_taxrates]
        cutoffs = [x[0] for x in self.cg_taxrates][1:] + [float('inf')]
        self.cg_taxtable = list(map(lambda x, y: [x[1], x[0], y], self.cg_taxrates, cutoffs))

        # vper calculations not needed for PuLP variable setup

        if 'prep' in d:
            self.workyr = d['prep']['workyears']
            self.maxsave = d['prep']['maxsave']
            self.maxsave_inflation = d['prep'].get('inflation', True)
            self.worktax = 1 + d['prep'].get('tax_rate', 25)/100
        else:
            self.workyr = 0
        self.retireage = self.startage + self.workyr
        self.numyr = self.endage - self.retireage

        self.aftertax = d.get('aftertax', {'bal': 0})
        if 'basis' not in self.aftertax:
            self.aftertax['basis'] = 0
        if 'distributions' not in self.aftertax:
            self.aftertax['distributions'] = 0.0
        self.aftertax['distributions'] *= 0.01

        self.IRA = d.get('IRA', {'bal': 0})
        if 'maxcontrib' not in self.IRA:
            self.IRA['maxcontrib'] = 19500 + 7000*2 # Example values, adjust as needed

        self.roth = d.get('roth', {'bal': 0})
        if 'maxcontrib' not in self.roth:
            self.roth['maxcontrib'] = 7000*2 # Example values, adjust as needed
        if 'contributions' not in self.roth:
            self.roth['contributions'] = []
#        else:
#             # Ensure contributions are tuples of (age, amount)
#             self.roth['contributions'] = [(c['age'], c['amount']) for c in self.roth['contributions']]


        self.parse_expenses(d)
        self.sepp_end = max(0, min(self.numyr, 59-self.retireage)) if self.numyr > 0 else 0 # first year *after* SEPP ends
        self.sepp_ratio = 25                       # money per-year from SEPP (bal/ratio)

    def parse_expenses(self, S):
        """ Return array of income/expense per year """
        INC = [0] * self.numyr
        EXP = [0] * self.numyr
        TAX = [0] * self.numyr
        STATE_TAX = [0] * self.numyr
        CEILING = [5_000_000] * self.numyr # Use infinity as default ceiling

        for k,v in S.get('expense', {}).items():
            for age in agelist(v['age']):
                year_idx = age - self.retireage
                if 0 <= year_idx < self.numyr:
                    amount = v['amount']
                    if v.get('inflation'):
                        # Inflation applies from start age
                        amount *= self.i_rate ** (age - self.startage)
                    EXP[year_idx] += amount

        for k,v in S.get('income', {}).items():
            for age in agelist(v['age']):
                year_idx = age - self.retireage
                if 0 <= year_idx < self.numyr:
                    ceil = v.get('ceiling', 5_000_000)
                    if v.get('inflation'):
                        # Inflation applies from start age
                         ceil *= self.i_rate ** (age - self.startage)
                    CEILING[year_idx] = min(CEILING[year_idx], ceil)

                    amount = v['amount']
                    if v.get('inflation'):
                        # Inflation applies from start age
                        amount *= self.i_rate ** (age - self.startage)
                    INC[year_idx] += amount

                    is_taxable = v.get('tax', False)
                    is_state_taxable = v.get('state_tax', is_taxable) # Defaults to federal taxability

                    if is_taxable:
                        TAX[year_idx] += amount
                    if is_state_taxable:
                         STATE_TAX[year_idx] += amount

        self.income = INC
        self.expenses = EXP
        self.taxed_income = TAX             # Renamed for clarity
        self.state_taxed_income = STATE_TAX # Renamed for clarity
        self.income_ceiling = CEILING       # Renamed for clarity


# Helper function to implement min(a, b) using Big M
# result = min(a,b) -> result <= a, result <= b
# a <= result + M*y, b <= result + M*(1-y) where y is binary
def add_min_constraints(prob, result_var, a_var, b_var, M, base_name):
    y = pulp.LpVariable(f"{base_name}_min_ind", cat=pulp.LpBinary)
    prob += result_var <= a_var, f"{base_name}_min_le_a"
    prob += result_var <= b_var, f"{base_name}_min_le_b"
    prob += a_var <= result_var + M * y, f"{base_name}_min_ge_a"
    prob += b_var <= result_var + M * (1 - y), f"{base_name}_min_ge_b"

# Helper function to implement max(0, x) using Big M
# result = max(0, x) -> result >= 0, result >= x
# x <= result + M*y, 0 <= result + M*(1-y) -> result >= x - M*y, result >= -M(1-y)
# result <= x + M*(1-y), result <= 0 + M*y -> result <= x + M(1-y), result <= M*y
def add_max_zero_constraints(prob, result_var, x_var, M, base_name):
    y = pulp.LpVariable(f"{base_name}_max0_ind", cat=pulp.LpBinary)
    prob += result_var >= 0, f"{base_name}_max0_ge_0"
    prob += result_var >= x_var, f"{base_name}_max0_ge_x"
    prob += result_var <= x_var + M * (1 - y), f"{base_name}_max0_le_x"
    prob += result_var <= M * y, f"{base_name}_max0_le_M"

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


# Minimize: c^T * x -> Defined using PuLP objective
# Subject to: A_ub * x <= b_ub -> Defined using PuLP constraints
# Subject to: A_eq * x == b_eq -> Defined using PuLP constraints
def solve_pulp(args, S):
    # Define the problem
    prob = pulp.LpProblem("FinancialPlan", pulp.LpMaximize if args.spend is None else pulp.LpMinimize)

    # --- Define Variables ---
    years_work = range(S.workyr)
    years_retire = range(S.numyr)
    M = 10_000_000 # Big M for indicator constraints

    # --- Single Variables ---
    spending_floor = pulp.LpVariable("SpendingFloor", lowBound=0)
    sepp_reserve = pulp.LpVariable("SEPP_Reserve", lowBound=0) # Amount set aside in IRA at retirement for SEPP

    # --- Work Year Variables ---
    w_f_save = pulp.LpVariable.dicts("Work_Contrib_Save", years_work, lowBound=0)
    w_f_ira = pulp.LpVariable.dicts("Work_Contrib_IRA", years_work, lowBound=0)
    w_f_roth = pulp.LpVariable.dicts("Work_Contrib_Roth", years_work, lowBound=0)

    # --- Retirement Year Variables ---
    # Withdrawals / Conversions
    r_f_save = pulp.LpVariable.dicts("Retire_Withdraw_Save", years_retire, lowBound=0)
    r_f_ira = pulp.LpVariable.dicts("Retire_Withdraw_IRA", years_retire, lowBound=0)
    r_f_roth = pulp.LpVariable.dicts("Retire_Withdraw_Roth", years_retire, lowBound=0)
    r_ira_to_roth = pulp.LpVariable.dicts("Retire_IRA_to_Roth", years_retire, lowBound=0)

    # Balances (Beginning of Year)
    bal_save = pulp.LpVariable.dicts("Balance_Save", years_retire, lowBound=0)
    bal_ira = pulp.LpVariable.dicts("Balance_IRA", years_retire, lowBound=0)
    bal_roth = pulp.LpVariable.dicts("Balance_Roth", years_retire, lowBound=0)
    # Work year balances (needed for constraints linking work->retirement)
    w_bal_save = pulp.LpVariable.dicts("Work_Balance_Save", years_work, lowBound=0)
    w_bal_ira = pulp.LpVariable.dicts("Work_Balance_IRA", years_work, lowBound=0)
    w_bal_roth = pulp.LpVariable.dicts("Work_Balance_Roth", years_work, lowBound=0)


    # Tax Calculation Variables
    non_investment_income = pulp.LpVariable.dicts("Taxable_Income", years_retire, lowBound=0)
    state_taxable_income = pulp.LpVariable.dicts("State_Taxable_Income", years_retire, lowBound=0)
    fed_tax = pulp.LpVariable.dicts("Fed_Tax", years_retire, lowBound=0)
    state_tax = pulp.LpVariable.dicts("State_Tax", years_retire, lowBound=0)
    total_tax = pulp.LpVariable.dicts("Total_Tax", years_retire, lowBound=0)
    cgd = pulp.LpVariable.dicts("Capital_Gains_Distribution", years_retire, lowBound=0) # Capital Gains Distribution Amount

    # Federal Tax Brackets
    std_deduction_amount = pulp.LpVariable.dicts("Std_Deduction_Amount", years_retire, lowBound=0)
#    print("years_retire:", list(years_retire))
#    print("S.taxtable:", list(S.taxtable))
#    print("S.taxtable length:", len(S.taxtable))
    # [(i,j) for i in range(YPER) for j in range(HE)]
    tax_bracket_amount = pulp.LpVariable.dicts("Tax_Bracket_Amount", [(y,j) for y in years_retire for j in range(len(S.taxtable))], lowBound=0)
#    print("tax_bracket_amount keys:", tax_bracket_amount.keys())
#    print("tax_bracket_amount keys length:", len(tax_bracket_amount.keys()))

    # State Tax Brackets
    state_std_deduction_amount = pulp.LpVariable.dicts("State_Std_Deduction_Amount", years_retire, lowBound=0)
    state_tax_bracket_amount = pulp.LpVariable.dicts("State_Tax_Bracket_Amount", [(y,j) for y in years_retire for j in range(len(S.state_taxtable))], lowBound=0)

    # Capital Gains Tax Brackets & NII Tax (using helper variables like original code)
    # For each CG bracket 'j':
    #   cg_income_over_bracket_raw[y, j] = (taxable_income - bracket_low) - used for calculation, can be negative
    #   cg_income_over_bracket[y, j] = max(0, cg_income_over_bracket_raw)
    #   cg_bracket_size[y, j] = (bracket_high - bracket_low)
    #   cg_bracket_income_portion[y, j] = min(cg_income_over_bracket, cg_bracket_size)
    #   cg_bracket_cg_portion[y, j] = amount of CGs taxed in this bracket
    cg_vars = {}
    for y in years_retire:
        for j in range(len(S.cg_taxtable)):
             # Intermediary vars for min/max logic
             cg_vars[y, j, 'raw_over'] = pulp.LpVariable(f"CG_{y}_{j}_RawOverBracket", cat=pulp.LpContinuous) # Can be negative
             cg_vars[y, j, 'over'] = pulp.LpVariable(f"CG_{y}_{j}_OverBracket", lowBound=0) # max(0, raw_over)
             cg_vars[y, j, 'size'] = pulp.LpVariable(f"CG_{y}_{j}_BracketSize", lowBound=0) # fixed later
             cg_vars[y, j, 'income_portion'] = pulp.LpVariable(f"CG_{y}_{j}_IncomePortion", lowBound=0) # min(over, size)
             cg_vars[y, j, 'cg_portion'] = pulp.LpVariable(f"CG_{y}_{j}_CGPortion", lowBound=0) # Amount taxed at this CG rate


    # NII Tax Variables (similar structure to CG)
    #   nii_income_over_bracket_raw[y] = (taxable_income - nii_threshold)
    #   nii_income_over_bracket[y] = max(0, nii_income_over_bracket_raw)
    #   nii_bracket_size[y] = nii_threshold
    #   nii_bracket_income_portion[y] = min(nii_income_over_bracket, nii_bracket_size)
    #   nii_bracket_cg_portion[y] = amount of CGs subject to NII tax
    nii_vars = {}
    for y in years_retire:
         nii_vars[y, 'raw_over'] = pulp.LpVariable(f"NII_{y}_RawOverBracket", cat=pulp.LpContinuous)
         nii_vars[y, 'over'] = pulp.LpVariable(f"NII_{y}_OverBracket", lowBound=0)
         nii_vars[y, 'size'] = pulp.LpVariable(f"NII_{y}_BracketSize", lowBound=0) # fixed later
         nii_vars[y, 'income_portion'] = pulp.LpVariable(f"NII_{y}_IncomePortion", lowBound=0)
         nii_vars[y, 'cg_portion'] = pulp.LpVariable(f"NII_{y}_CGPortion", lowBound=0) # Amount subject to NII


    # --- Objective Function ---
    if args.spend is None:
        # Maximize spending_floor
        prob += spending_floor, "Maximize_Spending"
        # Add constraint to ensure spending_floor is achievable minimum each year
        for y in years_retire:
             i_mul = S.i_rate ** (y + S.workyr)

             spend_cgd = cgd[y-1] if y > 0 else 0 # Cap gains from *last* year are spendable
#             sepp_spend = sepp_reserve / S.sepp_ratio if y < S.sepp_end else 0
             sepp_spend = 0

             # Spending = Withdrawals + Income - Expenses - Taxes
             # We want spending_floor <= yearly spendable amount / inflation multiplier
             prob += (r_f_save[y] + spend_cgd + r_f_ira[y] + r_f_roth[y] + S.income[y] \
                       - S.expenses[y] - total_tax[y] + sepp_spend) >= spending_floor * i_mul, f"Min_Spend_{y}"

    else:
        # Minimize total lifetime taxes (discounted to today's dollars)
        prob += pulp.lpSum(total_tax[y] / (S.i_rate ** (y + S.workyr)) for y in years_retire), "Minimize_Taxes"
        # Fix spending floor
        prob += spending_floor == float(args.spend), "Set_Spending_Floor"
        # Apply fixed spending constraint yearly
        for y in years_retire:
             i_mul = S.i_rate ** (y + S.workyr)
             spend_cgd = cgd[y-1] if y > 0 else 0
             sepp_spend = sepp_reserve / S.sepp_ratio if y < S.sepp_end else 0
             prob += (r_f_save[y] + spend_cgd + r_f_ira[y] + r_f_roth[y] + S.income[y] \
                       - S.expenses[y] - total_tax[y] + sepp_spend) == spending_floor * i_mul, f"Fixed_Spend_{y}"


    if args.roth is not None:
        # Calculate final year Roth balance and constrain it
        final_year = S.numyr - 1
        prob += (bal_roth[final_year] * S.r_rate \
                 - r_f_roth[final_year] * S.r_rate \
                 + r_ira_to_roth[final_year] * S.r_rate \
                 ) == float(args.roth) * (S.i_rate ** (S.numyr + S.workyr)), "Final_Roth_Value" # Inflated target

    # Force SEPP reserve to zero if not enabled (original code implies SEPP is off by default)
    # if not args.sepp: # Assuming args.sepp is available or default is False
    prob += sepp_reserve == 0, "Force_SEPP_Zero"

    # --- Constraints ---

    # --- Work Year Constraints ---
    for y in years_work:
        i_mul = S.i_rate ** y
        max_save_limit = S.maxsave * i_mul if S.maxsave_inflation else S.maxsave
        ira_contrib_limit = S.IRA['maxcontrib'] * i_mul # Assuming IRA limit inflates
        roth_contrib_limit = S.roth['maxcontrib'] * i_mul # Assuming Roth limit inflates

        # Contribution limits
        prob += w_f_save[y] * S.worktax + w_f_ira[y] + w_f_roth[y] * S.worktax <= max_save_limit, f"Work_MaxSave_{y}"
        prob += w_f_ira[y] <= ira_contrib_limit, f"Work_MaxIRA_{y}"
        prob += w_f_roth[y] <= roth_contrib_limit, f"Work_MaxRoth_{y}"

        # Work year balance calculations (Beginning of Year)
        if y == 0:
            prob += w_bal_save[y] == S.aftertax['bal'], f"Work_InitSaveBal_{y}"
            prob += w_bal_ira[y] == S.IRA['bal'], f"Work_InitIRABal_{y}"
            prob += w_bal_roth[y] == S.roth['bal'], f"Work_InitRothBal_{y}"
        else:
            prob += w_bal_save[y] == (w_bal_save[y-1] + w_f_save[y-1]) * S.r_rate, f"Work_SaveBal_{y}"
            # Assuming no CGD during work years for simplicity matching original logic
            # prob += w_bal_save[y] == (w_bal_save[y-1] + w_f_save[y-1]) * (S.r_rate - S.aftertax['distributions']), f"Work_SaveBal_{y}"

            prob += w_bal_ira[y] == (w_bal_ira[y-1] + w_f_ira[y-1]) * S.r_rate, f"Work_IRABal_{y}"
             # No IRA->Roth conversions during work years in original logic
            prob += w_bal_roth[y] == (w_bal_roth[y-1] + w_f_roth[y-1]) * S.r_rate, f"Work_RothBal_{y}"


    # --- Retirement Year Constraints ---
    for y in years_retire:
        i_mul = S.i_rate ** (y + S.workyr)
        age = y + S.retireage

        # Calculate basis (as used in state tax, NII, CG calcs)
        if S.aftertax['basis'] > 0:
            basis = 1 - (S.aftertax['basis'] /
                         (S.aftertax['bal'] *
                          (S.r_rate-S.aftertax['distributions'])**(y + S.workyr)))
            if basis < 0:
                basis = 0
        else:
            basis = 1

#        basis = 1
#        if S.aftertax['basis'] > 0 and S.aftertax['bal'] > 0:
#             current_bal_est = S.aftertax['bal'] * (S.r_rate - S.aftertax['distributions'])**(y + S.workyr) # Estimate EOY balance
#             if current_bal_est > 0:
#                   basis = 1 - max(0, min(1, S.aftertax['basis'] / current_bal_est)) # Basis is (1 - gain_ratio)
#        else:
#             basis = 1 if S.aftertax['bal'] == 0 else 0 # All basis if no initial balance? Or zero basis if initial balance? Needs check. Assume 0 basis if bal>0, basis=0

#        print("basis:", basis)
        taxable_part_of_f_save = basis # Portion of f_save that is taxable gain

        # Balance Calculations (Beginning of Year y)
        if y == 0:
            # Link from last work year or initial if no work years
            last_bal_save = w_bal_save[S.workyr-1] + w_f_save[S.workyr-1] if S.workyr > 0 else S.aftertax['bal']
            last_bal_ira = w_bal_ira[S.workyr-1] + w_f_ira[S.workyr-1] if S.workyr > 0 else S.IRA['bal']
            last_bal_roth = w_bal_roth[S.workyr-1] + w_f_roth[S.workyr-1] if S.workyr > 0 else S.roth['bal']

            prob += bal_save[y] == last_bal_save, f"Retire_InitSaveBal_{y}"
            # prob += bal_save[y] == last_bal_save * (S.r_rate - S.aftertax['distributions']), f"Retire_InitSaveBal_{y}" # With CGD
            prob += bal_ira[y] == last_bal_ira - sepp_reserve, f"Retire_InitIRABal_{y}" # Subtract SEPP reserve at retirement start
            prob += bal_roth[y] == last_bal_roth, f"Retire_InitRothBal_{y}"
        else:
            sepp_draw = 0
            prob += bal_save[y] == (bal_save[y-1] - r_f_save[y-1]) * S.r_rate - cgd[y-1], f"Retire_SaveBal_{y}" # Add previous year's CGD *after* growth
            # prob += bal_save[y] == (bal_save[y-1] - r_f_save[y-1]) * (S.r_rate - S.aftertax['distributions']), f"Retire_SaveBal_{y}" # With CGD rate
            prob += bal_ira[y] == (bal_ira[y-1] - r_f_ira[y-1] - r_ira_to_roth[y-1] - sepp_draw) * S.r_rate, f"Retire_IRABal_{y}"
            prob += bal_roth[y] == (bal_roth[y-1] - r_f_roth[y-1] + r_ira_to_roth[y-1]) * S.r_rate, f"Retire_RothBal_{y}"

        # Capital Gains Distribution Calculation
        prob += cgd[y] == (bal_save[y] - r_f_save[y]) * S.r_rate * S.aftertax['distributions'], f"CGD_Calc_{y}"
        # Original logic seems different: Cgd = end_of_year_balance * distribution_rate
        # EOY balance = (BOY_balance - withdrawal) * growth_rate
        # prob += cgd[y] == (bal_save[y] - r_f_save[y]) * S.r_rate * S.aftertax['distributions'], f"CGD_Calc_{y}"
        # Or based on BOY balance: prob += cgd[y] == bal_save[y] * S.r_rate * S.aftertax['distributions'] ? Check original logic carefully.
        # The original seemed to calculate cgd[y] based on BOY balance bal_save[y] plus contributions fsave[y] for that year, then apply rate.
        # Let's stick closer to original: cgd[y] = (bal_save[y] + r_f_save[y]) * S.r_rate * S.aftertax['distributions'] ?? Seems wrong.
        # Try: cgd[y] = (bal_save[y] * S.r_rate - r_f_save[y]*S.r_rate)* S.aftertax['distributions'] ?
        # Back to original AE: cgd = basis*fsave + fira + ira2roth <= ceiling ??? No, AE: cgd[y] = (bal_save[y] + fsave[y]) * r_rate * dist_rate
        # AE: cgd[y] = (bal_save[y] - r_f_save[y]) * S.r_rate * S.aftertax['distributions'] -- Let's use this, assuming fsave is withdrawal.

        # Total Taxable Income Calculation (Federal) = IRA Withdrawals + Conversions + Taxable External Income
        prob += non_investment_income[y] == r_f_ira[y] + r_ira_to_roth[y] + S.taxed_income[y], f"NonInvestmentIncome_{y}"


        # --- Federal Tax Calculation ---
        # Limit amounts in std deduction and brackets
        prob += std_deduction_amount[y] <= S.stded * i_mul, f"MaxStdDed_{y}"

        # DEBUG: Print keys just before the loop to ensure definition was okay
#        if y == 0 and j == 0: # Print only once per run
#             print("DEBUG: tax_bracket_amount keys sample:", list(tax_bracket_amount.keys())[:5])

        for j, (rate, low, high) in enumerate(S.taxtable):
             bracket_size = (high - low) * i_mul if high != float('inf') else M # Use Big M for unbounded top bracket
#             print("low, high, bracket_size:", low, high, bracket_size)

             # --- DEBUG PRINTS START ---
#             print(f"DEBUG: Checking y={y}, j={j}")
             current_key = (y, j)
             if current_key not in tax_bracket_amount:
                 print(f"ERROR: Key ({y}, {j}) not found in tax_bracket_amount dictionary!")
                 # Optional: print all keys to see what's there
                 print("Available keys:", tax_bracket_amount.keys())
                 # You might want to raise an exception here or handle it
                 raise KeyError(f"Key ({y}, {j}) was expected but not found in tax_bracket_amount.")
#             else:
#                 print(f"DEBUG: Key ({y}, {j}) found. Bracket size: {bracket_size}")
             # --- DEBUG PRINTS END ---

             # Original line where error occurs:
             prob += tax_bracket_amount[y, j] <= bracket_size, f"MaxTaxBracket_{y}_{j}"


        # Sum of amounts in brackets must equal total taxable income
        prob += std_deduction_amount[y] + pulp.lpSum(tax_bracket_amount[y, j] for j in range(len(S.taxtable))) == non_investment_income[y], f"SumTaxBrackets_{y}"

        # Calculate Federal Tax (sum across brackets + penalty + CG tax + NII tax)
        fed_tax_calc = pulp.lpSum(tax_bracket_amount[y, j] * S.taxtable[j][0] for j in range(len(S.taxtable)))
        if age < 59:
             fed_tax_calc += r_f_ira[y] * 0.10 # 10% penalty on early IRA withdrawal

        # Add Capital Gains Tax (calculated below)
        fed_tax_calc += pulp.lpSum(cg_vars[y, j, 'cg_portion'] * S.cg_taxtable[j][0] for j in range(len(S.cg_taxtable)))

        # Add NII Tax (calculated below) - NII applies to the lesser of net investment income or MAGI over threshold
        # Investment Income = cgd + taxable_part_of_f_save (approx)
        # MAGI = taxable_income + other adjustments (simplified here)
        # NII Tax = 0.038 * min(Investment Income, max(0, MAGI - NII_Threshold))
        # The original code uses a bracket splitting method for NII based on MAGI vs threshold.
        # NII is applied to cg_vars[y, 1, 'cg_portion']? Check original: row[n_nii+1*cg_vper+8] = -0.038 -> NII applies to the CG portion in the 2nd NII bracket?
        fed_tax_calc += nii_vars[y, 'cg_portion'] * 0.038 # Add NII tax based on the allocated portion

        # Tax Bump if applicable
        if args.bumptax and args.bumpstart and y >= float(args.bumpstart):
             fed_tax_calc += pulp.lpSum(tax_bracket_amount[y, j] * (float(args.bumptax) / 100.0) for j in range(len(S.taxtable)))

        prob += fed_tax[y] == fed_tax_calc, f"FedTaxCalc_{y}"

        #if (r_ira_to_roth[y] > 0):
        #    prob += r_f_roth[y] - r_ira_to_roth[y] <= 0, f"IRA_Roth_Transfer_{y}"
        ##############################
        add_if_then_constraint(prob, r_ira_to_roth[y], r_f_roth[y] - r_ira_to_roth[y], M, f"AvoidNonsensical_{y}")

        # State Taxable Income Calculation = Fed Taxable Income + Taxable Cap Gains - State Deduction differences?
        # Original: state_taxable = fira + ira2roth + basis*fsave + cgd + state_taxed_extra
        prob += state_taxable_income[y] == r_f_ira[y] + r_ira_to_roth[y] + r_f_save[y] * taxable_part_of_f_save + cgd[y] + S.state_taxed_income[y], f"StateTaxableIncome_{y}"

        # State Tax Calculation
        prob += state_std_deduction_amount[y] <= S.state_stded * i_mul, f"MaxStateStdDed_{y}"
        for j, (rate, low, high) in enumerate(S.state_taxtable):
             bracket_size = (high - low) * i_mul if high != float('inf') else M
             prob += state_tax_bracket_amount[y, j] <= bracket_size, f"MaxStateTaxBracket_{y}_{j}"

        prob += state_std_deduction_amount[y] + pulp.lpSum(state_tax_bracket_amount[y, j] for j in range(len(S.state_taxtable))) == state_taxable_income[y], f"SumStateTaxBrackets_{y}"

        prob += state_tax[y] == pulp.lpSum(state_tax_bracket_amount[y, j] * S.state_taxtable[j][0] for j in range(len(S.state_taxtable))), f"StateTaxCalc_{y}"


        # Capital Gains & NII Tax Logic (complex part, translating Big M)
        total_cap_gains = cgd[y] + r_f_save[y] * taxable_part_of_f_save

        # --- CG Bracket Calculations ---
        for j, (rate, low, high) in enumerate(S.cg_taxtable):
             low_adj = low * i_mul
             high_adj = high * i_mul if high != float('inf') else M
             bracket_size = high_adj - low_adj

             # cg_raw_over = taxable_income - bracket_low (adjusted for non-CG income already taxed)
             # Original: cg_raw_over = fira + ira2roth + taxed_extra - stded_amount - bracket_low
             # Simplified: cg_raw_over = taxable_income - std_deduction_amount - bracket_low ? Check original carefully.
             # AE: row[n_fira]=1; row[n_ira2roth]=1; row[n_stded]=-1; row[cg3]=1; row[cg2]=-1; AE += [row]; be += [low*i_mul - S.taxed[year]]
             # This means: cg2 - cg3 == (fira + ira2roth + taxed_extra) - stded - low*i_mul
             taxable_income_eff = non_investment_income[y] - std_deduction_amount[y] # Income above std deduction
             # prob += cg_vars[y, j, 'raw_over'] == non_investment_income[y] - - low_adj, f"CG_RawOver_{y}_{j}"
             prob += cg_vars[y, j, 'raw_over'] == taxable_income_eff - low_adj, f"CG_RawOver_{y}_{j}" # Alternative using effective income

             # cg_over = max(0, cg_raw_over)
             add_max_zero_constraints(prob, cg_vars[y, j, 'over'], cg_vars[y, j, 'raw_over'], M, f"CG_{y}_{j}")

             # cg_size = bracket_size
             prob += cg_vars[y, j, 'size'] == bracket_size, f"CG_Size_{y}_{j}"

             # cg_income_portion = min(cg_over, cg_size)
             add_min_constraints(prob, cg_vars[y, j, 'income_portion'], cg_vars[y, j, 'over'], cg_vars[y, j, 'size'], M, f"CG_{y}_{j}_IncPort")

             # Portion of bracket available for CGs = size - income_portion
             # cg_cg_portion <= available_portion
             prob += cg_vars[y, j, 'cg_portion'] <= cg_vars[y, j, 'size'] - cg_vars[y, j, 'income_portion'], f"CG_CGPortionLimit_{y}_{j}"
             


        # Sum of CG portions across all brackets must equal total capital gains
        prob += pulp.lpSum(cg_vars[y, j, 'cg_portion'] for j in range(len(S.cg_taxtable))) == total_cap_gains, f"Sum_CG_Portions_{y}"

        # --- NII Calculation (similar logic) ---
        nii_threshold_adj = S.nii # NII threshold typically not inflation adjusted
        # magi_approx = taxable_income[y] # Simplified MAGI for this calculation
        magi_approx = r_f_ira[y] + r_ira_to_roth[y] + S.taxed_income[y] + total_cap_gains # Original seems based on non-investment income part (NO!)
        # NII Raw Over = MAGI - Threshold
        prob += nii_vars[y, 'raw_over'] == magi_approx - nii_threshold_adj, f"NII_RawOver_{y}"

        # NII Over = max(0, raw_over)
        add_max_zero_constraints(prob, nii_vars[y, 'over'], nii_vars[y, 'raw_over'], M, f"NII_{y}")

        # NII CG Portion = min(Total Cap Gains, NII Over)
        add_min_constraints(prob, nii_vars[y, 'cg_portion'], nii_vars[y, 'over'], total_cap_gains, M, f"NII_{y}_CGPort")

        # Total Tax Calculation
        prob += total_tax[y] == fed_tax[y] + state_tax[y], f"TotalTaxCalc_{y}"

        # Income Ceiling Constraint (Original A+b constraint)
        # fira + ira2roth + taxed_extra + basis*fsave + cgd <= ceiling
        if (S.income_ceiling[y] < 5000000):
            prob += r_f_ira[y] + r_ira_to_roth[y] + S.taxed_income[y] + r_f_save[y] * taxable_part_of_f_save + cgd[y] <= S.income_ceiling[y], f"IncomeCeiling_{y}"
            print("S.income_ceiling[y]:", S.income_ceiling[y])

        # Ensure Balances are Non-Negative (implicitly handled by lowBound=0, but explicit doesn't hurt)
        prob += bal_save[y] >= 0, f"SaveNonNeg_{y}"
        prob += bal_ira[y] >= 0, f"IRANonNeg_{y}"
        prob += bal_roth[y] >= 0, f"RothNonNeg_{y}"

        prob += bal_roth[y] >= r_f_roth[y], f"RothWithdrawNonNeg_{y}" # Roth withdrawals must not exceed balance        

        # RMD Constraint (age >= 73)
        if age >= 73:
            rmd_factor = RMD[age - 72] # Get factor for current age
            # RMD amount = Previous Year End IRA Balance / rmd_factor
            # Previous Year End = bal_ira[y] / S.r_rate (approx BOY balance / growth)
            # Or, more accurately: bal_ira[y-1] - r_f_ira[y-1] - r_ira_to_roth[y-1] - sepp_draw_prev
            prev_year_end_ira = 0
            if y == 0:
                last_bal_ira = w_bal_ira[S.workyr-1] + w_f_ira[S.workyr-1] if S.workyr > 0 else S.IRA['bal']
                prev_year_end_ira = last_bal_ira # Approx EOY before retirement
            else:
                 sepp_draw_prev = sepp_reserve / S.sepp_ratio if (y-1) < S.sepp_end else 0
                 prev_year_end_ira = bal_ira[y-1] - r_f_ira[y-1] - r_ira_to_roth[y-1] - sepp_draw_prev

            rmd_required = prev_year_end_ira / rmd_factor
            # Withdrawal must meet RMD: r_f_ira[y] >= rmd_required
            prob += r_f_ira[y] >= rmd_required, f"RMD_{y}"


        # Roth Contribution Aging (5-year rule for conversions, contributions assumed available)
        # Before age 59.5, withdrawals limited to contributions + qualified conversions
        if age < 59: # Use 59 as threshold like original
             # Withdrawals (r_f_roth) <= Basis
             # Basis = Initial Contributions + Work Contributions + Conversions older than 5 years
             aged_conversions = pulp.lpSum(r_ira_to_roth[conv_y] for conv_y in range(max(0, y - 5))) # Sum conversions from >= 5 years ago

             # Calculate contributions basis available in year y
             initial_contrib_basis = 0
             for contrib_age, contrib_amount in S.roth['contributions']:
                  # Assume contributions are available immediately (or check 5-year rule if needed)
                  initial_contrib_basis += contrib_amount # Simplification: Assume all initial contribs are withdrawable

             work_contrib_basis = pulp.lpSum(w_f_roth[work_y] for work_y in years_work) # All work contributions

             total_basis = initial_contrib_basis + work_contrib_basis + aged_conversions
             prob += r_f_roth[y] <= total_basis, f"RothBasisLimit_{y}"


    # Final Balance Non-Negative Constraints (End of last year)
    final_year = S.numyr - 1
    if final_year >=0 :
        # EOY = (BOY - Withdrawals + Conversions) * Growth + CGD
        sepp_draw_final = sepp_reserve / S.sepp_ratio if final_year < S.sepp_end else 0

        prob += (bal_save[final_year] - r_f_save[final_year]) * S.r_rate + cgd[final_year] >= 0, "FinalSaveNonNeg"
        prob += (bal_ira[final_year] - r_f_ira[final_year] - r_ira_to_roth[final_year] - sepp_draw_final) * S.r_rate >= 0, "FinalIRANonNeg"
        prob += (bal_roth[final_year] - r_f_roth[final_year] + r_ira_to_roth[final_year]) * S.r_rate >= 0, "FinalRothNonNeg"

        # SEPP Reserve Constraint: IRA balance at SEPP end must be >= reserved amount grown
        if S.sepp_end > 0 and S.sepp_end <= S.numyr:
            sepp_end_year_idx = S.sepp_end -1 # Index of the last year SEPP applies
            # We need BOY balance of the year *after* SEPP ends
            if S.sepp_end < S.numyr:
                 prob += bal_ira[S.sepp_end] >= sepp_reserve * (S.r_rate ** S.sepp_end), f"SEPPEndBalance"
            else: # If SEPP ends in the last year, check final balance
                 prob += (bal_ira[final_year] - r_f_ira[final_year] - r_ira_to_roth[final_year] - sepp_draw_final) * S.r_rate >= sepp_reserve * (S.r_rate ** S.sepp_end), "SEPPEndBalanceFinal"


    prob.writeLP("debug.lp")
    # --- Solve ---
    solver_options = {}
    if args.timelimit:
        solver_options['timeLimit'] = float(args.timelimit)
    if args.verbose:
        solver_options['msg'] = 1 # Show solver output
    else:
         solver_options['msg'] = 0

    # Choose a solver (CBC is default, bundled with PuLP)
    # solver = pulp.PULP_CBC_CMD(**solver_options)
    # Or use GLPK if installed:
    # solver = pulp.GLPK_CMD(**solver_options)
    # Or others like CPLEX, GUROBI if configured
    solver = pulp.PULP_CBC_CMD(timeLimit=float(args.timelimit) if args.timelimit else 300, msg=args.verbose)


    print("Starting PuLP solver...")
    prob.solve(solver)

    # --- Process Results ---
    status = pulp.LpStatus[prob.status]
    print(f"Solver Status: {status}")

    if prob.status not in [pulp.LpStatusOptimal, pulp.LpStatusNotSolved]: # Not Solved can occur with time limit but might have a feasible solution
         print("Solver did not find an optimal solution.")
         if prob.status == pulp.LpStatusInfeasible:
              print("Problem is infeasible.")
         elif prob.status == pulp.LpStatusUnbounded:
               print("Problem is unbounded.")
         # Consider returning None or raising an error if no solution found
         # For now, return None, handle this in main
         return None, None, None # Indicate failure


    # Extract results into a dictionary or similar structure for printing
    results = {
        'spending_floor': spending_floor.varValue,
        'sepp_reserve': sepp_reserve.varValue,
        'work': {},
        'retire': {},
        'status': status
    }

    for y in years_work:
        results['work'][y] = {
            'f_save': w_f_save[y].varValue,
            'f_ira': w_f_ira[y].varValue,
            'f_roth': w_f_roth[y].varValue,
            'bal_save': w_bal_save[y].varValue,
            'bal_ira': w_bal_ira[y].varValue,
            'bal_roth': w_bal_roth[y].varValue,
        }

    for y in years_retire:
        results['retire'][y] = {
            'f_save': r_f_save[y].varValue,
            'f_ira': r_f_ira[y].varValue,
            'f_roth': r_f_roth[y].varValue,
            'ira_to_roth': r_ira_to_roth[y].varValue,
            'bal_save': bal_save[y].varValue,
            'bal_ira': bal_ira[y].varValue,
            'bal_roth': bal_roth[y].varValue,
            'taxable_income': non_investment_income[y].varValue,
            'state_taxable_income': state_taxable_income[y].varValue,
            'fed_tax': fed_tax[y].varValue,
            'state_tax': state_tax[y].varValue,
            'total_tax': total_tax[y].varValue,
            'cgd': cgd[y].varValue,
            # Include tax bracket details if needed for output
            'std_ded_amount': std_deduction_amount[y].varValue,
            'state_std_ded_amount': state_std_deduction_amount[y].varValue,
        }
        # Add bracket amounts
        results['retire'][y]['tax_brackets'] = [tax_bracket_amount[y, j].varValue for j in range(len(S.taxtable))]
        results['retire'][y]['state_tax_brackets'] = [state_tax_bracket_amount[y, j].varValue for j in range(len(S.state_taxtable))]


    if args.roth is not None:
        final_year = S.numyr - 1
        if final_year >= 0:
             roth_value = (results['retire'][final_year]['bal_roth'] \
                            - results['retire'][final_year]['f_roth'] \
                            + results['retire'][final_year]['ira_to_roth']) * S.r_rate
             i_mul_final = S.i_rate ** (S.numyr + S.workyr)
             print(f"The ending value, including final year investment returns, of your Roth account will be {roth_value:.0f}")
             print(f"That is equivalent to {roth_value / i_mul_final:.0f} in today's dollars")


    # Return the results structure instead of the raw array
    return results, S, prob # Pass S and prob back for potential inspection


def print_ascii(results, S):
    if results is None:
        print("No solution found to print.")
        return

    print(f"Solver Status: {results['status']}")
    spending_floor_val = results['spending_floor'] if results['spending_floor'] is not None else 0
    sepp_reserve_val = results['sepp_reserve'] if results['sepp_reserve'] is not None else 0
    print(f"Yearly spending floor (today's dollars) <= {spending_floor_val:.0f}")
    print(f"SEPP amount reserved = {sepp_reserve_val:.0f}")
    if S.sepp_ratio > 0:
        print(f" Implied yearly SEPP withdrawal = {sepp_reserve_val / S.sepp_ratio:.0f}")
    print()

    if S.workyr > 0:
        print((" age" + " %6s" * 6) %
              ("bSAVE", "cSAVE", "bIRA", "cIRA", "bROTH", "cROTH")) # b=balance, c=contribution
    for year in range(S.workyr):
        w_res = results['work'][year]
        bal_save = w_res['bal_save'] if w_res['bal_save'] is not None else 0
        f_save = w_res['f_save'] if w_res['f_save'] is not None else 0
        bal_ira = w_res['bal_ira'] if w_res['bal_ira'] is not None else 0
        f_ira = w_res['f_ira'] if w_res['f_ira'] is not None else 0
        bal_roth = w_res['bal_roth'] if w_res['bal_roth'] is not None else 0
        f_roth = w_res['f_roth'] if w_res['f_roth'] is not None else 0

        print((" %3d:" + " %6.0f" * 6) %
              (year + S.startage,
               bal_save / 1000, f_save / 1000,
               bal_ira / 1000, f_ira / 1000,
               bal_roth / 1000, f_roth / 1000))
    print("-" * (5 + 7*6)) # Separator

    print((" age" + " %6s" * 12) % # Adjusted column count
          ("bSAVE", "wSAVE", "bIRA", "wIRA", "SEPP", "bROTH", "wROTH", "IRA2R",
           "TxRate", "Tax", "Spend", "CGD")) # b=balance, w=withdrawal/conversion
    ttax = 0.0
    tspend = 0.0 # Total spending in today's dollars

    for year in range(S.numyr):
        r_res = results['retire'][year]
        age = year + S.retireage
        i_mul = S.i_rate ** (year + S.workyr)

        # Extract values, handling None if solver failed partially
        bal_save = r_res.get('bal_save', 0)
        f_save = r_res.get('f_save', 0)
        bal_ira = r_res.get('bal_ira', 0)
        f_ira = r_res.get('f_ira', 0)
        bal_roth = r_res.get('bal_roth', 0)
        f_roth = r_res.get('f_roth', 0)
        ira2roth = r_res.get('ira_to_roth', 0)
        cgd = r_res.get('cgd', 0)
        tax = r_res.get('total_tax', 0)
        taxable_inc = r_res.get('taxable_income',0)
        std_ded_amount = r_res.get('std_ded_amount',0)
        state_taxable_inc = r_res.get('state_taxable_income', 0)
        state_std_ded_amount = r_res.get('state_std_ded_amount',0)


        sepp_spend = sepp_reserve_val / S.sepp_ratio if year < S.sepp_end and S.sepp_ratio > 0 else 0

        # Calculate effective tax rate (simplified)
        inc_above_std = max(0, taxable_inc - std_ded_amount)
        state_inc_above_std = max(0, state_taxable_inc - state_std_ded_amount)

        fed_rate = 0
        if inc_above_std > 0:
             # Find highest bracket used
             for j in range(len(S.taxtable) - 1, -1, -1):
                   if r_res.get('tax_brackets', [])[j] > 1e-6: # Check if bracket amount is non-zero
                        fed_rate = S.taxtable[j][0]
                        break
        state_rate = 0
        if state_inc_above_std > 0:
             for j in range(len(S.state_taxtable) - 1, -1, -1):
                   if r_res.get('state_tax_brackets', [])[j] > 1e-6:
                        state_rate = S.state_taxtable[j][0]
                        break
        rate = fed_rate + state_rate

        # Calculate yearly spending = Withdrawals + Income - Expenses - Taxes
        spend_cgd = results['retire'][year-1]['cgd'] if year > 0 and 'cgd' in results['retire'][year-1] else 0 # From last year
        spending = f_save + spend_cgd + f_ira + f_roth + S.income[year] - S.expenses[year] - tax + sepp_spend

        ttax += tax / i_mul                     # totals in today's dollars
        tspend += spending / i_mul              # totals in today's dollars
        div_by = 1000
        print((" %3d:" + " %6.0f" * 12) %
              (age,
               bal_save / div_by, f_save / div_by,
               bal_ira / div_by, f_ira / div_by, sepp_spend / div_by,
               bal_roth / div_by, f_roth / div_by, ira2roth / div_by,
               rate * 100, tax / div_by, spending / div_by, cgd / div_by))

    print("\nTotal spending (today's dollars): %.0f" % tspend)
    print("Total tax (today's dollars): %.0f" % ttax)
    if tspend + ttax > 0:
        print(" Avg Tax Rate: %.1f%%" % (100 * ttax / (tspend + ttax)))


def print_csv(results, S):
    if results is None:
        print("No solution found to print.")
        return

    print(f"Solver Status,{results['status']}")
    spending_floor_val = results['spending_floor'] if results['spending_floor'] is not None else 0
    print(f"spend goal,{spending_floor_val:.0f}")
    print(f"savings,{S.aftertax['bal']},{S.aftertax['basis']}")
    print(f"ira,{S.IRA['bal']}")
    print(f"roth,{S.roth['bal']}")
    sepp_reserve_val = results['sepp_reserve'] if results['sepp_reserve'] is not None else 0
    print(f"sepp_reserve,{sepp_reserve_val:.0f}")


    print("age,bal_save,wd_save,bal_ira,wd_ira,bal_roth,wd_roth,ira_to_roth,income,expense,cgd,fed_tax,state_tax,total_tax,spend_goal_inf,actual_spend_inf")
    for year in range(S.numyr):
        r_res = results['retire'][year]
        age = year + S.retireage
        i_mul = S.i_rate ** (year + S.workyr)

        bal_save = r_res.get('bal_save', 0)
        f_save = r_res.get('f_save', 0)
        bal_ira = r_res.get('bal_ira', 0)
        f_ira = r_res.get('f_ira', 0)
        bal_roth = r_res.get('bal_roth', 0)
        f_roth = r_res.get('f_roth', 0)
        ira2roth = r_res.get('ira_to_roth', 0)
        cgd = r_res.get('cgd', 0)
        fed_tax = r_res.get('fed_tax', 0)
        state_tax = r_res.get('state_tax', 0)
        total_tax = r_res.get('total_tax', 0)

        sepp_spend = sepp_reserve_val / S.sepp_ratio if year < S.sepp_end and S.sepp_ratio > 0 else 0
        spend_cgd = results['retire'][year-1]['cgd'] if year > 0 and 'cgd' in results['retire'][year-1] else 0
        spending_inf = f_save + spend_cgd + f_ira + f_roth + S.income[year] - S.expenses[year] - total_tax + sepp_spend
        spend_goal_inf = spending_floor_val * i_mul


        print(f"{age},{bal_save:.0f},{f_save:.0f},{bal_ira:.0f},{f_ira:.0f},{bal_roth:.0f},{f_roth:.0f},{ira2roth:.0f},{S.income[year]:.0f},{S.expenses[year]:.0f},{cgd:.0f},{fed_tax:.0f},{state_tax:.0f},{total_tax:.0f},{spend_goal_inf:.0f},{spending_inf:.0f}")


def main():
    # Instantiate the parser
    parser = argparse.ArgumentParser(description="Financial planning using Linear Programming (PuLP version)")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Extra output from solver")
    # parser.add_argument('--sepp', action='store_true', # SEPP logic needs review
    #                     help="Enable SEPP processing (NEEDS REVIEW)")
    parser.add_argument('--csv', action='store_true', help="Generate CSV outputs")
    # parser.add_argument('--validate', action='store_true', # Validation logic removed
    #                     help="compare single run to separate runs")
    parser.add_argument('--timelimit',
                        help="After given seconds return the best answer found (solver dependent)")
    parser.add_argument('--bumpstart', type=int, # Changed type to int
                        help="Start tax bump after given retirement years (e.g., 10)")
    parser.add_argument('--bumptax', type=float, # Changed type to float
                        help="Increase taxes charged in all federal income tax brackets (as percentage points, e.g., 5 for 5%%)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--spend', type=float, # Changed type to float
                        help="Set fixed yearly spending (today's dollars); minimizes taxes.")
    group.add_argument('--roth', type=float, # Changed type to float
                       help="Specify the target final Roth balance (today's dollars)")
    parser.add_argument('conffile', help="Configuration file in TOML format")
    args = parser.parse_args()

    if bool(args.bumptax) != bool(args.bumpstart): # Use != for XOR check
        parser.error('--bumptax and --bumpstart must be given together')


    S = Data()
    S.load_file(args.conffile)

    # Solve using PuLP
    results, S_out, prob = solve_pulp(args, S) # Get S back in case it was modified (it shouldn't be here)

    if results is None:
        print("Failed to solve the problem.")
        # Optionally print problem formulation if verbose/debugging
        # prob.writeLP("fplan_debug.lp")
        # print("LP problem written to fplan_debug.lp")
        exit(1)


    if args.csv:
        print_csv(results, S_out)
    else:
        print_ascii(results, S_out)

    # Validation logic would need significant rewrite for PuLP variables

if __name__== "__main__":
    main()