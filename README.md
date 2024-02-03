# Retirement planner

This is an independant fork of [Wayne Scott's fplan](https://www.github.com/wscott/fplan)
which is designed to explore optimial withdraws from savings and IRA accounts. It uses a Linear
Programming solution to maximize the minimum amount of money available
to spend.

This is similar to the ideas of James Welch at www.i-orp.com.  You should
probably look at [wscott/fplan](https://www.github.com/wscott/fplan) or [i-orp](https://www.i-orp.com) 
before you look at this project.

## Installing

This program is written in Python and can be installed locally with
`pip install --user .`.

I am new to Python packaging so hints to make this easier for people are appreciated

## Usage

* Copy `sample.toml` to a new file
* Edit with your information
* run `fplan NEW.toml`

## Output

The output is a table by age with the following columns. All numbers
in table are in 1000s of dollars.

* save: amount in after-tax savings account
* fsave: amount to pull from savings this year
* IRA: balance of tax-deferred IRA acount
* fIRA: amount to pull from IRA this year. (before 59 with penalty)
* Roth: balance of tax-exempt Roth account
* fRoth: amount to pull from Roth this year
* IRA2R: money converted from the IRA to Roth this year
* rate: US + state tax bracket this year
* tax: tax spent this year (includes IRA 10% penlty)
* spend: net amount spent this year (includes income)
* extra: additional spending this year

