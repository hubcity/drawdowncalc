import pulp
from ddcalc.utils.pulp import add_min_constraints, add_max_constraints, add_if_then_constraint
from ddcalc.core.data_loader import RMD

# Minimize: c^T * x -> Defined using PuLP objective
# Subject to: A_ub * x <= b_ub -> Defined using PuLP constraints
# Subject to: A_eq * x == b_eq -> Defined using PuLP constraints
def prepare_pulp(args, S):
    current_year = 2025

    # Define the problem
    prob = pulp.LpProblem("FinancialPlan", pulp.LpMaximize)
    objectives = []

    # --- Define Variables ---
    years_retire = range(S.numyr)
    M = 100_000_000 # Big M for indicator constraints

    # --- Single Variables ---
    spending_floor = pulp.LpVariable("SpendingFloor", lowBound=0)
    eop_assets = pulp.LpVariable("EndOfPlan_Assets", lowBound=0)

    # --- Retirement Year Variables ---
    # Withdrawals / Conversions
    true_spending = pulp.LpVariable.dicts("True_Spending", years_retire, lowBound=0)
    f_save = pulp.LpVariable.dicts("Brokerage_Withdraw", years_retire, lowBound=0)
    f_ira = pulp.LpVariable.dicts("IRA_Withdraw", years_retire, lowBound=0)
    f_roth = pulp.LpVariable.dicts("Roth_Withdraw", years_retire, lowBound=0)
    ira_to_roth = pulp.LpVariable.dicts("IRA_to_Roth", years_retire, lowBound=0)

    # Balances (Beginning of Year)
    bal_save = pulp.LpVariable.dicts("Brokerage_Balance", years_retire, lowBound=0)
    bal_ira = pulp.LpVariable.dicts("IRA_Balance", years_retire, lowBound=0)
    bal_roth = pulp.LpVariable.dicts("Roth_Balance", years_retire, lowBound=0)

    # Tax Calculation Variables
    ordinary_income = pulp.LpVariable.dicts("Ordinary_Income", years_retire, lowBound=0)
    state_ordinary_income = pulp.LpVariable.dicts("State_Ordinary_Income", years_retire, lowBound=0)
    fed_tax = pulp.LpVariable.dicts("Fed_Tax", years_retire, lowBound=0)
    state_tax = pulp.LpVariable.dicts("State_Tax", years_retire, lowBound=0)
    total_tax = pulp.LpVariable.dicts("Total_Tax", years_retire, lowBound=0)
    cgd = pulp.LpVariable.dicts("Capital_Gains_Distribution", years_retire, lowBound=0) # Capital Gains Distribution Amount
    total_cap_gains = pulp.LpVariable.dicts("Total_Capital_Gains", years_retire, lowBound=0) # Total Capital Gains Amount

    # Additional holding variables to return with the answer
    fed_agi = pulp.LpVariable.dicts("Fed_AGI", years_retire, lowBound=0) # Federal AGI
    brokerage_cg = pulp.LpVariable.dicts("Brokerage_CG", years_retire, lowBound=0) # Capital Gains from Brokerage Account
    full_social_security = pulp.LpVariable.dicts("Social_Security", years_retire, lowBound=0) # Full Social Security Amount
    taxable_social_security = pulp.LpVariable.dicts("Taxable_Social_Security", years_retire, lowBound=0) # Taxable Social Security Amount
    state_agi = pulp.LpVariable.dicts("State_AGI", years_retire, lowBound=0) # State AGI
    state_IRA_taxable = pulp.LpVariable.dicts("State_IRA_Taxable", years_retire, lowBound=0) # State Taxable IRA Amount
    state_taxable_social_security = pulp.LpVariable.dicts("State_Taxable_Social_Security", years_retire, lowBound=0) # State Taxable Social Security Amount
    state_tax_ordinary_income = pulp.LpVariable.dicts("State_Tax_Ordinary_Income", years_retire, lowBound=0) # State Tax on Ordinary Income
    fed_tax_ordinary_income = pulp.LpVariable.dicts("Fed_Tax_Ordinary_Income", years_retire, lowBound=0) # Federal Tax on Ordinary Income
    fed_tax_cg = pulp.LpVariable.dicts("Fed_Tax_CG", years_retire, lowBound=0) # Federal Tax on Capital Gains
    fed_tax_nii = pulp.LpVariable.dicts("Fed_Tax_NII", years_retire, lowBound=0) # Federal Tax on NII
    fed_tax_early_withdrawal = pulp.LpVariable.dicts("Fed_Tax_Early_Withdrawal", years_retire, lowBound=0) # Federal Tax on Early Withdrawal
    required_RMD = pulp.LpVariable.dicts("Required_RMD", years_retire, lowBound=0) # Required Minimum Distribution Amount
    excess = pulp.LpVariable.dicts("Excess", years_retire, lowBound=0) # Excess Withdrawal
    cash_withdraw = pulp.LpVariable.dicts("Cash_Withdraw", years_retire, lowBound=0) # Cash Withdrawals

    # ACA
    min_payment = pulp.LpVariable.dicts("ACA_Min_Payment", years_retire, lowBound=0) # ACA Minimum Payment
    raw_help = pulp.LpVariable.dicts("ACA_Raw_Help", years_retire, cat=pulp.LpContinuous) # ACA Raw Help
    nonneg_help = pulp.LpVariable.dicts("ACA_Nonneg_Help", years_retire, cat=pulp.LpContinuous) # ACA Raw Help
    help = pulp.LpVariable.dicts("ACA_Help", years_retire, lowBound=0) # ACA Help
    hc_payment = pulp.LpVariable.dicts("ACA_HC_Payment", years_retire, lowBound=0) # ACA Health Care Payment

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

    jagged = pulp.LpVariable.dicts("Jagged", range(S.numyr-1), lowBound=0)

    inf_adj_tax = [(total_tax[y]+hc_payment[y]) * 1 / (S.i_rate ** y) for y in years_retire]
    for y in range(S.numyr-2):
        prob += jagged[y] >= (inf_adj_tax[y+2] - inf_adj_tax[y+1]) - (inf_adj_tax[y+1] - inf_adj_tax[y]), f"Jagged_Tax_Jump_{y}"
        prob += jagged[y] >= (inf_adj_tax[y+1] - inf_adj_tax[y]) - (inf_adj_tax[y+2] - inf_adj_tax[y+1]), f"Jagged_Tax_Jump_{y}_2"
    # Should we make a special attempt to smooth the first year?
    # prob += smooth[S.numyr-2] >= (inf_adj_tax[1] - inf_adj_tax[0]) - (inf_adj_tax[0] - 0), f"Smooth_Tax_Jump_{S.numyr-2}"
    # prob += smooth[S.numyr-2] >= (inf_adj_tax[0] - 0) - (inf_adj_tax[1] - inf_adj_tax[0]), f"Smooth_Tax_Jump_{S.numyr-2}_2"

    for y in years_retire:
         i_mul = S.i_rate ** y
         spend_cgd = cgd[y-1] if y > 0 else 0 # Cap gains from *last* year are spendable
         # Spending = Withdrawals + Income - Expenses - Taxes
         # We want spending_floor <= yearly spendable amount / inflation multiplier
         total_withdrawals = f_save[y] + spend_cgd + f_ira[y] + f_roth[y] + S.income[y] + S.social_security[y]
         total_expenses = total_tax[y] + S.expenses[y] + hc_payment[y] + spending_floor * i_mul
         prob += total_withdrawals >= total_expenses, f"Min_Spend_{y}"
         prob += excess[y] == total_withdrawals - total_expenses
         prob += true_spending[y] == total_withdrawals - total_tax[y] - excess[y] - hc_payment[y] - S.expenses[y]
         prob += full_social_security[y] == S.social_security[y]
         prob += cash_withdraw[y] == S.income[y]
