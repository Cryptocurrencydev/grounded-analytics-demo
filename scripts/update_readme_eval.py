"""Writes the eval table in the README from eval/results.json, so the numbers can't drift."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
r = json.loads((ROOT / "eval" / "results.json").read_text())
b, g = r["summary"]["baseline"], r["summary"]["grounded"]


def pair(k):
    return f"{b[k + '_correct']} / {b[k + '_total']}", f"{g[k + '_correct']} / {g[k + '_total']}"


rows = [
    ("Numeric answers correct", *pair("numeric")),
    ("Significance calls correct", *pair("significance")),
    ("Answers with an unsupported figure", b["answers_with_unsupported_figures"], g["answers_with_unsupported_figures"]),
    ("Unsupported figures in total", b["unsupported_figures"], g["unsupported_figures"]),
    ("Correct refusals (unanswerable, tiny samples)", *pair("refusal")),
    ("Refused an answerable question", b["over_refusals"], g["over_refusals"]),
    ("Input tokens, all questions", f"{b['input_tokens']:,}", f"{g['input_tokens']:,}"),
    ("Mean time per answer", f"{b['mean_latency_s']} s", f"{g['mean_latency_s']} s"),
]
table = "| | Naive baseline: raw rows in the prompt | Grounded: tools + validator |\n|---|---|---|\n"
table += "".join(f"| {a} | {x} | {y} |\n" for a, x, y in rows)
note = (
    f"\n{len(r['questions'])} questions, one run each, on {r['generated_at'][:10]} with `{r['model']}`. Expected answers are computed "
    f"from the Parquet file with pandas, a separate path from the app's DuckDB code. Both systems get the same rules. "
    f"The baseline ran at effort `{r['effort']['baseline']}` and the grounded system at `{r['effort']['grounded']}`.\n"
)
readme = ROOT / "README.md"
text = readme.read_text()
text = re.sub(r"<!-- eval:start -->.*<!-- eval:end -->", lambda _: f"<!-- eval:start -->\n{table}{note}<!-- eval:end -->", text, flags=re.S)
readme.write_text(text)
print("README updated")
