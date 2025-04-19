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
        self.retireage = self.startage
        self.numyr = self.endage - self.retireage

        self.aftertax = d.get('aftertax', {'bal': 0})
        if 'basis' not in self.aftertax:
            self.aftertax['basis'] = 0
        if 'distributions' not in self.aftertax:
            self.aftertax['distributions'] = 0.0
        self.aftertax['distributions'] *= 0.01

        self.IRA = d.get('IRA', {'bal': 0})

        self.roth = d.get('roth', {'bal': 0})
        if 'contributions' not in self.roth:
            self.roth['contributions'] = []

        self.parse_expenses(d)

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
    years_retire = range(S.numyr)
    M = 100_000_000 # Big M for indicator constraints

    # --- Single Variables ---
    spending_floor = pulp.LpVariable("SpendingFloor", lowBound=0)

    # --- Retirement Year Variables ---
    # Withdrawals / Conversions
    f_save = pulp.LpVariable.dicts("Retire_Withdraw_Save", years_retire, lowBound=0)
    f_ira = pulp.LpVariable.dicts("Retire_Withdraw_IRA", years_retire, lowBound=0)
    f_roth = pulp.LpVariable.dicts("Retire_Withdraw_Roth", years_retire, lowBound=0)
    ira_to_roth = pulp.LpVariable.dicts("Retire_IRA_to_Roth", years_retire, lowBound=0)
    conversion_convience_fee = pulp.LpVariable.dicts("Conversion_Convenience_Fee", years_retire, lowBound=0) # Fee for converting to Roth

    # Balances (Beginning of Year)
    bal_save = pulp.LpVariable.dicts("Balance_Save", years_retire, lowBound=0)
    bal_ira = pulp.LpVariable.dicts("Balance_IRA", years_retire, lowBound=0)
    bal_roth = pulp.LpVariable.dicts("Balance_Roth", years_retire, lowBound=0)

    # Tax Calculation Variables
    non_investment_income = pulp.LpVariable.dicts("Taxable_Income", years_retire, lowBound=0)
    state_taxable_income = pulp.LpVariable.dicts("State_Taxable_Income", years_retire, lowBound=0)
    fed_tax = pulp.LpVariable.dicts("Fed_Tax", years_retire, lowBound=0)
    state_tax = pulp.LpVariable.dicts("State_Tax", years_retire, lowBound=0)
    total_tax = pulp.LpVariable.dicts("Total_Tax", years_retire, lowBound=0)
    cgd = pulp.LpVariable.dicts("Capital_Gains_Distribution", years_retire, lowBound=0) # Capital Gains Distribution Amount

    # Federal Tax Brackets
    std_deduction_amount = pulp.LpVariable.dicts("Std_Deduction_Amount", years_retire, lowBound=0)
    tax_bracket_amount = pulp.LpVariable.dicts("Tax_Bracket_Amount", [(y,j) for y in years_retire for j in range(len(S.taxtable))], lowBound=0)

    # State Tax Brackets
    state_std_deduction_amount = pulp.LpVariable.dicts("State_Std_Deduction_Amount", years_retire, lowBound=0)
    state_std_deduction_used = pulp.LpVariable.dicts("State_Std_Deduction_Used", years_retire, lowBound=0)
    state_tax_bracket_amount = pulp.LpVariable.dicts("State_Tax_Bracket_Amount", [(y,j) for y in years_retire for j in range(len(S.state_taxtable))], lowBound=0)

    # Standard Deduction & CG Tax Variables
    standard_deduction_vars = {}
    cg_vars = {}
    for y in years_retire:
        standard_deduction_vars[y, 'income_portion'] = pulp.LpVariable(f"Standard_Deduction_Income_{y}", lowBound=0) # Portion of income in std deduction
        standard_deduction_vars[y, 'cg_portion'] = pulp.LpVariable(f"Standard_Deduction_CG_{y}", lowBound=0) # Portion of CGs in std deduction
        for j in range(len(S.cg_taxtable)):
             # Intermediary vars for min/max logic
             cg_vars[y, j, 'raw_over'] = pulp.LpVariable(f"CG_{y}_{j}_RawOverBracket", cat=pulp.LpContinuous) # Can be negative
             cg_vars[y, j, 'over'] = pulp.LpVariable(f"CG_{y}_{j}_OverBracket", lowBound=0) # max(0, raw_over)
             cg_vars[y, j, 'size'] = pulp.LpVariable(f"CG_{y}_{j}_BracketSize", lowBound=0) # fixed later
             cg_vars[y, j, 'income_portion'] = pulp.LpVariable(f"CG_{y}_{j}_IncomePortion", lowBound=0) # min(over, size)
             cg_vars[y, j, 'cg_portion'] = pulp.LpVariable(f"CG_{y}_{j}_CGPortion", lowBound=0) # Amount taxed at this CG rate


    # NII Tax Variables
    #   nii_income_over_bracket_raw[y] = (taxable_income - nii_threshold)
    #   nii_income_over_bracket[y] = max(0, nii_income_over_bracket_raw)
    #   nii_bracket_cg_portion[y] = amount of CGs subject to NII tax
    nii_vars = {}
    for y in years_retire:
         nii_vars[y, 'raw_over'] = pulp.LpVariable(f"NII_{y}_RawOverBracket", cat=pulp.LpContinuous)
         nii_vars[y, 'over'] = pulp.LpVariable(f"NII_{y}_OverBracket", lowBound=0)
         nii_vars[y, 'cg_portion'] = pulp.LpVariable(f"NII_{y}_CGPortion", lowBound=0) # Amount subject to NII

    not_both_vars = {}
    for y in years_retire:
        not_both_vars[y] = pulp.LpVariable(f"NotBoth_{y}", lowBound=0)

    # --- Objective Function ---
    if args.spend is None:
        # Maximize spending_floor
        prob += spending_floor, "Maximize_Spending"
        # Add constraint to ensure spending_floor is achievable minimum each year
        for y in years_retire:
             i_mul = S.i_rate ** y

             spend_cgd = cgd[y-1] if y > 0 else 0 # Cap gains from *last* year are spendable

             # Spending = Withdrawals + Income - Expenses - Taxes
             # We want spending_floor <= yearly spendable amount / inflation multiplier
             prob += (f_save[y] + spend_cgd + f_ira[y] + f_roth[y] + S.income[y] \
                       - S.expenses[y] - total_tax[y]) >= spending_floor * i_mul, f"Min_Spend_{y}"

    else:
        # Minimize total lifetime taxes (discounted to today's dollars)
        prob += pulp.lpSum(total_tax[y] * (1 / (S.i_rate ** y)) for y in years_retire), "Minimize_Taxes"

        # Fix spending floor
        prob += spending_floor == float(args.spend), "Set_Spending_Floor"
        # Apply fixed spending constraint yearly
        for y in years_retire:
             i_mul = S.i_rate ** y
             spend_cgd = cgd[y-1] if y > 0 else 0
             prob += (f_save[y] + spend_cgd + f_ira[y] + f_roth[y] + S.income[y] \
                       - S.expenses[y] - total_tax[y]) == spending_floor * i_mul, f"Fixed_Spend_{y}"


    if args.roth is not None:
        # Calculate final year Roth balance and constrain it
        final_year = S.numyr - 1
        prob += (bal_roth[final_year] * S.r_rate \
                 - f_roth[final_year] * S.r_rate \
                 + ira_to_roth[final_year] * S.r_rate \
                 ) >= float(args.roth) * (S.i_rate ** S.numyr), "Final_Roth_Value" # Inflated target
        
    if args.ira is not None:
        # Calculate final year ira balance and constrain it
        final_year = S.numyr - 1
        prob += (bal_ira[final_year] * S.r_rate \
                 - f_ira[final_year] * S.r_rate \
                 ) >= float(args.ira) * (S.i_rate ** S.numyr), "Final_401k_Value" # Inflated target   

    # --- Constraints ---

    # --- Retirement Year Constraints ---
    for y in years_retire:
        i_mul = S.i_rate ** y
        age = y + S.retireage

        # Calculate basis_percent (as used in state tax, NII, CG calcs)
        if S.aftertax['basis'] > 0:
            # This is the least wrong way I could think of to estimate the basis percent
            basis_percent = (S.aftertax['basis'] /
                         (S.aftertax['bal'] *
                          (S.r_rate-S.aftertax['distributions'])**y))
            if basis_percent > 1:
                basis_percent = 1
        else:
            basis_percent = 0

        taxable_part_of_f_save = 1 - basis_percent # Portion of f_save that is taxable gain

        # Balance Calculations (Beginning of Year y)
        if y == 0:
            # Link from initial
            last_bal_save = S.aftertax['bal']
            last_bal_ira = S.IRA['bal']
            last_bal_roth = S.roth['bal']

            prob += bal_save[y] == last_bal_save, f"Retire_InitSaveBal_{y}"
            prob += bal_ira[y] == last_bal_ira, f"Retire_InitIRABal_{y}"
            prob += bal_roth[y] == last_bal_roth, f"Retire_InitRothBal_{y}"
        else:
            prob += bal_save[y] == (bal_save[y-1] - f_save[y-1]) * S.r_rate - cgd[y-1], f"Retire_SaveBal_{y}"
