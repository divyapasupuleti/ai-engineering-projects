"""Permission checks run before every tool call: role, schema, rate limit, risk -> allow / approve / deny."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sandbox_tools import REGISTRY

INJECTION_RE = re.compile(
    r"ignore (all |any )?(previous|prior) instructions|disregard .*instructions|you are now|"
    r"send .* to .*@(?!company\.com)|exfiltrate|reveal (the )?system prompt",
    re.I,
)


@dataclass
class PolicyDecision:
    verdict: str  # allow | needs_approval | deny
    reason: str


def check_call(tool_name: str, args: dict, role: str, calls_so_far: dict[str, int], tainted: bool) -> PolicyDecision:
    tool = REGISTRY.get(tool_name)
    if tool is None:
        return PolicyDecision("deny", f"unknown tool '{tool_name}'")
    if role not in tool.roles:
        return PolicyDecision("deny", f"role '{role}' may not call {tool_name}")
    errors = tool.validate(args)
    if errors:
        return PolicyDecision("deny", "invalid args: " + "; ".join(errors))
    if tool_name == "send_email" and not str(args["to"]).endswith("@company.com"):
        return PolicyDecision("deny", f"external recipient {args['to']} blocked by data-egress policy")
    if calls_so_far.get(tool_name, 0) >= tool.rate_limit_per_run:
        return PolicyDecision("deny", f"rate limit {tool.rate_limit_per_run}/run reached for {tool_name}")
    if tainted and tool.writes:
        return PolicyDecision("needs_approval", "write action after untrusted content was read")
    if tool.risk == "high":
        return PolicyDecision("needs_approval", f"{tool_name} is high risk")
    return PolicyDecision("allow", f"{tool.risk} risk, role permitted")


def scan_untrusted(text: str) -> list[str]:
    """Tool output is data, never instructions: flag text that tries to steer the agent."""
    return [m.group(0) for m in INJECTION_RE.finditer(text)]
