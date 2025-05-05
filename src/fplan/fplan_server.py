import sys
import os
from flask import Flask, request, jsonify
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

        # You might want to pass objective config from the request data if needed
        # objective_cfg = config_data.get('objective', {'type': 'max_spend'})
        fplan = FPlan(data)
        fplan.solve()
        results = fplan.get_results() # Assuming get_results() returns serializable data

        return jsonify(results)
    except Exception as e:
        traceback.print_exc() # Print detailed error to server console
        return jsonify({"error": f"Calculation failed: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001) # Run on port 5001, accessible externally