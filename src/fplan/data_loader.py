import re
import os
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

# Required Minimal Distributions from IRA starting with age 73
# last updated for 2024
RMD = [27.4, 26.5, 25.5, 24.6, 23.7, 22.9, 22.0, 21.1, 20.2, 19.4,  # age 72-81
       18.5, 17.7, 16.8, 16.0, 15.2, 14.4, 13.7, 12.9, 12.2, 11.5,  # age 82-91
       10.8, 10.1,  9.5,  8.9,  8.4,  7.8,  7.3,  6.8,  6.4,  6.0,  # age 92-101
        5.6,  5.2,  4.9,  4.6,  4.3,  4.1,  3.9,  3.7,  3.5,  3.4,  # age 102+
        3.3,  3.1,  3.0,  2.9,  2.8,  2.7,  2.5,  2.3,  2.0,  2.0]

def agelist(str_val):
    for x in str_val.split(','):
        m = re.match(r'^(\d+)(-(\d+)?)?$', x)
        if m:
            s = int(m.group(1))
            e = s
            if m.group(2):
                e = m.group(3)
                if e:
                    e = int(e)
                else:
                    e = 120
            for a in range(s,e+1):
                yield a
        else:
            raise Exception("Bad age " + str_val)

class Data:
    def load_config(self, config_source):
        """
        Loads configuration data either from a file path or a dictionary.

        Args:
            config_source: Either a string representing the file path
                           or a dictionary containing the configuration.
        """
        if isinstance(config_source, str):
            print(f"Loading configuration from file: {config_source}")
            with open(config_source, 'rb') as conffile: # Use 'rb' for tomllib
                d = tomllib.load(conffile)
        elif isinstance(config_source, dict):
            print("Loading configuration from dictionary.")
            d = config_source
        else:
            raise TypeError("config_source must be a file path (str) or a dictionary (dict)")

        self.i_rate = 1 + d.get('inflation', 0) / 100       # inflation rate: 2.5 -> 1.025
        self.r_rate = 1 + d.get('returns', 6) / 100         # invest rate: 6 -> 1.06

        self.startage = d['startage']
        self.halfage = self.startage
        self.birthmonth = d.get('birthmonth', 1)
        if (self.birthmonth >= 7):
            self.halfage = self.startage - 1.0
        self.endage = d.get('endage', max(96, self.startage+5)) + 1

        # 2023 tax table (could predict it moves with inflation?)
        # married joint at the moment, can override in config file
        default_taxrates = [[0,      10],
                            [22000,  12],
                            [89450 , 22],
                            [190750, 24],
                            [364200, 32],
                            [462500, 35],
                            [693750, 37]]
        default_stded = 27700
        default_state_taxrates = [[0, 0]]
        default_cg_taxrates = [[0,        0],
                               [89250,   15],
                               [553850,  20]]

        tmp_taxrates = default_taxrates
        tmp_state_taxrates = default_state_taxrates
        tmp_cg_taxrates = default_cg_taxrates
        self.stded = default_stded
        self.state_stded = default_stded
        self.nii = 250000
        self.fpl_amount = 0 # Initialize FPL amount

        state_abbr = None
        if 'taxes' in d:
            tmp_taxrates = d['taxes'].get('taxrates', default_taxrates)
            tmp_state_taxrates = d['taxes'].get('state_rate', default_state_taxrates)
            tmp_cg_taxrates = d['taxes'].get('cg_taxrates', default_cg_taxrates)
            if (type(tmp_state_taxrates) is not list):
                tmp_state_taxrates = [[0, tmp_state_taxrates]]
            self.stded = d['taxes'].get('stded', default_stded)
            self.state_stded = d['taxes'].get('state_stded', self.stded)
            self.nii = d['taxes'].get('nii', 250000)
            state_abbr = d['taxes'].get('state', None)

        # --- Load Federal Tax Data (Moved outside 'if taxes in d' to always load FPL if ACA info present) ---
        # This ensures FPL is loaded even if the [taxes] section is minimal or absent,
        # as long as ACA info is provided.
        federal_tax_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'reference', 'taxes_federal.toml')
        all_federal_data = None # Initialize to ensure it's defined
        try:
            filing_status = d['taxes'].get('filing_status', 'MFJ') # Default to MFJ if not specified
            print(f"Attempting to load federal tax data from: {federal_tax_file_path}")
            federal_section_key = f"Federal_{filing_status}"

            try:
                with open(federal_tax_file_path, 'rb') as f:
                    all_federal_data = tomllib.load(f)
                federal_data = all_federal_data.get(federal_section_key)
                if federal_data:
                    print(f"Found federal tax data for filing status: {filing_status}")
                    self.status = filing_status
                    tmp_taxrates = federal_data.get('brackets', tmp_taxrates)
                    self.stded = federal_data.get('standard_deduction', self.stded)
                    self.nii = federal_data.get('net_investment_income_threshold', self.nii)
                    tmp_cg_taxrates = federal_data.get('capital_gains_taxrates', tmp_cg_taxrates)
                else:
                    print(f"Warning: Federal tax section '{federal_section_key}' not found in {federal_tax_file_path}. Using default MFJ values.")
            except FileNotFoundError:
                print(f"Warning: Federal tax file not found at {federal_tax_file_path}. Using default MFJ values.")
            except Exception as e:
                print(f"Error loading federal tax data: {e}. Using default MFJ values.")
        except Exception as e: # Catch errors if 'taxes' or 'filing_status' is missing
            print(f"Could not determine filing status for federal tax load: {e}. Using default MFJ values for rates/stded/nii.")
            # Ensure all_federal_data is loaded if only filing_status was the issue, for FPL.
            if not all_federal_data and os.path.exists(federal_tax_file_path):
                 with open(federal_tax_file_path, 'rb') as f:
                    all_federal_data = tomllib.load(f)

        # --- State Tax Loading Logic ---
        if state_abbr: # state_abbr is defined if 'taxes' and 'state' are in config
            state_abbr = state_abbr.upper()
            filing_status_for_state = d.get('taxes', {}).get('filing_status', 'MFJ') # Get filing_status again for state context
            state_tax_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'reference', 'taxes_state.toml')
            print(f"Attempting to load state tax data from: {state_tax_file_path}")
            try:
                with open(state_tax_file_path, 'rb') as f: # Use 'rb' for tomllib
                    all_state_data_toml = tomllib.load(f) # Renamed to avoid conflict
                heading = f'{state_abbr}_{filing_status_for_state}'
                state_data = all_state_data_toml.get(heading)
                if state_data:
                    print(f"Found tax data for state: {heading}")
                    self.state_status = heading
                    tmp_state_taxrates = state_data.get('brackets', default_state_taxrates)
                    self.state_stded = state_data.get('standard_deduction', 0)
                    self.state_taxes_ss = state_data.get('tax_social_security', True)
                    self.state_taxes_retirement_income = state_data.get('tax_retirement_income', True)
                else:
                    print(f"Warning: State abbreviation '{heading}' not found in {state_tax_file_path}. Defaulting to no state tax.")
                    tmp_state_taxrates = default_state_taxrates
                    self.state_stded = 0
            except FileNotFoundError:
                print(f"Warning: State tax file not found at {state_tax_file_path}. Defaulting to no state tax.")
                tmp_state_taxrates = default_state_taxrates
                self.state_stded = 0

        # --- FPL Lookup ---
        self.aca = d.get('aca', {'premium': 0, 'slcsp': 0, 'covered': 1})
        aca_covered_people = self.aca.get('covered', 1)
        # Use state_abbr from taxes section if available, otherwise default or handle error
        fpl_state_key_suffix = ""
        if state_abbr == "AK":
            fpl_state_key_suffix = "_AK"
        elif state_abbr == "HI":
            fpl_state_key_suffix = "_HI"

        fpl_section_key = f"FPL{fpl_state_key_suffix}"
        
        if all_federal_data and fpl_section_key in all_federal_data:
            fpl_table = dict(all_federal_data[fpl_section_key].get('fpl', []))
            self.fpl_amount = fpl_table.get(aca_covered_people, fpl_table.get(min(fpl_table.keys(), key=lambda k: abs(k-aca_covered_people)), 0)) # Get for covered, or closest, or 0
            print(f"FPL for {aca_covered_people} people in {state_abbr or 'N/A'} ({fpl_section_key}): {self.fpl_amount}")
        else:
            print(f"Warning: FPL section '{fpl_section_key}' not found in federal tax data or federal data not loaded. FPL set to 0.")
            self.fpl_amount = 0

        self.taxrates = [[x,y/100.0] for (x,y) in tmp_taxrates]
        cutoffs = [x[0] for x in self.taxrates][1:] + [1e8]
        self.taxtable = list(map(lambda x, y: [x[1], x[0], y], self.taxrates, cutoffs))
        self.state_taxrates = [[x,y/100.0] for (x,y) in tmp_state_taxrates]
        cutoffs = [x[0] for x in self.state_taxrates][1:] + [1e8]
        self.state_taxtable = list(map(lambda x, y: [x[1], x[0], y], self.state_taxrates, cutoffs))
        self.cg_taxrates = [[x,y/100.0] for (x,y) in tmp_cg_taxrates]
        cutoffs = [x[0] for x in self.cg_taxrates][1:] + [1e8]
        self.cg_taxtable = list(map(lambda x, y: [x[1], x[0], y], self.cg_taxrates, cutoffs))

        # vper calculations not needed for PuLP variable setup
        self.retireage = self.startage
        self.numyr = self.endage - self.retireage

        self.aftertax = d.get('aftertax', {'bal': 0})
        if 'basis' not in self.aftertax:
            self.aftertax['basis'] = 0
        if 'distributions' not in self.aftertax:
            self.aftertax['distributions'] = 0.0
        self.aftertax['distributions'] *= 0.01

        self.IRA = d.get('IRA', {'bal': 0})

        self.roth = d.get('roth', {'bal': 0})
        if 'contributions' not in self.roth:
            self.roth['contributions'] = []

        print(self.taxtable)
        print(self.state_taxtable)

        self.parse_expenses(d)

    def parse_expenses(self, S):
        """ Return array of income/expense per year """
        INC = [0] * self.numyr
        INC_SS = [0] * self.numyr
        EXP = [0] * self.numyr
        TAX = [0] * self.numyr
        TAX_SS = [0] * self.numyr
        STATE_TAX = [0] * self.numyr
        STATE_TAX_SS = [0] * self.numyr
        CEILING = [50_000_000] * self.numyr

        for k,v in S.get('expense', {}).items():
            for age in agelist(v['age']):
                year_idx = age - self.retireage
                if 0 <= year_idx < self.numyr:
                    amount = v['amount']
                    if v.get('inflation'):
                        # Inflation applies from start age
                        amount *= self.i_rate ** (age - self.startage)
                    EXP[year_idx] += amount

        for k,v in S.get('income', {}).items():
            firstyear = True
            for age in agelist(v['age']):
                year_idx = age - self.retireage
                if 0 <= year_idx < self.numyr:
                    ceil = v.get('ceiling', 50_000_000)
                    if v.get('inflation'):
                        # Inflation applies from start age
                         ceil *= self.i_rate ** (age - self.startage)
                    CEILING[year_idx] = min(CEILING[year_idx], ceil)

                    amount = v['amount']
                    if v.get('inflation') or (k == 'social_security'):
                        # Inflation applies from start age
                        amount *= self.i_rate ** (age - self.startage)

                    is_taxable = v.get('tax', (k == 'social_security'))
                    is_state_taxable = v.get('state_tax', is_taxable) # Defaults to federal taxability

                    if k == 'social_security':
                        # Social Security taxability
                        prorated_amount = amount if not firstyear else (13 - self.birthmonth) / 12 * amount
                        INC_SS[year_idx] += prorated_amount
                        TAX_SS[year_idx] += prorated_amount * 0.85
                        if self.state_taxes_ss:
                            STATE_TAX_SS[year_idx] += prorated_amount * 0.85
                    else:
                        # Other income taxability
                        INC[year_idx] += amount
                        if is_taxable:
                            TAX[year_idx] += amount
                        if is_state_taxable:
                            STATE_TAX[year_idx] += amount
                firstyear = False
        self.income = INC
        self.expenses = EXP
        self.taxed_income = TAX
        self.state_taxed_income = STATE_TAX
        self.social_security = INC_SS
        self.social_security_taxed = TAX_SS
        self.state_social_security_taxed = STATE_TAX_SS
        self.income_ceiling = CEILING
