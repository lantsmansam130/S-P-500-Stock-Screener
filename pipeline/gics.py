"""GICS hierarchy helpers.

Wikipedia's constituent table carries the GICS Sector and Sub-Industry. The
middle layer (Industry Group, 25 groups) is what most sell-side coverage is
organised around, so we reconstruct it here from the sub-industry name.
Unknown sub-industries fall back to the sector name so nothing is dropped.
"""

SECTOR_ORDER = [
    "Information Technology",
    "Financials",
    "Health Care",
    "Consumer Discretionary",
    "Communication Services",
    "Industrials",
    "Consumer Staples",
    "Energy",
    "Utilities",
    "Real Estate",
    "Materials",
]

# Short labels for tight layouts (phone chips).
SECTOR_SHORT = {
    "Information Technology": "Tech",
    "Financials": "Financials",
    "Health Care": "Health Care",
    "Consumer Discretionary": "Discretionary",
    "Communication Services": "Comm Services",
    "Industrials": "Industrials",
    "Consumer Staples": "Staples",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Materials": "Materials",
}

GROUP_OF_SUB = {}

def _grp(group, subs):
    for s in subs:
        GROUP_OF_SUB[s] = group

# Energy
_grp("Energy", [
    "Integrated Oil & Gas", "Oil & Gas Equipment & Services",
    "Oil & Gas Exploration & Production", "Oil & Gas Refining & Marketing",
    "Oil & Gas Storage & Transportation", "Oil & Gas Drilling", "Coal & Consumable Fuels",
])
# Materials
_grp("Materials", [
    "Commodity Chemicals", "Specialty Chemicals", "Industrial Gases", "Diversified Chemicals",
    "Fertilizers & Agricultural Chemicals", "Construction Materials",
    "Metal, Glass & Plastic Containers", "Paper & Plastic Packaging Products & Materials",
    "Steel", "Copper", "Gold", "Aluminum", "Diversified Metals & Mining", "Forest Products",
    "Paper Products", "Precious Metals & Minerals", "Silver",
])
# Industrials
_grp("Capital Goods", [
    "Aerospace & Defense", "Building Products", "Construction & Engineering",
    "Electrical Components & Equipment", "Heavy Electrical Equipment", "Industrial Conglomerates",
    "Construction Machinery & Heavy Transportation Equipment", "Agricultural & Farm Machinery",
    "Industrial Machinery & Supplies & Components", "Trading Companies & Distributors",
])
_grp("Commercial & Professional Services", [
    "Diversified Support Services", "Environmental & Facilities Services",
    "Human Resource & Employment Services", "Research & Consulting Services",
    "Data Processing & Outsourced Services", "Commercial Printing", "Office Services & Supplies",
    "Security & Alarm Services",
])
_grp("Transportation", [
    "Air Freight & Logistics", "Passenger Airlines", "Rail Transportation",
    "Cargo Ground Transportation", "Passenger Ground Transportation", "Marine Transportation",
    "Airport Services", "Highways & Railtracks", "Marine Ports & Services",
])
# Consumer Discretionary
_grp("Automobiles & Components", [
    "Automotive Parts & Equipment", "Automobile Manufacturers", "Motorcycle Manufacturers",
    "Tires & Rubber",
])
_grp("Consumer Durables & Apparel", [
    "Homebuilding", "Leisure Products", "Apparel, Accessories & Luxury Goods", "Footwear",
    "Consumer Electronics", "Home Furnishings", "Household Appliances", "Housewares & Specialties",
    "Textiles",
])
_grp("Consumer Services", [
    "Casinos & Gaming", "Hotels, Resorts & Cruise Lines", "Restaurants",
    "Specialized Consumer Services", "Leisure Facilities", "Education Services",
])
_grp("Consumer Discretionary Distribution & Retail", [
    "Distributors", "Broadline Retail", "Apparel Retail", "Automotive Retail",
    "Computer & Electronics Retail", "Home Improvement Retail", "Homefurnishing Retail",
    "Other Specialty Retail",
])
# Consumer Staples
_grp("Consumer Staples Distribution & Retail", [
    "Food Distributors", "Food Retail", "Consumer Staples Merchandise Retail", "Drug Retail",
])
_grp("Food, Beverage & Tobacco", [
    "Distillers & Vintners", "Soft Drinks & Non-alcoholic Beverages", "Brewers",
    "Agricultural Products & Services", "Packaged Foods & Meats", "Tobacco",
])
_grp("Household & Personal Products", ["Household Products", "Personal Care Products"])
# Health Care
_grp("Health Care Equipment & Services", [
    "Health Care Equipment", "Health Care Supplies", "Health Care Distributors",
    "Health Care Services", "Health Care Facilities", "Managed Health Care",
    "Health Care Technology",
])
_grp("Pharmaceuticals, Biotechnology & Life Sciences", [
    "Biotechnology", "Pharmaceuticals", "Life Sciences Tools & Services",
])
# Financials
_grp("Banks", ["Diversified Banks", "Regional Banks"])
_grp("Financial Services", [
    "Transaction & Payment Processing Services", "Asset Management & Custody Banks",
    "Investment Banking & Brokerage", "Financial Exchanges & Data", "Consumer Finance",
    "Multi-Sector Holdings", "Diversified Financial Services", "Specialized Finance",
    "Commercial & Residential Mortgage Finance",
])
_grp("Insurance", [
    "Insurance Brokers", "Life & Health Insurance", "Multi-line Insurance",
    "Property & Casualty Insurance", "Reinsurance",
])
# Information Technology
_grp("Software & Services", [
    "IT Consulting & Other Services", "Internet Services & Infrastructure",
    "Application Software", "Systems Software",
])
_grp("Technology Hardware & Equipment", [
    "Communications Equipment", "Technology Hardware, Storage & Peripherals",
    "Electronic Components", "Electronic Equipment & Instruments",
    "Electronic Manufacturing Services", "Technology Distributors",
])
_grp("Semiconductors & Semiconductor Equipment", [
    "Semiconductor Materials & Equipment", "Semiconductors",
])
# Communication Services
_grp("Telecommunication Services", [
    "Integrated Telecommunication Services", "Wireless Telecommunication Services",
    "Alternative Carriers",
])
_grp("Media & Entertainment", [
    "Advertising", "Broadcasting", "Cable & Satellite", "Publishing", "Movies & Entertainment",
    "Interactive Home Entertainment", "Interactive Media & Services",
])
# Utilities
_grp("Utilities", [
    "Electric Utilities", "Gas Utilities", "Multi-Utilities", "Water Utilities",
    "Independent Power Producers & Energy Traders", "Renewable Electricity",
])
# Real Estate
_grp("Equity REITs", [
    "Data Center REITs", "Health Care REITs", "Hotel & Resort REITs", "Industrial REITs",
    "Multi-Family Residential REITs", "Office REITs", "Other Specialized REITs", "Retail REITs",
    "Self-Storage REITs", "Single-Family Residential REITs", "Telecom Tower REITs", "Timber REITs",
    "Diversified REITs",
])
_grp("Real Estate Management & Development", [
    "Real Estate Services", "Real Estate Development", "Real Estate Operating Companies",
    "Diversified Real Estate Activities",
])


def industry_group(sector: str, sub_industry: str) -> str:
    return GROUP_OF_SUB.get(sub_industry, sector)
