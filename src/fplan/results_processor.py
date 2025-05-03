import pulp

def retrieve_results(args, S, prob):
    status = pulp.LpStatus[prob.status]
    all_values = { v.name: v.varValue for v in prob.variables() }
    all_names = ['Balance_Save', 'Withdraw_Save', 'Balance_IRA', 'Withdraw_IRA', 'Balance_Roth', 'Withdraw_Roth', 'IRA_to_Roth',
                  'Ordinary_Income', 'State_Ordinary_Income', 'Fed_Tax', 'State_Tax', 'Total_Tax', 'Capital_Gains_Distribution',
                  'Std_Deduction_Amount', 'State_Std_Deduction_Amount', 'Excess', 'Fed_AGI', 'ACA_HC_Payment']
#    # Extract results into a dictionary or similar structure for printing
    results = {
        'spending_floor': all_values['SpendingFloor'],
        'retire': {},
        'status': status
    }
    years_retire = range(S.numyr)

    for y in years_retire:
        i_mul = S.i_rate ** y
        adjust = min(all_values[f'IRA_to_Roth_{y}'], all_values[f'Withdraw_Roth_{y}']) if S.halfage+y >= 59 else 0
        adjust = adjust / i_mul
        results['retire'][y] = {
            a: all_values[f'{a}_{y}'] / i_mul for a in all_names
        }
        results['retire'][y]['IRA_to_Roth'] = results['retire'][y]['IRA_to_Roth'] - adjust
        results['retire'][y]['Withdraw_Roth'] = results['retire'][y]['Withdraw_Roth'] - adjust
        results['retire'][y]['Withdraw_IRA'] = results['retire'][y]['Withdraw_IRA'] + adjust
        results['retire'][y]['CGD_Spendable'] = (results['retire'][y-1]['Capital_Gains_Distribution'] / S.i_rate) if y > 0 else 0
        results['retire'][y]['tax_brackets'] = [all_values[f'Tax_Bracket_Amount_({y},_{j})'] / i_mul for j in range(len(S.taxtable))]
        results['retire'][y]['state_tax_brackets'] = [all_values[f'State_Tax_Bracket_Amount_({y},_{j})'] / i_mul for j in range(len(S.state_taxtable))]

    return results, S, prob # Pass S and prob back for potential inspection


def print_ascii(results, S):
    if results is None:
        print("No solution found to print.")
        return

    print(f"Solver Status: {results['status']}")
    spending_floor_val = results['spending_floor'] if results['spending_floor'] is not None else 0
    print(f"Yearly spending floor (today's dollars) <= {spending_floor_val:.0f}")
    print()

    print((" age" + " %6s" * 13) % # Adjusted column count
          ("bSAVE", "wSAVE", "bIRA", "wIRA", "bROTH", "wROTH", "IRA2R",
           "Excess", "Tax", "Spend", "CGD", "AGI", "ACA")) # b=balance, w=withdrawal/conversion
    ttax = 0.0
    tspend = 0.0 # Total spending in today's dollars

    for year in range(S.numyr):
        r_res = results['retire'][year]
        age = year + S.retireage
        i_mul = S.i_rate ** year

        # Extract values, handling None if solver failed partially
        bal_save = r_res.get('Balance_Save', 0)
        f_save = r_res.get('Withdraw_Save', 0)
        bal_ira = r_res.get('Balance_IRA', 0)
        f_ira = r_res.get('Withdraw_IRA', 0)
        bal_roth = r_res.get('Balance_Roth', 0)
        f_roth = r_res.get('Withdraw_Roth', 0)
        ira2roth = r_res.get('IRA_to_Roth', 0)
        cgd = r_res.get('Capital_Gains_Distribution', 0)
        cgd_spendable = r_res.get('CGD_Spendable', 0)
        tax = r_res.get('Total_Tax', 0)
        taxable_inc = r_res.get('Ordinary_Income',0)
        std_ded_amount = r_res.get('Std_Deduction_Amount',0)
        state_taxable_inc = r_res.get('State_Ordinary_Income', 0)
        state_std_ded_amount = r_res.get('State_Std_Deduction_Amount',0)
        excess = r_res.get('Excess', 0)
        agi = r_res.get('Fed_AGI', 0)
        aca = r_res.get('ACA_HC_Payment', 0)

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
        spending = -excess + f_save + cgd_spendable + f_ira + f_roth \
            + S.income[year] / i_mul + S.social_security[year] / i_mul \
            - S.expenses[year] / i_mul - aca - tax

        ttax += tax
        tspend += spending
        div_by = 1000
        print((" %3d:" + " %6.0f" * 13) %
              (age,
               bal_save / div_by, f_save / div_by,
               bal_ira / div_by, f_ira / div_by,
               bal_roth / div_by, f_roth / div_by, ira2roth / div_by,
               excess / div_by, tax / div_by, spending / div_by, cgd / div_by, agi / div_by, aca / div_by))

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

        bal_save = r_res.get('Balance_Save', 0)
        f_save = r_res.get('Withdraw_Save', 0)
        bal_ira = r_res.get('Balance_IRA', 0)
        f_ira = r_res.get('Withdraw_IRA', 0)
        bal_roth = r_res.get('Balance_Roth', 0)
        f_roth = r_res.get('Withdraw_Roth', 0)
        ira2roth = r_res.get('IRA_to_Roth', 0)
        cgd = r_res.get('Capital_Gains_Distribution', 0)
        fed_tax = r_res.get('Fed_Tax', 0)
        state_tax = r_res.get('State_Tax', 0)
        total_tax = r_res.get('Total_Tax', 0)
        excess = r_res.get('Excess', 0)
        aca = r_res.get('ACA_HC_Payment', 0)

#        spend_cgd = results['retire'][year-1]['cgd'] if year > 0 else 0
        spend_cgd = r_res.get('CGD_Spendable', 0)
        spending_inf = -excess + f_save + spend_cgd + f_ira + f_roth \
            + S.income[year] / i_mul + S.social_security[year] / i_mul \
            - S.expenses[year] / i_mul - aca - total_tax
        spend_goal_inf = spending_floor_val


        print(f"{age},{bal_save:.0f},{f_save:.0f},{bal_ira:.0f},{f_ira:.0f},{bal_roth:.0f},{f_roth:.0f},{ira2roth:.0f},{(S.income[year] + S.social_security[year]) / i_mul:.0f},{S.expenses[year] / i_mul:.0f},{cgd:.0f},{fed_tax:.0f},{state_tax:.0f},{total_tax:.0f},{spend_goal_inf:.0f},{spending_inf:.0f}")