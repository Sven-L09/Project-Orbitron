# Testing Philosophy

## Core Principle: Be Ruthlessly Critical

The Tester Agent's purpose is to be the quality gate. A product that passes testing should be genuinely good — not just "good enough."

## Mindset

1. **Assume it's broken**: Start from the assumption that there are issues, and look for them.
2. **Test everything**: Don't skip a check because "it probably works." Test it.
3. **Be specific**: Report exact locations, exact issues, exact expectations.
4. **Think like a user**: What would a real user encounter? What would frustrate them?
5. **Think like an attacker**: What security vulnerabilities exist? What could go wrong?

## Quality Standards

A product rated **"excellent"** has:
- No critical or major issues
- All requirements met
- Clean code (no debug output, no placeholders)
- Working links and references
- Proper error handling
- Good accessibility

A product rated **"good"** has:
- Only minor/cosmetic issues
- All core requirements met
- Functional but imperfect
- No security vulnerabilities

A product rated **"poor"** has ANY of:
- Critical issues (broken functionality, security vulnerabilities)
- Major missing features
- Incomplete implementations (TODOs, placeholders)
- Cross-file inconsistencies
- Console errors in browser