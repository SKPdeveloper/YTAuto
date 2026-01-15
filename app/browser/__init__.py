"""
Browser Automation Module

Provides unified browser interaction layer with:
- Human-like delays and actions
- BeautifulSoup4 DOM parsing
- Centralized selectors

Usage:
    from app.browser import BrowserActions, DOMParser

    actions = BrowserActions(driver)
    await actions.click_element("button.submit")
    await actions.type_text("input.prompt", "Hello world")

    parser = DOMParser(driver)
    images = parser.find_generated_images()
"""

from app.browser.actions import BrowserActions
from app.browser.parser import DOMParser

__all__ = [
    "BrowserActions",
    "DOMParser",
]