#            add_min_constraints(prob, conversion_convience_fee[y-1], ira_to_roth[y-1], 100, M, f"ConversionFee_{y}")
            prob += bal_ira[y] == (bal_ira[y-1] - f_ira[y-1] - ira_to_roth[y-1] - conversion_convience_fee[y-1]) * S.r_rate, f"Retire_IRABal_{y}"
            prob += bal_roth[y] == (bal_roth[y-1] - f_roth[y-1] + ira_to_roth[y-1]) * S.r_rate, f"Retire_RothBal_{y}"

        # prob += ira_to_roth[y] == 0

        # Capital Gains Distribution Balance Calculation
        prob += cgd[y] == (bal_save[y] - f_save[y]) * S.r_rate * S.aftertax['distributions'], f"CGD_Calc_{y}"
        total_cap_gains = cgd[y] + f_save[y] * taxable_part_of_f_save


        # --- Federal Tax Calculation ---

        # Total Non-investment Income Calculation (Federal) = IRA Withdrawals + Conversions + Taxable External Income
        prob += non_investment_income[y] == f_ira[y] + ira_to_roth[y] + S.taxed_income[y], f"NonInvestmentIncome_{y}"

        # --- Non-investment Income Tax Calculations ---
        # Limit amounts in std deduction and brackets
        prob += std_deduction_amount[y] <= S.stded * i_mul, f"MaxStdDed_{y}"

        # How much of the standard deduction is taken up by the non_investment_income?
        add_min_constraints(prob, standard_deduction_vars[y, 'income_portion'], std_deduction_amount[y], non_investment_income[y], M, f"StdDedIncomePortion_{y}")
        # Whatever is left can be used by the capital gains
        prob += standard_deduction_vars[y, 'cg_portion'] <= std_deduction_amount[y] - standard_deduction_vars[y, 'income_portion'], f"StdDedCGPortionLimit_{y}"

        for j, (rate, low, high) in enumerate(S.taxtable):
             bracket_size = (high - low) * i_mul if high != float('inf') else M # Use Big M for unbounded top bracket
             prob += tax_bracket_amount[y, j] <= bracket_size, f"MaxTaxBracket_{y}_{j}"

        # Sum of std_deduction plus the amounts in brackets must equal total non_investment taxable income
        prob += standard_deduction_vars[y, 'income_portion'] + pulp.lpSum(tax_bracket_amount[y, j] for j in range(len(S.taxtable))) == non_investment_income[y], f"SumTaxBrackets_{y}"

        # --- CG Tax Calculations ---

        # --- CG Tax Bracket Calculations ---
        taxable_income_eff = non_investment_income[y] - standard_deduction_vars[y, 'income_portion'] # Non-investment Income above std deduction
        for j, (rate, low, high) in enumerate(S.cg_taxtable):
             low_adj = low * i_mul
             high_adj = high * i_mul if high != float('inf') else M
             bracket_size = high_adj - low_adj

             # how much of this CG bracket was taken up by regular income
             # cg_raw_over = taxable_income_eff - bracket_low (adjusted for non-CG income already taxed)
             prob += cg_vars[y, j, 'raw_over'] == taxable_income_eff - low_adj, f"CG_RawOver_{y}_{j}" # Alternative using effective income

             # if it is 0 or negative, then set it to 0
             # cg_over = max(0, cg_raw_over)
             add_max_zero_constraints(prob, cg_vars[y, j, 'over'], cg_vars[y, j, 'raw_over'], M, f"CG_{y}_{j}")

             # cg_size = bracket_size
             prob += cg_vars[y, j, 'size'] == bracket_size, f"CG_Size_{y}_{j}"

             # complete the computation of how much of this CG bracket was taken up by regular income
             # cg_income_portion = min(cg_over, cg_size)
             add_min_constraints(prob, cg_vars[y, j, 'income_portion'], cg_vars[y, j, 'over'], cg_vars[y, j, 'size'], M, f"CG_{y}_{j}_IncPort")

             # The remainder of this bracket is available for capital gains
             # Portion of bracket available for CGs = size - income_portion
             # cg_cg_portion <= available_portion
             prob += cg_vars[y, j, 'cg_portion'] <= cg_vars[y, j, 'size'] - cg_vars[y, j, 'income_portion'], f"CG_CGPortionLimit_{y}_{j}"
             
        # Sum of CG portions across all brackets must equal total capital gains
        prob += standard_deduction_vars[y, 'cg_portion'] + pulp.lpSum(cg_vars[y, j, 'cg_portion'] for j in range(len(S.cg_taxtable))) == total_cap_gains, f"Sum_CG_Portions_{y}"


        # --- NII Calculation ---

        nii_threshold_adj = S.nii # NII threshold typically not inflation adjusted

        # Simplified MAGI for this calculation
        magi_approx = f_ira[y] + ira_to_roth[y] + S.taxed_income[y] + total_cap_gains

        # NII Raw Over = MAGI - Threshold
        prob += nii_vars[y, 'raw_over'] == magi_approx - nii_threshold_adj, f"NII_RawOver_{y}"

        # NII Over = max(0, raw_over)
        add_max_zero_constraints(prob, nii_vars[y, 'over'], nii_vars[y, 'raw_over'], M, f"NII_{y}")

        # NII CG Portion = min(Total Cap Gains, NII Over)
        add_min_constraints(prob, nii_vars[y, 'cg_portion'], nii_vars[y, 'over'], total_cap_gains, M, f"NII_{y}_CGPort")


        # Calculate Federal Tax (sum across brackets + penalty + CG tax + NII tax)
        fed_tax_calc = pulp.lpSum(tax_bracket_amount[y, j] * S.taxtable[j][0] for j in range(len(S.taxtable)))
        if age < 59:
             fed_tax_calc += f_ira[y] * 0.10 # 10% penalty on early IRA withdrawal
        # Add Capital Gains Tax (calculated below)
        fed_tax_calc += pulp.lpSum(cg_vars[y, j, 'cg_portion'] * S.cg_taxtable[j][0] for j in range(len(S.cg_taxtable)))
        # Add NII Tax (calculated below) - NII applies to the net investment income over threshold
        fed_tax_calc += nii_vars[y, 'cg_portion'] * 0.038 # Add NII tax based on the allocated portion

        # Tax Bump if applicable
        if args.bumptax and args.bumpstart and y >= float(args.bumpstart):
             fed_tax_calc += pulp.lpSum(tax_bracket_amount[y, j] * (float(args.bumptax) / 100.0) for j in range(len(S.taxtable)))

        prob += fed_tax[y] == fed_tax_calc, f"FedTaxCalc_{y}"


        # State Taxable Income Calculation = Fed Taxable Income + Taxable Cap Gains - State Deduction
        # Original: state_taxable = fira + ira2roth + basis*fsave + cgd + state_taxed_extra
        prob += state_taxable_income[y] == f_ira[y] + ira_to_roth[y] + f_save[y] * taxable_part_of_f_save + cgd[y] + S.state_taxed_income[y], f"StateTaxableIncome_{y}"

        # State Tax Calculation
        add_min_constraints(prob, state_std_deduction_used[y], state_std_deduction_amount[y], state_taxable_income[y], M, f"StateStdDedUsed_{y}")
        prob += state_std_deduction_amount[y] <= S.state_stded * i_mul, f"MaxStateStdDed_{y}"
        for j, (rate, low, high) in enumerate(S.state_taxtable):
             bracket_size = (high - low) * i_mul if high != float('inf') else M
             prob += state_tax_bracket_amount[y, j] <= bracket_size, f"MaxStateTaxBracket_{y}_{j}"

        prob += state_std_deduction_used[y] + pulp.lpSum(state_tax_bracket_amount[y, j] for j in range(len(S.state_taxtable))) == state_taxable_income[y], f"SumStateTaxBrackets_{y}"

        prob += state_tax[y] == pulp.lpSum(state_tax_bracket_amount[y, j] * S.state_taxtable[j][0] for j in range(len(S.state_taxtable))), f"StateTaxCalc_{y}"


        # Total Tax Calculation
        prob += total_tax[y] == fed_tax[y] + state_tax[y], f"TotalTaxCalc_{y}"


        # Income Ceiling Constraint (Original A+b constraint)
        # fira + ira2roth + taxed_extra + basis*fsave + cgd <= ceiling
        if (S.income_ceiling[y] < 5000000):
            prob += f_ira[y] + ira_to_roth[y] + S.taxed_income[y] + f_save[y] * taxable_part_of_f_save + cgd[y] <= S.income_ceiling[y], f"IncomeCeiling_{y}"

        # These constraints can make the results "prettier" by avoiding converting to a Roth and then immediately withdrawing it,
        # but they can make the compution slower.
        #  add_if_then_constraint(prob, ira_to_roth[y], f_roth[y], M, f"DontConvertAndWithdraw_{y}")
        #  add_if_then_constraint(prob, f_roth[y], ira_to_roth[y], M, f"DontWithdrawAndConvert_{y}")
        # or maybe this equivilent is slightly faster than the previous, but still slow?
        #  add_min_constraints(prob, not_both_vars[y], f_roth[y], ira_to_roth[y], M, f"NotConvertAndWithdraw_{y}")
        #  prob += not_both_vars[y] == 0, f"NotConvertAndWithdraw_Zero_{y}"
        # Here's another "pretty" fix.  I'm not sure if any of these are needed.
        #  prob += bal_roth[y] >= f_roth[y], f"RothWithdrawNonNeg_{y}" # Roth withdrawals must not exceed balance        


        # RMD Constraint (age >= 73)
        if age >= 73:
            rmd_factor = RMD[age - 72] # Get factor for current age
            # RMD amount = Previous Year End IRA Balance / rmd_factor
            # Previous Year End = bal_ira[y] / S.r_rate (approx BOY balance / growth)
            # Or, more accurately: bal_ira[y-1] - f_ira[y-1] - ira_to_roth[y-1]
            prev_year_end_ira = 0
            if y == 0:
                last_bal_ira = S.IRA['bal']
                prev_year_end_ira = last_bal_ira # Approx EOY before retirement
            else:
                 prev_year_end_ira = bal_ira[y-1] - f_ira[y-1] - ira_to_roth[y-1]

            rmd_required = prev_year_end_ira / rmd_factor
            # Withdrawal must meet RMD: f_ira[y] >= rmd_required
            prob += f_ira[y] >= rmd_required, f"RMD_{y}"


        # Roth Contribution Aging (5-year rule for conversions, contributions assumed available)
        # Before age 59.5, withdrawals limited to contributions + qualified conversions
        if age < 59: # Use 59 as threshold like original
             # Withdrawals (f_roth)) <= Basis
             # Basis = Initial Contributions + Work Contributions + Conversions older than 5 years
             aged_conversions = pulp.lpSum(ira_to_roth[conv_y] for conv_y in range(max(0, y - 5))) # Sum conversions from >= 5 years ago

             # Calculate contributions basis available in year y
             initial_contrib_basis = 0
             for contrib_age, contrib_amount in S.roth['contributions']:
                  # Assume contributions are available immediately (or check 5-year rule if needed)
                  initial_contrib_basis += contrib_amount # Simplification: Assume all initial contribs are withdrawable

             total_basis = initial_contrib_basis + aged_conversions
             prob += f_roth[y] <= total_basis, f"RothBasisLimit_{y}"


    # Final Balance Non-Negative Constraints (End of last year)
    final_year = S.numyr - 1
    if final_year >=0 :
        # EOY = (BOY - Withdrawals + Conversions) * Growth + CGD

        prob += (bal_save[final_year] - f_save[final_year]) * S.r_rate + cgd[final_year] >= 0, "FinalSaveNonNeg"
        prob += (bal_ira[final_year] - f_ira[final_year] - ira_to_roth[final_year]) * S.r_rate >= 0, "FinalIRANonNeg"
        prob += (bal_roth[final_year] - f_roth[final_year] + ira_to_roth[final_year]) * S.r_rate >= 0, "FinalRothNonNeg"


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
    solver = pulp.PULP_CBC_CMD(threads=4,timeLimit=float(args.timelimit) if args.timelimit else 300, msg=args.verbose)


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
        'retire': {},
        'status': status
    }

    for y in years_retire:
        results['retire'][y] = {
            'f_save': f_save[y].varValue,
            'f_ira': f_ira[y].varValue + min(ira_to_roth[y].varValue, f_roth[y].varValue),
            'f_roth': f_roth[y].varValue - min(ira_to_roth[y].varValue, f_roth[y].varValue),
            'ira_to_roth': ira_to_roth[y].varValue - min(ira_to_roth[y].varValue, f_roth[y].varValue),
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
             i_mul_final = S.i_rate ** S.numyr
             print(f"\nThe ending value, including final year investment returns, of your Roth account will be {roth_value:.0f}")
             print(f"That is equivalent to {roth_value / i_mul_final:.0f} in today's dollars")

    if args.ira is not None:
        final_year = S.numyr - 1
        if final_year >= 0:
             ira_value = (results['retire'][final_year]['bal_ira'] \
                            - results['retire'][final_year]['f_ira']) * S.r_rate
             i_mul_final = S.i_rate ** S.numyr
             print(f"\nThe ending value, including final year investment returns, of your IRA account will be {ira_value:.0f}")
             print(f"That is equivalent to {ira_value / i_mul_final:.0f} in today's dollars")

    # Return the results structure instead of the raw array
    return results, S, prob # Pass S and prob back for potential inspection


def print_ascii(results, S):
    if results is None:
        print("No solution found to print.")
        return

    print(f"Solver Status: {results['status']}")
    spending_floor_val = results['spending_floor'] if results['spending_floor'] is not None else 0
    print(f"Yearly spending floor (today's dollars) <= {spending_floor_val:.0f}")
    print()

    print((" age" + " %6s" * 11) % # Adjusted column count
          ("bSAVE", "wSAVE", "bIRA", "wIRA", "bROTH", "wROTH", "IRA2R",
           "TxRate", "Tax", "Spend", "CGD")) # b=balance, w=withdrawal/conversion
    ttax = 0.0
    tspend = 0.0 # Total spending in today's dollars

    for year in range(S.numyr):
        r_res = results['retire'][year]
        age = year + S.retireage
        i_mul = S.i_rate ** year

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
        spending = f_save + spend_cgd + f_ira + f_roth + S.income[year] - S.expenses[year] - tax

        ttax += tax / i_mul                     # totals in today's dollars
        tspend += spending / i_mul              # totals in today's dollars
        div_by = 1000
        print((" %3d:" + " %6.0f" * 11) %
              (age,
               bal_save / div_by, f_save / div_by,
               bal_ira / div_by, f_ira / div_by,
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

    print("age,bal_save,wd_save,bal_ira,wd_ira,bal_roth,wd_roth,ira_to_roth,income,expense,cgd,fed_tax,state_tax,total_tax,spend_goal_inf,actual_spend_inf")
    for year in range(S.numyr):
        r_res = results['retire'][year]
        age = year + S.retireage
        i_mul = S.i_rate ** year

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

        spend_cgd = results['retire'][year-1]['cgd'] if year > 0 and 'cgd' in results['retire'][year-1] else 0
        spending_inf = f_save + spend_cgd + f_ira + f_roth + S.income[year] - S.expenses[year] - total_tax
        spend_goal_inf = spending_floor_val * i_mul


        print(f"{age},{bal_save:.0f},{f_save:.0f},{bal_ira:.0f},{f_ira:.0f},{bal_roth:.0f},{f_roth:.0f},{ira2roth:.0f},{S.income[year]:.0f},{S.expenses[year]:.0f},{cgd:.0f},{fed_tax:.0f},{state_tax:.0f},{total_tax:.0f},{spend_goal_inf:.0f},{spending_inf:.0f}")


def main():
    # Instantiate the parser
    parser = argparse.ArgumentParser(description="Financial planning using Linear Programming (PuLP version)")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Extra output from solver")
    parser.add_argument('--csv', action='store_true', help="Generate CSV outputs")
    parser.add_argument('--timelimit',
                        help="After given seconds return the best answer found (solver dependent)")
    parser.add_argument('--bumpstart', type=int, # Changed type to int
                        help="Start tax bump after given retirement years (e.g., 10)")
    parser.add_argument('--bumptax', type=float, # Changed type to float
                        help="Increase taxes charged in all federal income tax brackets (as percentage points, e.g., 5 for 5%%)")
#    group = parser.add_mutually_exclusive_group()
    parser.add_argument('--spend', type=float, # Changed type to float
                        help="Set fixed yearly spending (today's dollars); minimizes taxes.")
    parser.add_argument('--roth', type=float, # Changed type to float
                       help="Specify the target final Roth balance (today's dollars)")
    parser.add_argument('--ira', type=float, # Changed type to float
                       help="Specify the target final IRA balance (today's dollars)")
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