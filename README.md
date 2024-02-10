# Retirement planner

This is an independant fork of [Wayne Scott's fplan](https://www.github.com/wscott/fplan). It is designed to explore optimal withdrawals from savings, Roth and IRA accounts. It uses a mixed-integer linear programming solution to maximize the minimum amount of money available to spend.

The ideas are similar to those of James Welch at www.i-orp.com.  You should probably look at [i-orp](https://www.i-orp.com) or [wscott/fplan](https://www.github.com/wscott/fplan) before you look at this project.

## Installing

This program is written in Python and can be installed locally with
`pip install --user .`.

## Usage

* Copy `examples/sample.toml` to a new file
* Edit with your information.  Take a close look at sample.toml and dcsingle.toml in the examples directory to see what the program supports.
* run `fplan NEW.toml`

## Output

The output is a table by age with the following columns. All numbers
in table are in 1000s of dollars.

* save: amount in taxable brokerage account
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

## Command-line Options

### --verbose
Shows the progress of the solver as it attempts to maximize your spending floor.

### --timelimit N
Usually the program gives you an answer within a few seconds.  In the event that it can't find the answer quickly it will return the best answer that it has found after 300 seconds (5 minutes).  If you want to wait longer then you can specify how long, in seconds, that you are willing to wait with this option.  I recommend that you use the --verbose option in conjunction with this argument so you can see that progress is being made.

### --csv
Outputs your answer in csv format instead of a table.

### --spend N
Instead of solving to maximize your spending floor, this option will solve for the given amount of spending while minimizing lifetime taxes.

### --roth N
Solves to maximize your spending floor while leaving at least N dollars, in inflation adjusted terms, in your Roth account at the end of your plan.

### --bumpstart Y --bumptax T
This program doesn't try to model what will happen when the TCJA expires.  However, you can use these options to get a rough idea by modeling what would happen if all of the federal income tax bracket levels increased by T after Y years.  So if you wanted to see what the program would suggest if all of the tax brackets added 2.5 (like 10% -> 12.5%, 12% -> 14.5%, etc) in 2 years, then you would use the options: --bumpstart 2 --bumptax 2.5

## Why
This program adds some features that other progams lack, such as:
* State tax brackets
* Capital gains tax brackets
* Net investment income (NII) tax
* Year-end capital gains and qualified dividend distributions
    * The program assumes they are taxed in the year they are received and then spent in the following year

## What's missing
There are a few things that could be added to make this more complete.  The program does not currently take into account any of the following:
* Taxability of social security
    * If set to taxable it calculates 100% taxable
    * If set to not taxable it calculates 0% taxable
* HSA
* AMT
* IRMAA

## State tax
Every state has their own rules.  I did not try to implement them all.  I put in enough to model my state and I believe many others.  The following things are assumed about state taxes (and cannot be changed in your config file):
* Withdrawals from your IRA are taxed as income in your state
* Capital gains are taxed as income in your state

## Known Issues
Check the issues tab for updates.  This is what I'm currently aware of:
* RMDs still use the old rules for ages
* Basis calcuations for capital-gains taxes are estimates
    * The programs fixes your basis percentage at retirement by using the original basis number in your config file.  The basis percentage in retirement never changes.  I'm not sure if this estimate can be improved in a program of this type.
