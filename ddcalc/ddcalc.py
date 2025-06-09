import pulp
import argparse # We'll use Namespace to mimic args
import logging

# Attempt relative imports for use within the package
from .core.model_builder import prepare_pulp
from .core.results_processor import retrieve_results, print_ascii, print_csv

class DDCalc:
    """
    Encapsulates the financial planning model setup, solving, and results processing.
    """
    def __init__(self, data, objective_config=None):
        """
        Initializes the DDCalc object.

        Args:
            data: An instance of the Data class with loaded configuration.
            objective_config (dict, optional): Defines the primary objective.
                Example: {'type': 'max_spend'}
                         {'type': 'max_assets', 'value': 100000}
                         {'type': 'min_taxes', 'value': 100000}
                Defaults to {'type': 'max_spend'}.
        """
        self.data = data
        self.prob = None
        self.solver = None
        self.objectives = None
        self.results = None
        self.S_out = None
        self.status = None

        # Set default objective if not provided
        if objective_config is None:
            self.objective_config = {'type': 'max_spend'}
        else:
            self.objective_config = objective_config
        logging.debug(objective_config)

    def solve(self, timelimit=None, verbose=False, pessimistic_taxes=False, pessimistic_healthcare=False, 
              allow_conversions=True, no_conversions=False, no_conversions_after_socsec=False,
              relTol_steps=[1.0, 0.9999, 0.999, 0.99]):
        """
        Prepares and solves the linear programming problem.

        Args:
            timelimit (int, optional): Time limit for the solver in seconds.
            verbose (bool): Enable verbose solver output.
            pessimistic_taxes (bool): Use pessimistic tax assumptions.
            pessimistic_healthcare (bool): Use pessimistic healthcare cost assumptions.
            relTol_steps (list): Relative tolerance steps for sequential solve.
        """
        # Create a mock 'args' object for prepare_pulp
        mock_args = argparse.Namespace(
            verbose=verbose,
            timelimit=timelimit,
            pessimistic_taxes=pessimistic_taxes,
            pessimistic_healthcare=pessimistic_healthcare,
            allow_conversions=allow_conversions,
            no_conversions=no_conversions,
            no_conversions_after_socsec=no_conversions_after_socsec,
            max_spend=(self.objective_config.get('type') == 'max_spend'),
            max_assets=self.objective_config.get('value') if self.objective_config.get('type') == 'max_assets' else None,
            min_taxes=self.objective_config.get('value') if self.objective_config.get('type') == 'min_taxes' else None,
            # Add other args defaults if prepare_pulp needs them
        )

        logging.info("Starting PuLP solver...")
        for relTol in relTol_steps:
            self.prob, self.solver, self.objectives = prepare_pulp(mock_args, self.data)
            # print(f"Searching solution with relTol={relTol}")
#            self.objectives = [self.objectives[0]] # If you only want the primary objective
            self.prob.sequentialSolve(self.objectives, relativeTols=[relTol]*len(self.objectives), solver=self.solver)
            self.status = pulp.LpStatus[self.prob.status]
            if self.status == "Optimal":
                logging.info(f"Found solution with relTol={relTol}")
                break
            else:
                logging.info(f"Solver status: {self.status} with relTol={relTol}")
                if relTol != relTol_steps[-1]:
                    logging.info("Trying with a less strict tolerance...")

        logging.info(f"Final solver status: {self.status}")

    def get_results(self):
        """
        Processes and returns the results if the solver was successful.

        Returns:
            list: A list of dictionaries representing the yearly plan results,
                  or None if solving failed or hasn't been run.
        """
        if self.prob is None or self.status is None:
            logging.info("Solver has not been run yet.")
            return None

        # Not Solved can occur with time limit but might have a feasible solution
        if self.prob.status not in [pulp.LpStatusOptimal, pulp.LpStatusNotSolved]:
             logging.info(f"Solver did not find an optimal/feasible solution (Status: {self.status}).")
             return None

        # Create a minimal mock 'args' for retrieve_results if needed
        # Often, retrieve_results might only need S and prob
        mock_args_results = argparse.Namespace(
            # Add any args needed by retrieve_results, e.g., csv=False
        )

        self.results, self.S_out, self.prob = retrieve_results(mock_args_results, self.data, self.prob)

        if self.results is None:
            logging.info("Failed to retrieve results from the solver.")
            return None

        # Assuming results is the list of dictionaries ready for JSON
        return self.results

    def print_results_ascii(self):
        """Prints the results in ASCII table format."""
        if self.results and self.S_out:
            print_ascii(self.results, self.S_out)
        else:
            print("No results available to print.")

    def print_results_csv(self):
        """Prints the results in CSV format."""
        if self.results and self.S_out:
            print_csv(self.results, self.S_out)
        else:
            print("No results available to print.")