#         prob += excess[y] == 0
         # add_max_constraints(prob, excess[y], raw_excess, 0, M, f"Excess_{y}")

    if args.no_conversions:
        for y in years_retire:
            prob += ira_to_roth[y] == 0
    elif args.no_conversions_after_socsec:
        for y in years_retire:
            if S.social_security[y] > 0:
                prob += ira_to_roth[y] == 0


    # Final Balance Non-Negative Constraints (End of last year)
    final_year = S.numyr - 1
    eop_assets = pulp.LpVariable("EndOfPlan_Assets", lowBound=0)
    if final_year >=0 :
        # For brokerage we don't have to subtract new capital gains and can add back in the ones not spent from last year
        eop_save = (bal_save[final_year] - f_save[final_year]) * S.r_rate + cgd[final_year-1] + excess[final_year]
        eop_ira = (bal_ira[final_year] - f_ira[final_year] - ira_to_roth[final_year]) * S.r_rate
        eop_roth = (bal_roth[final_year] - f_roth[final_year] + ira_to_roth[final_year]) * S.r_rate        

        prob += eop_save >= 0, "FinalSaveNonNeg"
        prob += eop_ira  >= 0, "FinalIRANonNeg"
        prob += eop_roth >= 0, "FinalRothNonNeg"

        prob += eop_assets == eop_save + eop_ira + eop_roth, "EndOfPlan_Assets"

    if args.min_taxes is not None:
        prob += spending_floor == float(args.min_taxes), "Set_Spending_Floor"
        objectives = [- 1 * pulp.lpSum(inf_adj_tax[y] for y in years_retire) / len(years_retire)]
    elif args.max_assets is not None:
        prob += spending_floor == float(args.max_assets), "Set_Spending_Floor"
        objectives = [+ 1.0 * eop_assets \
                      - 0.0 * pulp.lpSum(jagged[y] for y in range(S.numyr-1)) / len(years_retire)]
    else:  # defaults to max-spend
        objectives = [+ 1.0 * spending_floor \
                      - 0.0 * pulp.lpSum(jagged[y] for y in range(S.numyr-1)) / len(years_retire)]

    # --- Constraints ---

    # --- Retirement Year Constraints ---
    for y in years_retire:
        i_mul = S.i_rate ** y
        tax_i_mul = ((S.i_rate - 0.01) ** y) if (args.pessimistic_taxes) else i_mul
        hc_i_mul = ((S.i_rate + 0.01) ** y) if (args.pessimistic_healthcare) else i_mul
        age = y + S.retireage

        # Calculate basis_percent (as used in state tax, NII, CG calcs)
        if S.aftertax['bal'] > 0:
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

            prob += bal_save[y] == last_bal_save, f"InitSaveBal_{y}"
            prob += bal_ira[y] == last_bal_ira, f"InitIRABal_{y}"
            prob += bal_roth[y] == last_bal_roth, f"InitRothBal_{y}"
        else:
            prob += bal_save[y] == (bal_save[y-1] - f_save[y-1]) * S.r_rate - cgd[y-1] + excess[y-1], f"SaveBal_{y}"
            prob += bal_ira[y] == (bal_ira[y-1] - f_ira[y-1] - ira_to_roth[y-1]) * S.r_rate, f"IRABal_{y}"
            prob += bal_roth[y] == (bal_roth[y-1] - f_roth[y-1] + ira_to_roth[y-1]) * S.r_rate, f"RothBal_{y}"


        # Capital Gains Distribution Balance Calculation
        prob += cgd[y] == (bal_save[y] - f_save[y]) * S.r_rate * S.aftertax['distributions'], f"CGD_Calc_{y}"
        prob += brokerage_cg[y] == f_save[y] * taxable_part_of_f_save, f"BrokerageCG_{y}"
        prob += total_cap_gains[y] == cgd[y] + brokerage_cg[y] # Total Capital Gains = Cap Gains Distribution + Brokerage CG


        # --- Federal Tax Calculation ---

        # Total Non-investment Income Calculation (Federal) = IRA Withdrawals + Conversions + Taxable External Income
        prob += ordinary_income[y] == f_ira[y] + ira_to_roth[y] + S.taxed_income[y] + S.social_security_taxed[y], f"Ordinary_Income_{y}"

        # --- Non-investment Income Tax Calculations ---
        # Limit amounts in std deduction and brackets
        prob += std_deduction_amount[y] <= S.stded * tax_i_mul, f"MaxStdDed_{y}"

        # How much of the standard deduction is taken up by the non_investment_income?
        add_min_constraints(prob, standard_deduction_vars[y, 'income_portion'], std_deduction_amount[y], ordinary_income[y], M, f"StdDedIncomePortion_{y}")
        # Whatever is left can be used by the capital gains
        prob += standard_deduction_vars[y, 'cg_portion'] <= std_deduction_amount[y] - standard_deduction_vars[y, 'income_portion'], f"StdDedCGPortionLimit_{y}"


        for j, (rate, low, high) in enumerate(S.taxtable):
             bracket_size = (high - low) * tax_i_mul if high != float('inf') else M # Use Big M for unbounded top bracket
             prob += tax_bracket_amount[y, j] <= bracket_size, f"MaxTaxBracket_{y}_{j}"

        # Sum of std_deduction plus the amounts in brackets must equal total non_investment taxable income
        prob += standard_deduction_vars[y, 'income_portion'] + pulp.lpSum(tax_bracket_amount[y, j] for j in range(len(S.taxtable))) == ordinary_income[y], f"SumTaxBrackets_{y}"

        # --- CG Tax Calculations ---

        # --- CG Tax Bracket Calculations ---
        taxable_income_eff = ordinary_income[y] - standard_deduction_vars[y, 'income_portion'] # Ordinary (Non-investment) Income above std deduction
        for j, (rate, low, high) in enumerate(S.cg_taxtable):
             low_adj = low * tax_i_mul
             high_adj = high * tax_i_mul if high != float('inf') else M
             bracket_size = high_adj - low_adj

             # how much of this CG bracket was taken up by regular income
             # cg_raw_over = taxable_income_eff - bracket_low (adjusted for non-CG income already taxed)
             prob += cg_vars[y, j, 'raw_over'] == taxable_income_eff - low_adj, f"CG_RawOver_{y}_{j}" # Alternative using effective income

             # if it is 0 or negative, then set it to 0
             # cg_over = max(0, cg_raw_over)
             # add_max_zero_constraints(prob, cg_vars[y, j, 'over'], cg_vars[y, j, 'raw_over'], M, f"CG_{y}_{j}")
             prob += cg_vars[y, j, 'over'] >= cg_vars[y, j, 'raw_over']
             prob += cg_vars[y, j, 'over'] >= 0

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
        prob += standard_deduction_vars[y, 'cg_portion'] + pulp.lpSum(cg_vars[y, j, 'cg_portion'] for j in range(len(S.cg_taxtable))) == total_cap_gains[y], f"Sum_CG_Portions_{y}"


        # --- NII Calculation ---

        nii_threshold_adj = S.nii # NII threshold typically not inflation adjusted

        # Simplified MAGI for this calculation
        magi_approx = f_ira[y] + ira_to_roth[y] + S.taxed_income[y] + S.social_security_taxed[y] + total_cap_gains[y]
        prob += fed_agi[y] == magi_approx, f"FedAGI_{y}"

        # NII Raw Over = MAGI - Threshold
        prob += nii_vars[y, 'raw_over'] == magi_approx - nii_threshold_adj, f"NII_RawOver_{y}"

        # NII Over = max(0, raw_over)
        # add_max_zero_constraints(prob, nii_vars[y, 'over'], nii_vars[y, 'raw_over'], M, f"NII_{y}")
        prob += nii_vars[y, 'over'] >= 0
        prob += nii_vars[y, 'over'] >= nii_vars[y, 'raw_over']

        # NII CG Portion = min(Total Cap Gains, NII Over)
        add_min_constraints(prob, nii_vars[y, 'cg_portion'], nii_vars[y, 'over'], total_cap_gains[y], M, f"NII_{y}_CGPort")


        # Calculate Federal Tax (sum across brackets + penalty + CG tax + NII tax)
        # First, the brackets
        fed_tax_calc = pulp.lpSum(tax_bracket_amount[y, j] * S.taxtable[j][0] for j in range(len(S.taxtable)))
        prob += fed_tax_ordinary_income[y] == fed_tax_calc, f"FedTaxOrdIncome_{y}"

        # Add Capital Gains Tax
        prob += fed_tax_cg[y] == pulp.lpSum(cg_vars[y, j, 'cg_portion'] * S.cg_taxtable[j][0] for j in range(len(S.cg_taxtable))), f"FedTaxCG_{y}"
        fed_tax_calc += fed_tax_cg[y]

        # Add NII Tax (calculated below) - NII applies to the net investment income over threshold
        prob += fed_tax_nii[y] == nii_vars[y, 'cg_portion'] * 0.038 # NII tax rate
        fed_tax_calc += fed_tax_nii[y] # Add NII tax based on the allocated portion

        if S.halfage + y < 59:
            prob += fed_tax_early_withdrawal[y] == f_ira[y] * 0.1, f"FedTaxEarlyWithdraw_{y}"
            prob += fed_tax[y] == fed_tax_calc + fed_tax_early_withdrawal[y], f"FedTaxCalc_{y}"
        else:
            prob += fed_tax[y] == fed_tax_calc, f"FedTaxCalc_{y}"


        # State Taxable Income Calculation = Fed Taxable Income + Taxable Cap Gains - State Deduction
        # Original: state_taxable = fira + ira2roth + basis*fsave + cgd + state_taxed_extra
        taxed_ira = 0
        if (S.state_taxes_retirement_income):
            taxed_ira = f_ira[y]
        prob += state_ordinary_income[y] == taxed_ira + ira_to_roth[y] + f_save[y] * taxable_part_of_f_save \
            + cgd[y] + S.state_taxed_income[y] + S.state_social_security_taxed[y], f"StateTaxableIncome_{y}"
        prob += state_agi[y] == state_ordinary_income[y], f"StateAGI_{y}"

        # aca premium subsidy
        # Implemented as discrete steps from 200% to 400%.  Currently using the 2025 rules.
        # This is reasonably fast to calculate and better than ignoring subsidies altogether.
        if (S.retireage + y <= 65) and (S.aca['slcsp'] > 0):
            add_if_then_constraint(prob, fed_agi[y] - 3.5 * S.fpl_amount * i_mul, raw_help[y] - (S.aca['slcsp']*i_mul - (0.085 * fed_agi[y])/12.0), M, f"FPL_400_{y}")
            add_if_then_constraint(prob, fed_agi[y] - 3.0 * S.fpl_amount * i_mul, raw_help[y] - (S.aca['slcsp']*i_mul - (0.0725 * fed_agi[y])/12.0), M, f"FPL_350_{y}")
            add_if_then_constraint(prob, fed_agi[y] - 2.75 * S.fpl_amount * i_mul, raw_help[y] - (S.aca['slcsp']*i_mul - (0.06 * fed_agi[y])/12.0), M, f"FPL_300_{y}")
            add_if_then_constraint(prob, fed_agi[y] - 2.5 * S.fpl_amount * i_mul, raw_help[y] - (S.aca['slcsp']*i_mul - (0.05 * fed_agi[y])/12.0), M, f"FPL_275_{y}")
            add_if_then_constraint(prob, fed_agi[y] - 2.25 * S.fpl_amount * i_mul, raw_help[y] - (S.aca['slcsp']*i_mul - (0.04 * fed_agi[y])/12.0), M, f"FPL_250_{y}")
            add_if_then_constraint(prob, fed_agi[y] - 2.0 * S.fpl_amount * i_mul, raw_help[y] - (S.aca['slcsp']*i_mul - (0.03 * fed_agi[y])/12.0), M, f"FPL_225_{y}")
            prob += raw_help[y] <= S.aca['slcsp']*i_mul - (0.02 * fed_agi[y])/12.0, f"FPL_200_{y}"
            add_max_constraints(prob, nonneg_help[y], raw_help[y], 0, M, f"Help_Nonneg_{y}")
            add_min_constraints(prob, help[y], nonneg_help[y], S.aca['premium']*i_mul, M, f"Help_{y}")

