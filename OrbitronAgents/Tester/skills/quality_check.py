"""Quality Check Skill for the Tester Agent.

Provides tools for inspecting file contents, checking code quality,
validating HTML/CSS/JS structure, and detecting common issues.
"""

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("QualityCheckSkill")


class QualityCheckSkill:
    """Skill for performing quality checks on generated artifacts.

    This skill provides read-only inspection tools. It does NOT modify any files.
    """

    name = "quality_check"
    description = "Tools for inspecting and validating file quality without modifying them"

    def get_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions for the quality check skill."""
        return [
            {
                "name": "inspect_file",
                "description": "Read and analyze a file for quality issues. Returns content stats, structure info, and potential problems.",
                "schema": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to inspect"},
                        "check_type": {
                            "type": "string",
                            "enum": ["general", "html", "css", "javascript", "python", "json"],
                            "description": "Type of quality check to perform (default: general)",
                        },
                    },
                },
            },
            {
                "name": "check_html_structure",
                "description": "Validate HTML file structure: proper doctype, balanced tags, required elements, link integrity, accessibility basics.",
                "schema": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "description": "Path to the HTML file"},
                        "check_links": {
                            "type": "boolean",
                            "description": "Whether to check that linked resources exist (default: true)",
                        },
                        "check_accessibility": {
                            "type": "boolean",
                            "description": "Whether to check basic accessibility (alt texts, ARIA labels) (default: true)",
                        },
                    },
                },
            },
            {
                "name": "check_code_quality",
                "description": "Analyze code quality: dead code, unused variables, missing error handling, code smells, security issues.",
                "schema": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "description": "Path to the code file"},
                        "language": {
                            "type": "string",
                            "enum": ["javascript", "python", "html", "css"],
                            "description": "Programming language of the file (default: auto-detect)",
                        },
                    },
                },
            },
            {
                "name": "check_cross_file_consistency",
                "description": "Check consistency across multiple files: shared imports, matching references, consistent naming, cross-page navigation.",
                "schema": {
                    "type": "object",
                    "required": ["paths"],
                    "properties": {
                        "paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of file paths to check for cross-file consistency",
                        },
                        "project_root": {
                            "type": "string",
                            "description": "Root directory of the project for resolving relative paths",
                        },
                    },
                },
            },
            {
                "name": "check_requirements_coverage",
                "description": "Check whether a product meets its original requirements by comparing requirements against the actual implementation.",
                "schema": {
                    "type": "object",
                    "required": ["requirements", "artifact_paths"],
                    "properties": {
                        "requirements": {
                            "type": "string",
                            "description": "The original requirements or task description to check against",
                        },
                        "artifact_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Paths to the artifact files to check",
                        },
                    },
                },
            },
        ]

    def get_handlers(self) -> dict[str, Any]:
        """Return handler functions for each tool."""
        return {
            "inspect_file": self.inspect_file,
            "check_html_structure": self.check_html_structure,
            "check_code_quality": self.check_code_quality,
            "check_cross_file_consistency": self.check_cross_file_consistency,
            "check_requirements_coverage": self.check_requirements_coverage,
        }

    # ========== Tool Implementations ==========

    def inspect_file(self, args: dict[str, Any]) -> dict[str, Any]:
        """Inspect a file and report quality statistics."""
        path = args.get("path", "")
        check_type = args.get("check_type", "general")

        file_path = Path(path)
        if not file_path.exists():
            return {"ok": False, "error": f"File not found: {path}"}
        if not file_path.is_file():
            return {"ok": False, "error": f"Not a file: {path}"}

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"ok": False, "error": f"Cannot read file: {e}"}

        lines = content.split("\n")
        stats = {
            "path": str(file_path),
            "size_bytes": file_path.stat().st_size,
            "line_count": len(lines),
            "non_empty_lines": sum(1 for line in lines if line.strip()),
            "extension": file_path.suffix.lower(),
        }

        issues = []

        # Check for placeholder content
        placeholders = ["todo", "tbd", "fixme", "hack", "lorem ipsum", "xxx", "placeholder"]
        for i, line in enumerate(lines, 1):
            lower_line = line.lower()
            for placeholder in placeholders:
                if placeholder in lower_line:
                    issues.append({
                        "severity": "major",
                        "type": "placeholder_content",
                        "line": i,
                        "description": f"Found placeholder '{placeholder}' on line {i}",
                    })

        # Check for empty file
        if len(content.strip()) == 0:
            issues.append({
                "severity": "critical",
                "type": "empty_file",
                "description": "File is empty",
            })
        elif len(content.strip()) < 20:
            issues.append({
                "severity": "major",
                "type": "minimal_content",
                "description": f"File has only {len(content.strip())} characters — likely incomplete",
            })

        # Type-specific checks
        ext = file_path.suffix.lower()
        if ext == ".html" or check_type == "html":
            issues.extend(self._check_html_content(content))
        elif ext == ".css" or check_type == "css":
            issues.extend(self._check_css_content(content))
        elif ext in (".js", ".mjs") or check_type == "javascript":
            issues.extend(self._check_js_content(content))
        elif ext == ".py" or check_type == "python":
            issues.extend(self._check_python_content(content))
        elif ext == ".json" or check_type == "json":
            issues.extend(self._check_json_content(content))

        return {
            "ok": True,
            "stats": stats,
            "issues": issues,
            "issue_count": len(issues),
            "critical_count": sum(1 for i in issues if i.get("severity") == "critical"),
            "major_count": sum(1 for i in issues if i.get("severity") == "major"),
        }

    def check_html_structure(self, args: dict[str, Any]) -> dict[str, Any]:
        """Validate HTML file structure."""
        path = args.get("path", "")
        check_links = args.get("check_links", True)
        check_accessibility = args.get("check_accessibility", True)

        file_path = Path(path)
        if not file_path.exists():
            return {"ok": False, "error": f"File not found: {path}"}

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"ok": False, "error": f"Cannot read file: {e}"}

        issues = []
        project_root = file_path.parent

        # Doctype check
        if not content.strip().lower().startswith("<!doctype") and not content.strip().lower().startswith("<html"):
            issues.append({
                "severity": "major",
                "type": "missing_doctype",
                "description": "HTML file missing <!DOCTYPE html> declaration",
            })

        # Required elements
        if "<html" not in content.lower():
            issues.append({
                "severity": "critical",
                "type": "missing_html_tag",
                "description": "Missing <html> root element",
            })
        if "<head" not in content.lower():
            issues.append({
                "severity": "major",
                "type": "missing_head",
                "description": "Missing <head> element",
            })
        if "<body" not in content.lower():
            issues.append({
                "severity": "critical",
                "type": "missing_body",
                "description": "Missing <body> element",
            })

        # Charset and viewport
        if "charset" not in content.lower():
            issues.append({
                "severity": "minor",
                "type": "missing_charset",
                "description": "Missing charset declaration — may cause encoding issues",
            })
        if "viewport" not in content.lower():
            issues.append({
                "severity": "minor",
                "type": "missing_viewport",
                "description": "Missing viewport meta tag — page may not be responsive",
            })

        # Balanced tags check (basic)
        paired_tags = [
            "html", "head", "body", "div", "p", "span", "section", "article",
            "header", "footer", "nav", "main", "aside", "ul", "ol", "li",
            "table", "thead", "tbody", "tr", "td", "th", "form", "fieldset",
        ]
        for tag in paired_tags:
            open_count = len(re.findall(rf"<{tag}[\s>]", content, re.IGNORECASE))
            close_count = len(re.findall(rf"</{tag}>", content, re.IGNORECASE))
            if open_count != close_count and open_count > 0:
                issues.append({
                    "severity": "major",
                    "type": "unbalanced_tags",
                    "description": f"Unbalanced <{tag}> tags: {open_count} opened, {close_count} closed",
                })

        # Link integrity check
        if check_links:
            # CSS links
            css_links = re.findall(r'href=["\']([^"\']+\.css)["\']', content, re.IGNORECASE)
            for css_link in css_links:
                css_path = project_root / css_link
                if not css_path.exists():
                    issues.append({
                        "severity": "major",
                        "type": "broken_link",
                        "description": f"CSS file not found: {css_link}",
                    })

            # JS links
            js_links = re.findall(r'src=["\']([^"\']+\.js)["\']', content, re.IGNORECASE)
            for js_link in js_links:
                js_path = project_root / js_link
                if not js_path.exists():
                    issues.append({
                        "severity": "major",
                        "type": "broken_link",
                        "description": f"JavaScript file not found: {js_link}",
                    })

            # Image sources
            img_srcs = re.findall(r'src=["\']([^"\']+\.(png|jpg|jpeg|gif|svg|webp))["\']', content, re.IGNORECASE)
            for img_src, _ in img_srcs:
                img_path = project_root / img_src
                if not img_path.exists():
                    issues.append({
                        "severity": "minor",
                        "type": "broken_image",
                        "description": f"Image not found: {img_src}",
                    })

        # Accessibility check
        if check_accessibility:
            # Images without alt text
            img_tags = re.findall(r'<img\s[^>]*>', content, re.IGNORECASE)
            for img_tag in img_tags:
                if "alt=" not in img_tag.lower():
                    issues.append({
                        "severity": "major",
                        "type": "accessibility",
                        "description": f"Image missing alt text: {img_tag[:80]}",
                    })

            # Form inputs without labels
            input_tags = re.findall(r'<input\s[^>]*>', content, re.IGNORECASE)
            for input_tag in input_tags:
                input_type = re.search(r'type=["\']([^"\']+)["\']', input_tag, re.IGNORECASE)
                if input_type and input_type.group(1).lower() in ("submit", "reset", "button", "hidden"):
                    continue
                if "id=" in input_tag.lower():
                    input_id = re.search(r'id=["\']([^"\']+)["\']', input_tag, re.IGNORECASE)
                    if input_id:
                        label_pattern = rf'<label[^>]*for=["\']({re.escape(input_id.group(1))})["\']'
                        if not re.search(label_pattern, content, re.IGNORECASE):
                            issues.append({
                                "severity": "minor",
                                "type": "accessibility",
                                "description": f"Input without associated label: {input_tag[:80]}",
                            })

        # Inline style detection
        inline_styles = len(re.findall(r'style=["\']', content, re.IGNORECASE))
        if inline_styles > 5:
            issues.append({
                "severity": "minor",
                "type": "excessive_inline_styles",
                "description": f"Found {inline_styles} inline styles — consider using CSS classes instead",
            })

        return {
            "ok": True,
            "path": str(file_path),
            "issues": issues,
            "issue_count": len(issues),
            "critical_count": sum(1 for i in issues if i.get("severity") == "critical"),
            "major_count": sum(1 for i in issues if i.get("severity") == "major"),
        }

    def check_code_quality(self, args: dict[str, Any]) -> dict[str, Any]:
        """Analyze code quality in a file."""
        path = args.get("path", "")
        language = args.get("language", "auto")

        file_path = Path(path)
        if not file_path.exists():
            return {"ok": False, "error": f"File not found: {path}"}

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"ok": False, "error": f"Cannot read file: {e}"}

        # Auto-detect language
        if language == "auto":
            ext = file_path.suffix.lower()
            lang_map = {
                ".js": "javascript", ".mjs": "javascript",
                ".py": "python",
                ".html": "html",
                ".css": "css",
                ".ts": "javascript", ".tsx": "javascript",
            }
            language = lang_map.get(ext, "general")

        issues = []

        if language == "javascript":
            issues.extend(self._check_js_content(content))
        elif language == "python":
            issues.extend(self._check_python_content(content))
        elif language == "html":
            issues.extend(self._check_html_content(content))
        elif language == "css":
            issues.extend(self._check_css_content(content))
        else:
            # General checks
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if "console.log" in stripped and not stripped.startswith("//"):
                    issues.append({
                        "severity": "minor",
                        "type": "debug_code",
                        "line": i,
                        "description": f"Debug console.log on line {i}",
                    })

        return {
            "ok": True,
            "path": str(file_path),
            "language": language,
            "issues": issues,
            "issue_count": len(issues),
            "critical_count": sum(1 for i in issues if i.get("severity") == "critical"),
            "major_count": sum(1 for i in issues if i.get("severity") == "major"),
        }

    def check_cross_file_consistency(self, args: dict[str, Any]) -> dict[str, Any]:
        """Check consistency across multiple files."""
        paths = args.get("paths", [])
        project_root = args.get("project_root", "")

        if not paths:
            return {"ok": False, "error": "No paths provided"}

        root_path = Path(project_root) if project_root else Path(paths[0]).parent
        issues = []
        file_contents = {}

        # Read all files
        for path in paths:
            file_path = Path(path)
            if not file_path.exists():
                issues.append({
                    "severity": "critical",
                    "type": "missing_file",
                    "description": f"Referenced file does not exist: {path}",
                })
                continue
            try:
                file_contents[str(file_path)] = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                issues.append({
                    "severity": "major",
                    "type": "read_error",
                    "description": f"Cannot read file {path}: {e}",
                })

        if len(file_contents) < 2:
            return {
                "ok": True,
                "files_checked": len(file_contents),
                "issues": issues,
                "note": "Need at least 2 readable files for cross-file checks",
            }

        # Check shared references between files
        all_css_classes = {}
        all_ids = {}
        all_links = {}

        for file_path_str, content in file_contents.items():
            ext = Path(file_path_str).suffix.lower()

            if ext == ".html":
                # Collect CSS classes
                classes = re.findall(r'class=["\']([^"\']+)["\']', content)
                for cls_str in classes:
                    for cls in cls_str.split():
                        all_css_classes.setdefault(cls, []).append(file_path_str)

                # Collect IDs
                ids = re.findall(r'id=["\']([^"\']+)["\']', content)
                for element_id in ids:
                    all_ids.setdefault(element_id, []).append(file_path_str)

                # Collect links
                links = re.findall(r'href=["\']([^"\']+)["\']', content)
                for link in links:
                    if not link.startswith(("http", "#", "mailto:", "tel:")):
                        all_links.setdefault(link, []).append(file_path_str)

            elif ext == ".css":
                # Collect CSS selectors
                class_selectors = re.findall(r'\.([a-zA-Z_][\w-]*)', content)
                for cls in class_selectors:
                    all_css_classes.setdefault(cls, []).append(file_path_str)

            elif ext in (".js", ".mjs"):
                # Check for getElementById references
                get_elem_refs = re.findall(r'getElementById\(["\']([^"\']+)["\']\)', content)
                for ref_id in get_elem_refs:
                    if ref_id not in all_ids:
                        # Only flag if we have HTML files to check against
                        has_html = any(Path(p).suffix.lower() == ".html" for p in file_contents)
                        if has_html:
                            issues.append({
                                "severity": "critical",
                                "type": "missing_reference",
                                "description": f"JavaScript references element ID '{ref_id}' that may not exist in HTML files",
                                "file": file_path_str,
                            })

        # Check for duplicate IDs
        for element_id, files in all_ids.items():
            if len(files) > 1:
                issues.append({
                    "severity": "major",
                    "type": "duplicate_id",
                    "description": f"Duplicate ID '{element_id}' found in: {', '.join(Path(f).name for f in files)}",
                })

        # Check for broken internal links
        for link, files in all_links.items():
            link_path = root_path / link
            if not link_path.exists():
                issues.append({
                    "severity": "major",
                    "type": "broken_internal_link",
                    "description": f"Internal link '{link}' referenced in {', '.join(Path(f).name for f in files)} does not exist",
                })

        return {
            "ok": True,
            "files_checked": len(file_contents),
            "issues": issues,
            "issue_count": len(issues),
            "critical_count": sum(1 for i in issues if i.get("severity") == "critical"),
            "major_count": sum(1 for i in issues if i.get("severity") == "major"),
        }

    def check_requirements_coverage(self, args: dict[str, Any]) -> dict[str, Any]:
        """Check whether artifacts meet the original requirements."""
        requirements = args.get("requirements", "")
        artifact_paths = args.get("artifact_paths", [])

        if not requirements:
            return {"ok": False, "error": "No requirements provided"}
        if not artifact_paths:
            return {"ok": False, "error": "No artifact paths provided"}

        issues = []
        all_content = ""

        for path in artifact_paths:
            file_path = Path(path)
            if file_path.exists():
                try:
                    all_content += file_path.read_text(encoding="utf-8", errors="replace") + "\n"
                except Exception:
                    issues.append({
                        "severity": "major",
                        "type": "read_error",
                        "description": f"Cannot read file: {path}",
                    })

        if not all_content.strip():
            issues.append({
                "severity": "critical",
                "type": "empty_content",
                "description": "No readable content found in any of the artifact files",
            })
            return {
                "ok": False,
                "issues": issues,
                "coverage": 0.0,
            }

        content_lower = all_content.lower()
        requirements_lower = requirements.lower()

        # Extract key terms from requirements
        key_terms = re.findall(r'\b[a-z]{4,}\b', requirements_lower)
        # Filter out common stop words
        stop_words = {
            "that", "this", "with", "from", "have", "been", "will", "would",
            "should", "could", "about", "which", "their", "there", "where",
            "when", "what", "some", "than", "also", "just", "like", "very",
            "into", "over", "only", "then", "each", "does", "make", "made",
        }
        key_terms = [t for t in set(key_terms) if t not in stop_words and len(t) >= 4]

        # Check which key terms appear in the content
        missing_terms = []
        found_terms = []
        for term in sorted(key_terms):
            if term in content_lower:
                found_terms.append(term)
            else:
                missing_terms.append(term)

        coverage = len(found_terms) / len(key_terms) if key_terms else 0.0

        if missing_terms and coverage < 0.7:
            issues.append({
                "severity": "major",
                "type": "missing_requirements",
                "description": f"Key requirement terms not found in artifacts: {', '.join(missing_terms[:10])}",
            })

        # Check for specific requirement patterns
        requirement_patterns = {
            "navigation": r'(nav|menu|navigation|sidebar|header)',
            "responsive": r'(responsive|media|viewport|flex|grid|mobile|@media)',
            "form": r'(form|input|submit|validation|button)',
            "authentication": r'(login|auth|password|session|token)',
            "api": r'(api|fetch|endpoint|request|response)',
            "database": r'(database|db|sql|table|query|schema)',
            "testing": r'(test|spec|assert|expect|mock)',
            "error_handling": r'(try|catch|error|exception|throw|finally)',
            "validation": r'(valid|check|verify|ensure|confirm)',
        }

        for req_key, pattern in requirement_patterns.items():
            if req_key in requirements_lower and not re.search(pattern, content_lower):
                issues.append({
                    "severity": "major",
                    "type": "missing_feature",
                    "description": f"Requirement mentions '{req_key}' but no implementation found",
                })

        return {
            "ok": True,
            "requirements_terms_total": len(key_terms),
            "requirements_terms_found": len(found_terms),
            "requirements_terms_missing": missing_terms,
            "coverage": round(coverage, 2),
            "issues": issues,
            "issue_count": len(issues),
        }

    # ========== Internal Helpers ==========

    def _check_html_content(self, content: str) -> list[dict[str, Any]]:
        """Check HTML content for quality issues."""
        issues = []

        # Inline event handlers
        inline_events = re.findall(r'on\w+=["\']', content, re.IGNORECASE)
        if len(inline_events) > 3:
            issues.append({
                "severity": "minor",
                "type": "inline_events",
                "description": f"Found {len(inline_events)} inline event handlers — consider using addEventListener",
            })

        # localStorage on file:// protocol
        if "localstorage" in content.lower() and "file://" in content.lower():
            issues.append({
                "severity": "critical",
                "type": "localStorage_file_protocol",
                "description": "localStorage may not work on file:// protocol — wrap in try/catch",
            })

        # Empty elements
        empty_tags = re.findall(r'<(\w+)[^>]*>\s*</\1>', content)
        for tag in set(empty_tags):
            if tag.lower() not in ("script", "style", "textarea", "iframe"):
                issues.append({
                    "severity": "minor",
                    "type": "empty_element",
                    "description": f"Empty <{tag}> element found",
                })

        return issues

    def _check_css_content(self, content: str) -> list[dict[str, Any]]:
        """Check CSS content for quality issues."""
        issues = []

        # !important overuse
        important_count = len(re.findall(r'!important', content))
        if important_count > 5:
            issues.append({
                "severity": "minor",
                "type": "important_overuse",
                "description": f"Found {important_count} !important declarations — indicates specificity issues",
            })

        # Check for CSS rules
        if "{" not in content or "}" not in content:
            issues.append({
                "severity": "critical",
                "type": "invalid_css",
                "description": "CSS file contains no rule blocks",
            })

        # Z-index values
        high_z_indices = re.findall(r'z-index\s*:\s*(\d+)', content)
        for z in high_z_indices:
            if int(z) > 9999:
                issues.append({
                    "severity": "minor",
                    "type": "high_z_index",
                    "description": f"Very high z-index value: {z} — may cause stacking issues",
                })

        return issues

    def _check_js_content(self, content: str) -> list[dict[str, Any]]:
        """Check JavaScript content for quality issues."""
        issues = []
        lines = content.split("\n")

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # console.log left in production code
            if "console.log" in stripped and not stripped.startswith("//"):
                issues.append({
                    "severity": "minor",
                    "type": "debug_code",
                    "line": i,
                    "description": f"Debug console.log on line {i}",
                })

            # var instead of let/const
            if re.match(r'\s*var\s+', stripped):
                issues.append({
                    "severity": "minor",
                    "type": "var_usage",
                    "line": i,
                    "description": f"Using 'var' on line {i} — prefer 'let' or 'const'",
                })

            # innerHTML usage (potential XSS)
            if ".innerHTML" in stripped and not stripped.startswith("//"):
                issues.append({
                    "severity": "major",
                    "type": "security",
                    "line": i,
                    "description": f"innerHTML usage on line {i} — potential XSS vulnerability, use textContent or DOM manipulation",
                })

            # eval usage
            if re.search(r'\beval\s*\(', stripped):
                issues.append({
                    "severity": "critical",
                    "type": "security",
                    "line": i,
                    "description": f"eval() usage on line {i} — security risk, use safer alternatives",
                })

            # document.write
            if "document.write" in stripped:
                issues.append({
                    "severity": "major",
                    "type": "deprecated",
                    "line": i,
                    "description": f"document.write() on line {i} — deprecated, use DOM methods",
                })

        # getElementById without null check
        get_elem_lines = [
            (i + 1, line)
            for i, line in enumerate(lines)
            if "getElementById" in line and "null" not in line
            and "=== null" not in line and "!== null" not in line
            and "if (" not in line and "?" not in line
        ]
        if len(get_elem_lines) > 3:
            issues.append({
                "severity": "major",
                "type": "null_check",
                "description": f"Found {len(get_elem_lines)} getElementById calls without null checks — may cause runtime errors",
            })

        # localStorage on file://
        if "localstorage" in content.lower():
            if "try" not in content.lower() or "catch" not in content.lower():
                issues.append({
                    "severity": "critical",
                    "type": "localStorage_unsafe",
                    "description": "localStorage usage without try/catch — will fail on file:// protocol",
                })

        return issues

    def _check_python_content(self, content: str) -> list[dict[str, Any]]:
        """Check Python content for quality issues."""
        issues = []
        lines = content.split("\n")

        # Check for bare except
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if re.match(r'except\s*:', stripped):
                issues.append({
                    "severity": "major",
                    "type": "bare_except",
                    "line": i,
                    "description": f"Bare except clause on line {i} — catch specific exceptions",
                })

            # eval usage
            if re.search(r'\beval\s*\(', stripped):
                issues.append({
                    "severity": "critical",
                    "type": "security",
                    "line": i,
                    "description": f"eval() usage on line {i} — security risk",
                })

            # Hardcoded secrets
            if re.search(r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']', stripped, re.IGNORECASE):
                if not stripped.startswith("#") and not stripped.startswith('"""'):
                    issues.append({
                        "severity": "critical",
                        "type": "security",
                        "line": i,
                        "description": f"Possible hardcoded secret on line {i}",
                    })

        return issues

    def _check_json_content(self, content: str) -> list[dict[str, Any]]:
        """Check JSON content for quality issues."""
        import json as json_module
        issues = []

        try:
            data = json_module.loads(content)
        except json_module.JSONDecodeError as e:
            issues.append({
                "severity": "critical",
                "type": "invalid_json",
                "description": f"Invalid JSON: {e}",
            })
            return issues

        # Check for empty objects/arrays
        if isinstance(data, dict) and len(data) == 0:
            issues.append({
                "severity": "major",
                "type": "empty_content",
                "description": "JSON object is empty",
            })

        return issues