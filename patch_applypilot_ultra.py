import re, sys, pathlib

p = pathlib.Path("/home/andhe001/projects/ux_job_scraper/applypilot_ux.py")
src = p.read_text(encoding="utf-8")

def sub(pattern, repl, text, flags=re.DOTALL):
    new, n = re.subn(pattern, repl, text, flags=flags)
    if n == 0:
        print(f"[WARN] No match for pattern:\n{pattern[:120]}...")
    else:
        print(f"[OK] Replaced {n} occurrence(s).")
    return new

# A) Replace the whole build_cover_message() with a new version that supports summaries
pattern_a = r'''def\s+build_cover_message\(\)\s*->\s*str:\s*return\s*f""".*?"""'''
repl_a = r'''def build_cover_message(provider_summary: str = "", flags_summary: str = "") -> str:
    return f"""Hello,

Attached is today’s batch of {ROLE_FAMILY} opportunities.

Signals we care about:
- Presales motions: discovery/demo/POC/RFI-RFP
- Tech: APIs/integrations, auth (OAuth/SAML/SSO), Linux/Python/SQL, cloud
- Remote friendly, US or AU eligible preferred

Work rights: US green card + SSN; Australian citizen.

{("Providers: " + provider_summary) if provider_summary else ""}
{("Run flags: " + flags_summary) if flags_summary else ""}
"''' + '""' + '""' + r''''
'''
# (the odd quoting above avoids confusing the shell with triple-quotes)

src = sub(pattern_a, repl_a, src)

# B) Replace `body = build_cover_message()` call with a short preamble that computes summaries
pattern_b = r'''body\s*=\s*build_cover_message\(\)'''
repl_b = r'''# Prepare email body summaries
provider_counts = {}
for _j in jobs:
    provider_counts[_j.source] = provider_counts.get(_j.source, 0) + 1
provider_summary = ", ".join(f"{k}:{v}" for k, v in sorted(provider_counts.items(), key=lambda kv: (-kv[1], kv[0])))

flags_summary = " ".join(arg for arg in [
    "--loose" if args.loose else "",
    "--strict" if args.strict else "",
    f"--min-score {args.min_score}",
    f"--days {args.days}",
    f"--max {args.max}",
] if arg)

body = build_cover_message(provider_summary, flags_summary)'''

src = sub(pattern_b, repl_b, src, flags=re.DOTALL)

p.write_text(src, encoding="utf-8")
print("[OK] Patches applied to", p)
