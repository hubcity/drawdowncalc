#!/usr/bin/env python3

import argparse
import sys # Import sys for sys.exit

import fplan.core.data_loader as dl  # .Data
# Import the new FPlan class
import fplan.fplan as fc



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
                       help="Maximize inflation-adjusted spending (default objective)")
    group.add_argument('--max-assets', type=float, # Changed type to float
                       help="Set fixed yearly spending; maximize end-of-plan assets.")
    group.add_argument('--min-taxes', type=float,
                       help="Set fixed yearly spending; minimize the total taxes paid over the plan")

    conversion_group = parser.add_mutually_exclusive_group()
    conversion_group.add_argument('--allow-conversions', action='store_true',
                                  help="Allow Roth conversions throughout the plan (default behavior if no conversion option is specified).")
    conversion_group.add_argument('--no-conversions', action='store_true',
                                  help="Disallow all Roth conversions.")
    conversion_group.add_argument('--no-conversions-after-socsec', action='store_true',
                                  help="Disallow Roth conversions after Social Security benefits begin.")

    parser.add_argument('conffile', help="Configuration file in TOML format")
    args = parser.parse_args()

    # -- Load Configuration File --
    data = dl.Data()
    data.load_config(args.conffile) # Use load_config

    # --- Determine primary objective from args ---
    objective_config = {'type': 'max_spend'} # Default
    if args.max_assets:
        objective_config = {'type': 'max_assets', 'value': args.max_assets}
    elif args.min_taxes:
        objective_config = {'type': 'min_taxes', 'value': args.min_taxes}

    # --- Use the FPlan class ---
    # The FPlan class will need to be updated to handle these new conversion args
    fplan = fc.FPlan(data, objective_config)

    fplan.solve(
        timelimit=args.timelimit,
        verbose=args.verbose,
        pessimistic_taxes=args.pessimistic_taxes,
        pessimistic_healthcare=args.pessimistic_healthcare,
        # Pass the new conversion flags to the solve method
        # The FPlan.solve() method and subsequently model_builder.prepare_pulp()
        # will need to be updated to accept and use these.
        allow_conversions=args.allow_conversions, # This will be True if explicitly set, or False if another option in the group is set or none are.
                                                  # We might need to adjust logic if --allow-conversions is the default.
        no_conversions=args.no_conversions,
        no_conversions_after_socsec=args.no_conversions_after_socsec
        # relTol_steps can be passed if you want to override the default in FPlan.solve
    )


    # --- Process Results ---
    if fplan.status in ["Optimal", "Not Solved"]: # Check status from FPlan object
        # get_results is called implicitly by the print methods if needed,
        # but calling it explicitly first is fine too.
        results = fplan.get_results()
        if results:
            if args.csv:
                fplan.print_results_csv()
            else:
                fplan.print_results_ascii()
        else:
            print("Failed to retrieve results even though solver status was acceptable.")
    else:
        print(f"Solver did not find an optimal/feasible solution (Status: {fplan.status}).")
        sys.exit(1)

if __name__== "__main__":
    main()