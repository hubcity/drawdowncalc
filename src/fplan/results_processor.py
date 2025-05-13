import pulp

def retrieve_results(args, S, prob):
    status = pulp.LpStatus[prob.status]
    all_values = { v.name: v.varValue for v in prob.variables() }
    all_names = ["Cash_Withdraw", "Brokerage_Balance", "Brokerage_Withdraw", "IRA_Balance", "IRA_Withdraw", 
                 "Required_RMD", "Roth_Balance", 
                 "Roth_Withdraw", "IRA_to_Roth", "CGD_Spendable", "Capital_Gains_Distribution", "Total_Capital_Gains", 
                 "Ordinary_Income", "Fed_AGI", "Fed_Tax", "State_AGI", "State_Tax", "Total_Tax", 
                 "ACA_HC_Payment", "ACA_Help", "Social_Security", "True_Spending", "Excess"]
#    # Extract results into a dictionary or similar structure for printing
    results = {
        'spending_floor': all_values['SpendingFloor'],
        'endofplan_assets': all_values['EndOfPlan_Assets'] / (S.i_rate ** S.numyr),
        'retire': {},
        'federal': { 'status': S.status, 'taxtable': S.taxtable, 'cg_taxtable': S.cg_taxtable, 'nii': S.nii, 'standard_deduction': S.stded },
        'state': { 'status': S.state_status, 'taxtable': S.state_taxtable, 'standard_deduction': S.state_stded, 'taxes_ss': S.state_taxes_ss, 'taxes_retirement_income': S.state_taxes_retirement_income},
        'status': status
    }
    years_retire = range(S.numyr)

    for y in years_retire:
        i_mul = S.i_rate ** y
        adjust = min(all_values[f'IRA_to_Roth_{y}'], all_values[f'Roth_Withdraw_{y}']) if S.halfage+y >= 59 else 0
        adjust = adjust / i_mul
        results['retire'][y] = {
            a: round(all_values.get(f'{a}_{y}', 0) / i_mul) for a in all_names
        }
        results['retire'][y]['IRA_to_Roth'] = round(results['retire'][y]['IRA_to_Roth'] - adjust)
        results['retire'][y]['Roth_Withdraw'] = round(results['retire'][y]['Roth_Withdraw'] - adjust)
        results['retire'][y]['IRA_Withdraw'] = round(results['retire'][y]['IRA_Withdraw'] + adjust)
        results['retire'][y]['CGD_Spendable'] = round(results['retire'][y-1]['Capital_Gains_Distribution'] / i_mul) if y > 0 else 0
        results['retire'][y]['tax_brackets'] = [all_values[f'Tax_Bracket_Amount_({y},_{j})'] / i_mul for j in range(len(S.taxtable))]
        results['retire'][y]['state_tax_brackets'] = [all_values[f'State_Tax_Bracket_Amount_({y},_{j})'] / i_mul for j in range(len(S.state_taxtable))]

#    print(all_values)
    return results, S, prob # Pass S and prob back for potential inspection


def print_ascii(results, S):
    if results is None:
        print("No solution found to print.")
        return

    print(f"Solver Status: {results['status']}")
    spending = results['spending_floor'] if results['spending_floor'] is not None else 0
    print(f"Yearly spending floor (today's dollars) <= {spending:.0f}")
    eop = results['endofplan_assets'] if results['endofplan_assets'] is not None else 0
    print(f"End-of-plan Assets (today's dollars) <= {eop:.0f}")   
    print()

    columns = ["Brokerage_Balance", "Brokerage_Withdraw", "IRA_Balance", "IRA_Withdraw", "Roth_Balance", 
                "Roth_Withdraw", "IRA_to_Roth", "Capital_Gains_Distribution", "Fed_AGI", "Total_Tax", 
                "ACA_HC_Payment", "Social_Security", "True_Spending", "Excess"]

    print((" age" + " %6.6s" * len(columns)) % # Adjusted column count
          tuple(columns)) # b=balance, w=withdrawal/conversion

    for year in range(S.numyr):
        r_res = results['retire'][year]
        age = year + S.retireage

        values = [r_res.get(c, 0) / 1000.0 for c in columns]

        div_by = 1000
        print((" %3d:" + " %6.0f" * len(columns)) %
              ((age,) + tuple(values)))


def print_csv(results, S):
    if results is None:
        print("No solution found to print.")
        return

#    print(f"Solver Status,{results['status']}")
    spending_floor_val = results['spending_floor'] if results['spending_floor'] is not None else 0
#    print(f"spend goal,{spending_floor_val:.0f}")
#    print(f"savings,{S.aftertax['bal']},{S.aftertax['basis']}")
#    print(f"ira,{S.IRA['bal']}")
#    print(f"roth,{S.roth['bal']}")

    columns = ["Cash_Withdraw", "Brokerage_Balance", "Brokerage_Withdraw", "IRA_Balance", "IRA_Withdraw", "Roth_Balance", 
                 "Roth_Withdraw", "IRA_to_Roth", "CGD_Spendable", "Capital_Gains_Distribution", "Total_Capital_Gains", 
                 "Ordinary_Income", "Fed_AGI", "Fed_Tax", "State_Tax", "Total_Tax", 
                 "ACA_HC_Payment", "ACA_Help", "Social_Security", "True_Spending"]
    print(("age" + ",%6s" * len(columns)) % # Adjusted column count
          tuple(columns)) # b=balance, w=withdrawal/conversion
    for year in range(S.numyr):
        r_res = results['retire'][year]
        age = year + S.retireage
        values = [r_res.get(c, 0) for c in columns]

        print(("%d" + ",%.0f" * len(columns)) %
              ((age,) + tuple(values)))