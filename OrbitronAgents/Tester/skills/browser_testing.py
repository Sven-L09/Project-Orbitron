"""Browser Testing Skill for the Tester Agent.

Uses Playwright to test HTML pages in a real browser, checking
visual rendering, interactivity, responsiveness, and more.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("BrowserTestingSkill")

# Playwright availability flag
_PLAYWRIGHT_AVAILABLE = False
_playwright_module = None

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
    logger.info("[BrowserTestingSkill] Playwright is available")
except ImportError:
    logger.warning("[BrowserTestingSkill] Playwright not installed. Browser testing will be limited.")


class BrowserTestingSkill:
    """Skill for browser-based HTML testing using Playwright.

    This skill provides tools to open HTML pages in a real browser,
    take screenshots, check for visual elements, test interactions,
    and validate responsive design.
    """

    name = "browser_testing"
    description = "Tools for testing HTML pages in a real browser using Playwright"

    def get_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions for the browser testing skill."""
        return [
            {
                "name": "browser_open_page",
                "description": "Open an HTML page in the browser for testing. Returns page title, URL, and basic metrics.",
                "schema": {
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL or file path to open. For local files, use file:// protocol or absolute path.",
                        },
                        "viewport_width": {
                            "type": "integer",
                            "description": "Browser viewport width in pixels (default: 1280)",
                        },
                        "viewport_height": {
                            "type": "integer",
                            "description": "Browser viewport height in pixels (default: 720)",
                        },
                    },
                },
            },
            {
                "name": "browser_screenshot",
                "description": "Take a screenshot of the current page or a specific element. Useful for visual verification.",
                "schema": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector to screenshot a specific element (optional, screenshots full page if omitted)",
                        },
                        "full_page": {
                            "type": "boolean",
                            "description": "Whether to capture the full scrollable page (default: true)",
                        },
                        "save_path": {
                            "type": "string",
                            "description": "Path to save the screenshot. If omitted, returns base64 data.",
                        },
                    },
                },
            },
            {
                "name": "browser_check_elements",
                "description": "Check for the existence and visibility of specific elements on the page. Returns detailed info about each element.",
                "schema": {
                    "type": "object",
                    "required": ["selectors"],
                    "properties": {
                        "selectors": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of CSS selectors to check for existence and visibility",
                        },
                    },
                },
            },
            {
                "name": "browser_check_console",
                "description": "Check the browser console for errors, warnings, and log messages. Returns all console output.",
                "schema": {
                    "type": "object",
                    "properties": {
                        "include_logs": {
                            "type": "boolean",
                            "description": "Whether to include console.log messages (default: false, only errors and warnings)",
                        },
                    },
                },
            },
            {
                "name": "browser_test_responsive",
                "description": "Test how the page renders at different viewport sizes. Checks common breakpoints.",
                "schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL or file path to test (uses current page if omitted)",
                        },
                        "breakpoints": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "Name of the breakpoint (e.g., 'mobile')"},
                                    "width": {"type": "integer", "description": "Viewport width"},
                                    "height": {"type": "integer", "description": "Viewport height"},
                                },
                            },
                            "description": "Custom breakpoints to test (default: mobile 375x667, tablet 768x1024, desktop 1280x720)",
                        },
                    },
                },
            },
            {
                "name": "browser_test_interaction",
                "description": "Test interactive elements: click buttons, fill forms, check navigation. Returns results of each interaction.",
                "schema": {
                    "type": "object",
                    "required": ["actions"],
                    "properties": {
                        "actions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["click", "fill", "select", "check", "hover", "wait"],
                                        "description": "Type of interaction",
                                    },
                                    "selector": {
                                        "type": "string",
                                        "description": "CSS selector for the element",
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": "Value for fill/select actions",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Human description of what this action does",
                                    },
                                },
                            },
                            "description": "List of interactions to perform",
                        },
                    },
                },
            },
            {
                "name": "browser_get_page_info",
                "description": "Get detailed information about the current page: title, meta tags, links, images, forms, scripts.",
                "schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "browser_close",
                "description": "Close the browser and release resources. Call this when done with browser testing.",
                "schema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    def get_handlers(self) -> dict[str, Any]:
        """Return handler functions for each tool."""
        return {
            "browser_open_page": self.browser_open_page,
            "browser_screenshot": self.browser_screenshot,
            "browser_check_elements": self.browser_check_elements,
            "browser_check_console": self.browser_check_console,
            "browser_test_responsive": self.browser_test_responsive,
            "browser_test_interaction": self.browser_test_interaction,
            "browser_get_page_info": self.browser_get_page_info,
            "browser_close": self.browser_close,
        }

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None
        self._console_messages = []

    def _ensure_playwright(self) -> bool:
        """Ensure Playwright is available and browsers are installed."""
        global _PLAYWRIGHT_AVAILABLE
        if not _PLAYWRIGHT_AVAILABLE:
            return False
        return True

    def _get_page(self):
        """Get or create the Playwright page."""
        if self._page and not self._page.is_closed():
            return self._page
        return None

    def _start_browser(self, viewport_width: int = 1280, viewport_height: int = 720):
        """Start the browser if not already running."""
        if not self._ensure_playwright():
            return False

        try:
            if self._playwright is None:
                self._playwright = sync_playwright().start()

            if self._browser is None or not self._browser.is_connected():
                self._browser = self._playwright.chromium.launch(headless=True)
                self._page = self._browser.new_page(
                    viewport={"width": viewport_width, "height": viewport_height},
                )
                # Capture console messages
                self._console_messages = []
                self._page.on("console", lambda msg: self._console_messages.append({
                    "type": msg.type,
                    "text": msg.text,
                }))

            return True
        except Exception as e:
            logger.error("[BrowserTestingSkill] Failed to start browser: %s", e)
            return False

    # ========== Tool Implementations ==========

    def browser_open_page(self, args: dict[str, Any]) -> dict[str, Any]:
        """Open an HTML page in the browser."""
        url = args.get("url", "")
        viewport_width = args.get("viewport_width", 1280)
        viewport_height = args.get("viewport_height", 720)

        if not url:
            return {"ok": False, "error": "No URL provided"}

        # Handle local file paths
        if not url.startswith(("http://", "https://", "file://")):
            file_path = Path(url)
            if file_path.exists():
                url = f"file:///{file_path.resolve().as_posix()}"
            else:
                return {"ok": False, "error": f"File not found: {url}"}

        if not self._start_browser(viewport_width, viewport_height):
            return {
                "ok": False,
                "error": "Playwright not available. Install with: pip install playwright && playwright install chromium",
            }

        try:
            self._console_messages = []
            self._page.goto(url, wait_until="networkidle", timeout=30000)

            title = self._page.title()
            current_url = self._page.url

            # Basic page metrics
            metrics = self._page.evaluate("""() => {
                return {
                    documentHeight: document.documentElement.scrollHeight,
                    viewportHeight: window.innerHeight,
                    elementCount: document.querySelectorAll('*').length,
                    linkCount: document.querySelectorAll('a').length,
                    imageCount: document.querySelectorAll('img').length,
                    formCount: document.querySelectorAll('form').length,
                    scriptCount: document.querySelectorAll('script').length,
                };
            }""")

            return {
                "ok": True,
                "title": title,
                "url": current_url,
                "metrics": metrics,
                "console_errors": len([m for m in self._console_messages if m["type"] == "error"]),
            }

        except Exception as e:
            return {"ok": False, "error": f"Failed to open page: {e}"}

    def browser_screenshot(self, args: dict[str, Any]) -> dict[str, Any]:
        """Take a screenshot of the page or a specific element."""
        page = self._get_page()
        if not page:
            return {"ok": False, "error": "No page open. Call browser_open_page first."}

        selector = args.get("selector")
        full_page = args.get("full_page", True)
        save_path = args.get("save_path")

        try:
            if selector:
                element = page.query_selector(selector)
                if not element:
                    return {"ok": False, "error": f"Element not found: {selector}"}

                if save_path:
                    element.screenshot(path=save_path)
                    return {"ok": True, "screenshot_path": save_path, "element": selector}
                else:
                    screenshot_bytes = element.screenshot()
                    import base64
                    return {
                        "ok": True,
                        "element": selector,
                        "screenshot_size": len(screenshot_bytes),
                        "screenshot_base64": base64.b64encode(screenshot_bytes).decode("utf-8")[:500] + "...",
                        "note": "Full base64 available in production; truncated for display",
                    }
            else:
                if save_path:
                    page.screenshot(path=save_path, full_page=full_page)
                    return {"ok": True, "screenshot_path": save_path, "full_page": full_page}
                else:
                    screenshot_bytes = page.screenshot(full_page=full_page)
                    import base64
                    return {
                        "ok": True,
                        "full_page": full_page,
                        "screenshot_size": len(screenshot_bytes),
                        "screenshot_base64": base64.b64encode(screenshot_bytes).decode("utf-8")[:500] + "...",
                        "note": "Full base64 available in production; truncated for display",
                    }

        except Exception as e:
            return {"ok": False, "error": f"Screenshot failed: {e}"}

    def browser_check_elements(self, args: dict[str, Any]) -> dict[str, Any]:
        """Check for the existence and visibility of elements."""
        page = self._get_page()
        if not page:
            return {"ok": False, "error": "No page open. Call browser_open_page first."}

        selectors = args.get("selectors", [])
        if not selectors:
            return {"ok": False, "error": "No selectors provided"}

        results = []
        for selector in selectors:
            try:
                elements = page.query_selector_all(selector)
                if not elements:
                    results.append({
                        "selector": selector,
                        "found": False,
                        "count": 0,
                        "visible": False,
                    })
                    continue

                # Check visibility of first element
                first_visible = False
                for elem in elements[:5]:  # Check up to 5 elements
                    try:
                        if elem.is_visible():
                            first_visible = True
                            break
                    except Exception:
                        pass

                # Get text content of first element
                text_content = ""
                try:
                    text_content = elements[0].inner_text()[:200]
                except Exception:
                    pass

                results.append({
                    "selector": selector,
                    "found": True,
                    "count": len(elements),
                    "visible": first_visible,
                    "text_preview": text_content,
                })

            except Exception as e:
                results.append({
                    "selector": selector,
                    "found": False,
                    "count": 0,
                    "visible": False,
                    "error": str(e),
                })

        return {
            "ok": True,
            "results": results,
            "all_found": all(r.get("found", False) for r in results),
            "all_visible": all(r.get("visible", False) for r in results if r.get("found", False)),
        }

    def browser_check_console(self, args: dict[str, Any]) -> dict[str, Any]:
        """Check the browser console for errors and warnings."""
        page = self._get_page()
        if not page:
            return {"ok": False, "error": "No page open. Call browser_open_page first."}

        include_logs = args.get("include_logs", False)

        # Filter console messages
        messages = self._console_messages.copy()
        if not include_logs:
            messages = [m for m in messages if m["type"] in ("error", "warning")]

        errors = [m for m in messages if m["type"] == "error"]
        warnings = [m for m in messages if m["type"] == "warning"]

        return {
            "ok": True,
            "total_messages": len(self._console_messages),
            "errors": errors,
            "error_count": len(errors),
            "warnings": warnings,
            "warning_count": len(warnings),
            "has_errors": len(errors) > 0,
            "has_warnings": len(warnings) > 0,
            "all_messages": messages if include_logs else None,
        }

    def browser_test_responsive(self, args: dict[str, Any]) -> dict[str, Any]:
        """Test the page at different viewport sizes."""
        url = args.get("url", "")
        custom_breakpoints = args.get("breakpoints")

        default_breakpoints = [
            {"name": "mobile", "width": 375, "height": 667},
            {"name": "tablet", "width": 768, "height": 1024},
            {"name": "desktop", "width": 1280, "height": 720},
            {"name": "large_desktop", "width": 1920, "height": 1080},
        ]
        breakpoints = custom_breakpoints or default_breakpoints

        results = []

        try:
            if not self._start_browser():
                return {
                    "ok": False,
                    "error": "Playwright not available",
                }

            for bp in breakpoints:
                try:
                    # Resize viewport
                    self._page.set_viewport_size({"width": bp["width"], "height": bp["height"]})

                    # Navigate if URL provided
                    if url:
                        nav_url = url
                        if not nav_url.startswith(("http://", "https://", "file://")):
                            file_path = Path(nav_url)
                            if file_path.exists():
                                nav_url = f"file:///{file_path.resolve().as_posix()}"
                        self._page.goto(nav_url, wait_until="networkidle", timeout=15000)

                    # Check for horizontal overflow
                    has_horizontal_scroll = self._page.evaluate("""() => {
                        return document.documentElement.scrollWidth > document.documentElement.clientWidth;
                    }""")

                    # Check for visible content
                    visible_text = self._page.evaluate("""() => {
                        return document.body ? document.body.innerText.substring(0, 500) : '';
                    }""")

                    # Check for overlapping elements at this size
                    overlapping = self._page.evaluate("""() => {
                        const elements = document.querySelectorAll('*');
                        const overlapping = [];
                        for (let i = 0; i < Math.min(elements.length, 50); i++) {
                            const rect = elements[i].getBoundingClientRect();
                            if (rect.width === 0 || rect.height === 0) continue;
                            const style = window.getComputedStyle(elements[i]);
                            if (style.overflow === 'hidden') continue;
                            if (rect.width > window.innerWidth + 10) {
                                overlapping.push({
                                    tag: elements[i].tagName,
                                    width: rect.width,
                                    overflow: true,
                                });
                            }
                        }
                        return overlapping.slice(0, 5);
                    }""")

                    results.append({
                        "breakpoint": bp["name"],
                        "viewport": f"{bp['width']}x{bp['height']}",
                        "horizontal_scroll": has_horizontal_scroll,
                        "has_content": len(visible_text.strip()) > 0,
                        "content_preview": visible_text[:200],
                        "overflow_elements": overlapping,
                        "issues": [],
                    })

                    # Add issues
                    if has_horizontal_scroll:
                        results[-1]["issues"].append({
                            "severity": "major",
                            "type": "horizontal_scroll",
                            "description": f"Page has horizontal scrollbar at {bp['name']} ({bp['width']}px)",
                        })

                    for elem in overlapping:
                        results[-1]["issues"].append({
                            "severity": "major",
                            "type": "element_overflow",
                            "description": f"Element <{elem['tag']}> overflows viewport at {bp['name']} (width: {elem['width']}px)",
                        })

                except Exception as e:
                    results.append({
                        "breakpoint": bp["name"],
                        "viewport": f"{bp['width']}x{bp['height']}",
                        "error": str(e),
                        "issues": [{"severity": "critical", "type": "page_error", "description": str(e)}],
                    })

            total_issues = sum(len(r.get("issues", [])) for r in results)

            return {
                "ok": True,
                "breakpoints_tested": len(results),
                "results": results,
                "total_issues": total_issues,
                "all_passed": total_issues == 0,
            }

        except Exception as e:
            return {"ok": False, "error": f"Responsive test failed: {e}"}

    def browser_test_interaction(self, args: dict[str, Any]) -> dict[str, Any]:
        """Test interactive elements on the page."""
        page = self._get_page()
        if not page:
            return {"ok": False, "error": "No page open. Call browser_open_page first."}

        actions = args.get("actions", [])
        if not actions:
            return {"ok": False, "error": "No actions provided"}

        results = []

        for action in actions:
            action_type = action.get("type", "")
            selector = action.get("selector", "")
            value = action.get("value", "")
            description = action.get("description", action_type)

            try:
                if action_type == "click":
                    element = page.wait_for_selector(selector, timeout=5000)
                    if element:
                        element.click()
                        results.append({
                            "action": action_type,
                            "selector": selector,
                            "description": description,
                            "success": True,
                        })
                    else:
                        results.append({
                            "action": action_type,
                            "selector": selector,
                            "description": description,
                            "success": False,
                            "error": "Element not found",
                        })

                elif action_type == "fill":
                    element = page.wait_for_selector(selector, timeout=5000)
                    if element:
                        element.fill(value)
                        results.append({
                            "action": action_type,
                            "selector": selector,
                            "description": description,
                            "success": True,
                            "value": value,
                        })
                    else:
                        results.append({
                            "action": action_type,
                            "selector": selector,
                            "description": description,
                            "success": False,
                            "error": "Element not found",
                        })

                elif action_type == "select":
                    element = page.wait_for_selector(selector, timeout=5000)
                    if element:
                        element.select_option(value=value)
                        results.append({
                            "action": action_type,
                            "selector": selector,
                            "description": description,
                            "success": True,
                        })
                    else:
                        results.append({
                            "action": action_type,
                            "selector": selector,
                            "description": description,
                            "success": False,
                            "error": "Element not found",
                        })

                elif action_type == "check":
                    element = page.wait_for_selector(selector, timeout=5000)
                    if element:
                        element.check()
                        results.append({
                            "action": action_type,
                            "selector": selector,
                            "description": description,
                            "success": True,
                        })
                    else:
                        results.append({
                            "action": action_type,
                            "selector": selector,
                            "description": description,
                            "success": False,
                            "error": "Element not found",
                        })

                elif action_type == "hover":
                    element = page.wait_for_selector(selector, timeout=5000)
                    if element:
                        element.hover()
                        results.append({
                            "action": action_type,
                            "selector": selector,
                            "description": description,
                            "success": True,
                        })
                    else:
                        results.append({
                            "action": action_type,
                            "selector": selector,
                            "description": description,
                            "success": False,
                            "error": "Element not found",
                        })

                elif action_type == "wait":
                    page.wait_for_timeout(int(value) if value else 1000)
                    results.append({
                        "action": action_type,
                        "description": description,
                        "success": True,
                        "duration_ms": int(value) if value else 1000,
                    })

                else:
                    results.append({
                        "action": action_type,
                        "description": description,
                        "success": False,
                        "error": f"Unknown action type: {action_type}",
                    })

            except Exception as e:
                results.append({
                    "action": action_type,
                    "selector": selector,
                    "description": description,
                    "success": False,
                    "error": str(e),
                })

        success_count = sum(1 for r in results if r.get("success", False))

        return {
            "ok": True,
            "actions_tested": len(results),
            "actions_passed": success_count,
            "actions_failed": len(results) - success_count,
            "all_passed": success_count == len(results),
            "results": results,
        }

    def browser_get_page_info(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get detailed information about the current page."""
        page = self._get_page()
        if not page:
            return {"ok": False, "error": "No page open. Call browser_open_page first."}

        try:
            info = page.evaluate("""() => {
                const meta = {};
                document.querySelectorAll('meta').forEach(m => {
                    const name = m.getAttribute('name') || m.getAttribute('property') || m.getAttribute('http-equiv');
                    if (name) meta[name] = m.getAttribute('content');
                });

                const links = [];
                document.querySelectorAll('a').forEach(a => {
                    links.push({
                        href: a.href,
                        text: a.innerText.substring(0, 50),
                        target: a.target,
                    });
                });

                const images = [];
                document.querySelectorAll('img').forEach(img => {
                    images.push({
                        src: img.src,
                        alt: img.alt,
                        width: img.naturalWidth,
                        height: img.naturalHeight,
                        displayed: img.offsetWidth > 0,
                    });
                });

                const forms = [];
                document.querySelectorAll('form').forEach(form => {
                    const inputs = [];
                    form.querySelectorAll('input, select, textarea').forEach(input => {
                        inputs.push({
                            type: input.type || input.tagName.toLowerCase(),
                            name: input.name,
                            id: input.id,
                            required: input.required,
                        });
                    });
                    forms.push({
                        action: form.action,
                        method: form.method,
                        inputCount: inputs.length,
                        inputs: inputs.slice(0, 10),
                    });
                });

                const scripts = [];
                document.querySelectorAll('script').forEach(s => {
                    if (s.src) scripts.push(s.src);
                });

                return {
                    title: document.title,
                    url: window.location.href,
                    meta: meta,
                    links: links.slice(0, 20),
                    linkCount: links.length,
                    images: images.slice(0, 20),
                    imageCount: images.length,
                    forms: forms.slice(0, 10),
                    formCount: forms.length,
                    scripts: scripts.slice(0, 20),
                    scriptCount: scripts.length,
                    bodyTextLength: document.body ? document.body.innerText.length : 0,
                    headingCount: document.querySelectorAll('h1,h2,h3,h4,h5,h6').length,
                };
            }""")

            return {
                "ok": True,
                "info": info,
            }

        except Exception as e:
            return {"ok": False, "error": f"Failed to get page info: {e}"}

    def browser_close(self, args: dict[str, Any] = None) -> dict[str, Any]:
        """Close the browser and release resources."""
        try:
            if self._page and not self._page.is_closed():
                self._page.close()
            if self._browser and self._browser.is_connected():
                self._browser.close()
            if self._playwright:
                self._playwright.stop()

            self._page = None
            self._browser = None
            self._playwright = None
            self._console_messages = []

            return {"ok": True, "message": "Browser closed successfully"}

        except Exception as e:
            return {"ok": False, "error": f"Error closing browser: {e}"}