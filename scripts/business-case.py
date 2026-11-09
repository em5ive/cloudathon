"""Calculate a transparent planning scenario; no company financial data is inferred."""
import argparse
import json
import math
from pathlib import Path


def calculate(data):
    totals = {}
    for category in ["on_prem_annual", "target_annual", "one_time_transition"]:
        values = data[category]
        if not values or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in values.values()):
            raise ValueError(f"{category} must contain finite, nonnegative numeric amounts")
        totals[category] = round(sum(values.values()), 2)
    savings = round(totals["on_prem_annual"] - totals["target_annual"], 2)
    return {"scenario": data["scenario"], "currency": data.get("currency", "USD"), "totals": totals,
            "annual_savings_after_full_exit": savings,
            "break_even_months_after_full_exit": round(totals["one_time_transition"] / (savings / 12), 2) if savings > 0 else None,
            "assumptions": data.get("assumptions", []),
            "limitations": "Simple undiscounted payback starting after complete retirement and contract termination. Transition includes incremental overlap only; excludes taxes, financing, inflation, discounting and partial-wave savings. Staff savings require an actual cost reduction; redeployment of staff is capacity benefit, not automatic cash savings."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(calculate(json.loads(args.input.read_text(encoding="utf-8"))), indent=2))
    except (ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
