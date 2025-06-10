import os
from flask import Flask, request, jsonify
from flask_cors import CORS # Import CORS
import traceback
import logging

from ddcalc.core.data_loader import Data
from ddcalc.ddcalc import DDCalc

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
# Configure CORS more explicitly.
# For development, origins="*" is okay. 
# For production, replace "*" with your specific frontend domain(s),
# e.g., origins=["http://localhost:3000", "https://your-frontend-domain.com"]
# --- CORS Configuration ---
# Determine the environment
FLASK_ENV = os.environ.get('FLASK_ENV', 'production') # Default to production if not set

if FLASK_ENV == 'development':
    # For development, allow specific local origins or a wildcard if you're frequently changing ports/hosts
    # Example: "http://localhost:3000,http://127.0.0.1:3000"
    # Using "*" is also common in dev but less secure if your dev machine is network-accessible.
    allowed_origins_str = os.environ.get('DEV_CORS_ORIGINS', "http://localhost:*,http://127.0.0.1:*")
    logging.info(f"Development CORS origins: {allowed_origins_str}")
else: # Production or other environments
    # For production, always use specific, trusted domains.
    # Example: "https://your-app.com,https://www.your-app.com"
    allowed_origins_str = os.environ.get('PROD_CORS_ORIGINS')
    if not allowed_origins_str:
        logging.info("PROD_CORS_ORIGINS environment variable is not set! Using defaults")
        # Fallback to a very restrictive or no-origin policy if not set,
        # or raise an error to prevent insecure deployment.
        # For now, let's default to an empty list, which means no 
        allowed_origins_str = "https://drawdowncalc.com,https://www.drawdowncalc.com,https://https://ddcalcweb-862640917698.us-central1.run.app"
    else:
        logging.info(f"Production CORS origins: {allowed_origins_str}")

# Split the string into a list of origins
allowed_origins = [origin.strip() for origin in allowed_origins_str.split(',') if origin.strip()] if allowed_origins_str else []

# If in development and no DEV_CORS_ORIGINS is set, but you want a default for local Next.js
if FLASK_ENV == 'development' and not allowed_origins:
    allowed_origins = ["http://localhost:*", "http://127.0.0.1:*"] # Sensible default for local dev

CORS(app,
     origins=allowed_origins, # Use the dynamically determined list
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"],
     supports_credentials=True, # Set to True if your frontend sends cookies or Authorization headers
     expose_headers=["Content-Length"]) # Optional: if your frontend needs to read non-simple response headers

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
    # Set FLASK_ENV for local development if not already set externally
    if not os.environ.get('FLASK_ENV'):
        os.environ['FLASK_ENV'] = 'development'
        logging.info("FLASK_ENV not set, defaulting to 'development' for local run.")

    app.run(debug=(os.environ.get('FLASK_ENV') == 'development'),
            host='0.0.0.0',
            port=int(os.environ.get("PORT", 5001)))

if __name__ == '__main__':
    main()