#            prob += min_payment[y] >= (8.5 / 100.0 * fed_agi[y]) / 12.0, f"Min_Payment_{y}"
#            prob += raw_help[y] <= (S.aca['premium'] * hc_i_mul)
#            prob += raw_help[y] <= (S.aca['slcsp'] * hc_i_mul) - min_payment[y]  
#            add_max_constraints(prob, help[y], raw_help[y], 0, M, f"Help_{y}")
            if S.retireage + y == 65:
                prob += hc_payment[y] == ((S.aca['premium'] * hc_i_mul) - help[y]) * (S.birthmonth -1)
            else:
                prob += hc_payment[y] == ((S.aca['premium'] * hc_i_mul) - help[y]) * 12

#            if y > 0:
#                prob += hc_payment[y] <= hc_payment[y-1] * S.i_rate

        elif (S.retireage + y <= 65):
            if S.retireage + y == 65:
                prob += hc_payment[y] == ((S.aca['premium'] * hc_i_mul)) * (S.birthmonth -1)
            else:
                prob += hc_payment[y] == ((S.aca['premium'] * hc_i_mul)) * 12
        else:
            prob += hc_payment[y] == 0


        # State Tax Calculation
#        add_min_constraints(prob, state_std_deduction_used[y], state_std_deduction_amount[y], state_ordinary_income[y], M, f"StateStdDedUsed_{y}")
        prob += state_std_deduction_used[y] <= state_std_deduction_amount[y]
        prob += state_std_deduction_used[y] <= state_ordinary_income[y]
        prob += state_std_deduction_amount[y] <= S.state_stded * tax_i_mul, f"MaxStateStdDed_{y}"
        for j, (rate, low, high) in enumerate(S.state_taxtable):
             bracket_size = (high - low) * tax_i_mul if high != float('inf') else M
             prob += state_tax_bracket_amount[y, j] <= bracket_size, f"MaxStateTaxBracket_{y}_{j}"

        prob += state_std_deduction_used[y] + pulp.lpSum(state_tax_bracket_amount[y, j] for j in range(len(S.state_taxtable))) == state_ordinary_income[y], f"SumStateTaxBrackets_{y}"

        prob += state_tax[y] == pulp.lpSum(state_tax_bracket_amount[y, j] * S.state_taxtable[j][0] for j in range(len(S.state_taxtable))), f"StateTaxCalc_{y}"
        prob += state_tax_ordinary_income[y] == state_tax[y], f"StateTaxOrdIncome_{y}"

        # Total Tax Calculation
        prob += total_tax[y] == fed_tax[y] + state_tax[y], f"TotalTaxCalc_{y}"

        # Income Ceiling Constraint (Original A+b constraint)
        # fira + ira2roth + taxed_extra + basis*fsave + cgd <= ceiling
        if (S.income_ceiling[y] < 50_000_000):
            prob += fed_agi[y] <= S.income_ceiling[y], f"IncomeCeiling_{y}"

        # RMD Constraint (SECURE Act 2.0)
        # Once you start RMDs you can't stop.  So the unlucky people born in 1959 will
        # start their RMDs at age 73 in 2032.  In 2033 when the rules change to 75, they 
        # will already be in the system and the new rules won't apply to them.
        birthyear = current_year + y - age
        if (birthyear < 1960 and age >= 73) or (age >= 75):
            rmd_factor = RMD[age - 72] # Get factor for current age
            # RMD amount = Previous Year End IRA Balance / rmd_factor
            # We will use this year's starting balance as a proxy for last year's ending balance
            rmd_required = bal_ira[y] * (1.0 / rmd_factor)
            # Withdrawal must meet RMD: f_ira[y] >= rmd_required
            prob += f_ira[y] >= rmd_required, f"RMD_{y}"
            prob += required_RMD[y] == rmd_required, f"RMD_Amount_{y}"
            # prob += ira_to_roth[y] == 0, f"RMD_Convert_{y}" # No conversions if RMD is required
