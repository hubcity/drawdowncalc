import os
from flask import Flask, request, jsonify
from flask_cors import CORS # Import CORS
import traceback
import logging

from ddcalc.core.data_loader import Data
from ddcalc.ddcalc import DDCalc

logging.basicConfig(level=logging.WARNING)

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

        ddcalc = DDCalc(data, objective_config=objective_cfg)
        ddcalc.solve(pessimistic_taxes=pessimistic_taxes_val, 
                    pessimistic_healthcare=pessimistic_healthcare_val,
                    allow_conversions=allow_conversions_val,
                    no_conversions=no_conversions_val,
                    no_conversions_after_socsec=no_conversions_after_socsec_val)
        results = ddcalc.get_results() # Assuming get_results() returns serializable data
#       logging.debug(jsonify(results))
        return jsonify(results)
    except Exception as e:
        traceback.print_exc() # Print detailed error to server console
        return jsonify({"error": f"Calculation failed: {str(e)}"}), 500

def main():
    """Entry point for running the Flask server."""
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5001))) # Example run command, adjust as needed

if __name__ == '__main__':
    main()