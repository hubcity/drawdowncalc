#!/usr/bin/env python3

import argparse
import pulp

import data_loader  # .Data
import model_builder as mb #.prepare_pulp
import results_processor as rp #retrieve_results, print_ascii, print_csv

def main():
    # Instantiate the parser
    parser = argparse.ArgumentParser(description="Financial planning using Linear Programming (PuLP version)")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Extra output from solver")
    parser.add_argument('--csv', action='store_true', help="Generate CSV outputs")
    parser.add_argument('--timelimit',
                        help="After given seconds return the best answer found (solver dependent)")
    parser.add_argument('--pessimistic-taxes', action='store_true',
                        help="Simulate higher future taxes by increasing the tax bracket caps slower than inflation")
    parser.add_argument('--pessimistic-healthcare', action='store_true',
                        help="Simulate higher future healthcare costs by increasing the costs more than inflation")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--max-spend', action='store_true',
                       help="Maximize inflation-adjusted spending")
    group.add_argument('--max-assets', type=float, # Changed type to float
                       help="Set fixed yearly spending; maximize end-of-plan assets.")
    group.add_argument('--min-taxes', type=float,
                       help="Set fixed yearly spending; minimize the total taxes paid over the plan")
    parser.add_argument('conffile', help="Configuration file in TOML format")
    args = parser.parse_args()

    # -- Load Configuration File --
    Data = data_loader.Data
    S = Data()
    S.load_file(args.conffile)

    # Solve using PuLP
    print("Starting PuLP solver...")
    # --- Prepare the problem for solving ---
    prob, solver, objectives = None, None, None
    for relTol in [0.9999, 0.999, 0.99]:
        prob, solver, objectives = mb.prepare_pulp(args, S) # Prepare the problem for solving
        print(f"Searching solution with relTol={relTol}")
        prob.sequentialSolve(objectives, relativeTols=[relTol]*len(objectives), solver=solver)
        status = pulp.LpStatus[prob.status]
        if status == "Optimal":
            print(f"Found solution with relTol={relTol}")
            break
        else:
            print(f"Solver status: {status} with relTol={relTol}")
            print("Trying with a less strict tolerance...")

    # --- Process Results ---
    if prob is None:
        print("Failed to create the problem.")
        exit(1)

    final_status = pulp.LpStatus[prob.status]
    print(f"Final solver status: {final_status}")

    if prob.status not in [pulp.LpStatusOptimal, pulp.LpStatusNotSolved]: # Not Solved can occur with time limit but might have a feasible solution
         print("Solver did not find an optimal solution.")
         if prob.status == pulp.LpStatusInfeasible:
            print("Problem is infeasible.")
         elif prob.status == pulp.LpStatusUnbounded:
            print("Problem is unbounded.")
         return None, None, None # Indicate failure

    results, S_out, prob = rp.retrieve_results(args, S, prob)
    if results is None:
        print("Failed to solve the problem.")
        exit(1)


    if args.csv:
        rp.print_csv(results, S_out)
    else:
        rp.print_ascii(results, S_out)

    # Validation logic would need significant rewrite for PuLP variables

if __name__== "__main__":
    main()