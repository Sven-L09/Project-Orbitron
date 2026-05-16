# Testing Philosophy

## Core Principle: Be Ruthlessly Critical

The Tester Agent's purpose is to be the quality gate. A product that passes testing should be genuinely good — not just "good enough."

## Mindset

1. **Assume it's broken**: Start from the assumption that there are issues, and look for them.
2. **Test everything**: Don't skip a check because "it probably works." Test it.
3. **Be specific**: Report exact locations, exact issues, exact expectations.
4. **Think like a user**: What would a real user encounter? What would frustrate them?
5. **Think like an attacker**: What security vulnerabilities exist? What could go wrong?
6. **Think like a designer**: Does it LOOK professional? Would you be proud to show this to a client?

## Professional Quality Standards

A product rated **"excellent"** has:
- No critical or major issues
- All requirements met
- Clean code (no debug output, no placeholders)
- Working links and references
- Proper error handling
- Good accessibility
- **Professional visual design** — clean spacing, consistent typography, harmonious colors
- **Polished UX** — intuitive navigation, clear hierarchy, smooth interactions
- **Responsive** — works perfectly on mobile, tablet, and desktop

A product rated **"good"** has:
- Only minor/cosmetic issues
- All core requirements met
- Functional and visually acceptable
- No security vulnerabilities
- **Still looks professional** — no amateur design patterns

A product rated **"poor"** has ANY of:
- Critical issues (broken functionality, security vulnerabilities)
- Major missing features
- Incomplete implementations (TODOs, placeholders)
- Cross-file inconsistencies
- Console errors in browser
- **Poor visual design** — misaligned elements, inconsistent spacing, ugly colors
- **Poor UX** — confusing navigation, missing feedback, inaccessible
- **Not responsive** — broken on mobile or tablet

## Visual & UX Quality Checks (MANDATORY)

### Spacing & Layout
- Are margins, paddings, and gaps consistent throughout?
- Are elements properly aligned (left, center, right)?
- Is there enough whitespace between sections?
- Does the grid system work correctly?

### Typography
- Is the font hierarchy clear (H1 > H2 > H3 > body)?
- Are font sizes appropriate for the content type?
- Is line-height comfortable for reading?

### Colors & Contrast
- Do colors work together harmoniously?
- Is there sufficient contrast for text readability (WCAG AA minimum)?
- Are interactive elements visually distinguishable?

### Interactions
- Do buttons have hover states?
- Are there transitions/animations for state changes?
- Is there visual feedback for user actions?
- Are focus states visible for keyboard navigation?

### Responsive Design
- Does the layout adapt to mobile (< 768px)?
- Does it work on tablet (768-1024px)?
- Does it work on desktop (> 1024px)?
- Are there any overflow or clipping issues?