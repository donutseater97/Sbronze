from morningstar_fund_scraper import Fund as Fund, FundException as FundException
from morningstar_fund_scraper import Fund

# Initialize the Fund object with an optional perfid parameter
fund = Fund(perfid="F00000PYZ6")

# Get the latest Net Asset Value (NAV) data for the fund
nav_data = fund.get_nav()

print(nav_data)