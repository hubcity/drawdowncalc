import sys
import os
from flask import Flask, request, jsonify
from flask_cors import CORS # Import CORS
import traceback

# Add the parent directory to sys.path to allow imports from fplan
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

try:
    from fplan.data_loader import Data
    from fplan.fplan_class import FPlan
except ImportError as e:
    print(f"Error importing fplan modules: {e}")
    print(f"Current sys.path: {sys.path}")
    sys.exit(1)

app = Flask(__name__)
CORS(app) # Enable CORS for all routes and origins by default

@app.route('/calculate', methods=['POST'])
def calculate_plan():
    """
    Calculates the financial plan based on the config JSON provided in the request body.
    """
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    config_data = request.get_json()

    try:
        data = Data()
        data.load_config(config_data) # Use the modified load_config method

        # Extract arguments from the payload
        args_data = config_data.get('arguments', {})
        objective_cfg = args_data.get('objective', {'type': 'max_spend'}) # Default if not provided
        pessimistic_taxes_val = args_data.get('pessimistic_taxes', False)
        pessimistic_healthcare_val = args_data.get('pessimistic_healthcare', False)
        allow_conversions_val = args_data.get('allow_conversions', True)
        no_conversions_val = args_data.get('no_conversions', False)
        no_conversions_after_socsec_val = args_data.get('no_conversions_after_socsec', False)

        fplan = FPlan(data, objective_config=objective_cfg)
        fplan.solve(pessimistic_taxes=pessimistic_taxes_val, 
                    pessimistic_healthcare=pessimistic_healthcare_val,
                    allow_conversions=allow_conversions_val,
                    no_conversions=no_conversions_val,
                    no_conversions_after_socsec=no_conversions_after_socsec_val)
        results = fplan.get_results() # Assuming get_results() returns serializable data
#        print(jsonify(results))
        return jsonify(results)
    except Exception as e:
        traceback.print_exc() # Print detailed error to server console
        return jsonify({"error": f"Calculation failed: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001) # Run on port 5001, accessible externally