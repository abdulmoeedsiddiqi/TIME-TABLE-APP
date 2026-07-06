import pandas as pd
import sys

path = sys.argv[1]
xl = pd.ExcelFile(path)
print(f"Sheets: {xl.sheet_names}")
for s in xl.sheet_names:
    df = xl.parse(s, header=None)
    print(f"\n=== {s} ({len(df)} rows) ===")
    print(df.head(12).to_string())