#            if y < S.numyr-1:
#                prob += total_tax[y+1] >= total_tax[y] * S.i_rate
        else:
            prob += required_RMD[y] == 0




        # Roth Conversion Aging (5-year rule for all Roth additions) until age 59.5 with an additional 
        # requirement that the account be open for 5 years for full access.
        # I believe this is more strict than the IRS rules.  It is certainly easier to compute.
        age_account_open = min([ca for ca, _ in S.roth['contributions']], default=S.retireage)

        if not ((S.halfage + y >= 59) and (S.retireage + y - age_account_open >= 5)):
#             print("Restricting Roth Conversions ", S.retireage + y)
             aged_conversions = pulp.lpSum(ira_to_roth[conv_y] for conv_y in range(max(0, y - 4))) \
                                - pulp.lpSum(f_roth[conv_y] for conv_y in range(y)) # Sum conversions from >= 5 years ago less withdrawals

             # Calculate contributions basis available in year y
             initial_contrib_basis = 0
             for contrib_age, contrib_amount in S.roth['contributions']:
                  if S.retireage + y - contrib_age >= 5:
                      initial_contrib_basis += contrib_amount

             total_basis = initial_contrib_basis + aged_conversions
             prob += f_roth[y] <= total_basis, f"RothBasisLimit_{y}"


    # --- Solve ---
    solver_options = {}
    if args.timelimit:
        solver_options['timeLimit'] = float(args.timelimit)
    if args.verbose:
        solver_options['msg'] = 1 # Show solver output
    else:
         solver_options['msg'] = 0

    # Choose a solver (HiGHs is now default, bundled with PuLP >=2.7)
    solver = pulp.HiGHS_CMD(timeLimit=float(args.timelimit) if args.timelimit else 90, msg=args.verbose)

    return prob, solver, objectives