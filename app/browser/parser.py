"""
DOM Parser using BeautifulSoup4

Provides fast DOM analysis without Selenium overhead.
Useful for checking generation status, finding images/videos, etc.
"""

import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag
from selenium.webdriver.remote.webdriver import WebDriver
from loguru import logger


@dataclass
class ImageInfo:
    """Information about a generated image"""
    src: str
    alt: Optional[str] = None
    data_id: Optional[str] = None
    index: int = 0
    is_candidate: bool = False


@dataclass
class VideoInfo:
    """Information about a generated video"""
    src: str
    poster: Optional[str] = None
    data_id: Optional[str] = None
    index: int = 0


@dataclass
class GenerationStatus:
    """Status of ongoing generation"""
    is_pending: bool = False
    is_generating: bool = False
    is_complete: bool = False
    progress_percent: Optional[float] = None
    queue_position: Optional[int] = None
    error_message: Optional[str] = None


class DOMParser:
    """
    BeautifulSoup4 parser for analyzing page DOM.

    Faster than Selenium for complex DOM queries.
    Use for status checks, image/video discovery, etc.

    Usage:
        parser = DOMParser(driver)

        # Check generation status
        status = parser.get_generation_status()
        if status.is_complete:
            images = parser.find_generated_images()

        # Find specific elements
        buttons = parser.find_all("button", class_="generate-btn")
    """

    def __init__(self, driver: WebDriver):
        self.driver = driver
        self._soup: Optional[BeautifulSoup] = None
        self._cached_html: Optional[str] = None

    def refresh(self) -> "DOMParser":
        """
        Refresh DOM cache from current page.

        Call this after any page changes before parsing.
        Returns self for chaining.
        """
        self._cached_html = self.driver.page_source
        self._soup = BeautifulSoup(self._cached_html, 'html.parser')
        return self

    @property
    def soup(self) -> BeautifulSoup:
        """Get BeautifulSoup object, refreshing if needed"""
        if self._soup is None:
            self.refresh()
        return self._soup

    # ========================================================================
    # IMAGE FINDING
    # ========================================================================

    def find_generated_images(
        self,
        container_selector: Optional[str] = None
    ) -> List[ImageInfo]:
        """
        Find all generated images on the page.

        Args:
            container_selector: Optional CSS selector to limit search

        Returns:
            List of ImageInfo objects
        """
        self.refresh()

        # Search in container or whole page
        if container_selector:
            container = self.soup.select_one(container_selector)
            if not container:
                return []
            search_area = container
        else:
            search_area = self.soup

        images = []
        index = 0

        # Look for images with common generated image patterns
        for img in search_area.find_all('img'):
            src = img.get('src', '')

            # Skip icons, placeholders, avatars
            if self._is_ui_image(src, img):
                continue

            # Check for generated image indicators
            if self._is_generated_image(src, img):
                images.append(ImageInfo(
                    src=src,
                    alt=img.get('alt'),
                    data_id=img.get('data-id') or img.get('data-asset-id'),
                    index=index,
                    is_candidate='candidate' in src.lower() or 'preview' in str(img.get('class', []))
                ))
                index += 1

        logger.debug(f"Found {len(images)} generated images")
        return images

    def _is_ui_image(self, src: str, img: Tag) -> bool:
        """Check if image is a UI element (icon, avatar, etc.)"""
        # Small images are usually icons
        width = img.get('width')
        height = img.get('height')
        if width and height:
            try:
                if int(width) < 50 or int(height) < 50:
                    return True
            except ValueError:
                pass

        # Check classes for UI indicators
        classes = ' '.join(img.get('class', []))
        ui_classes = ['icon', 'avatar', 'logo', 'emoji', 'spinner', 'loading']
        if any(c in classes.lower() for c in ui_classes):
            return True

        # Check src for UI patterns
        ui_patterns = ['/icons/', '/avatars/', '/ui/', 'sprite', 'placeholder', 'data:image/svg']
        if any(p in src.lower() for p in ui_patterns):
            return True

        return False

    def _is_generated_image(self, src: str, img: Tag) -> bool:
        """Check if image appears to be a generated/uploaded image"""
        # CDN patterns for generated images
        cdn_patterns = [
            'cdn.', 'storage.', 'blob.', 'cloudfront',
            'higgsfield', 'generated', 'output', 'result'
        ]
        if any(p in src.lower() for p in cdn_patterns):
            return True

        # Check for data attributes indicating generated content
        data_attrs = ['data-asset', 'data-generated', 'data-output', 'data-result']
        if any(img.get(attr) for attr in data_attrs):
            return True

        # Check parent container
        parent = img.parent
        if parent:
            parent_class = ' '.join(parent.get('class', []))
            if any(c in parent_class.lower() for c in ['gallery', 'result', 'output', 'generated', 'preview']):
                return True

        # Large images without UI indicators are likely generated
        if src.startswith('http') and not self._is_ui_image(src, img):
            return True

        return False

    def count_new_images(self, previous_count: int = 0) -> int:
        """
        Count newly generated images since last check.

        Args:
            previous_count: Number of images from previous check

        Returns:
            Number of new images
        """
        current_images = self.find_generated_images()
        return max(0, len(current_images) - previous_count)

    # ========================================================================
    # VIDEO FINDING
    # ========================================================================

    def find_generated_videos(
        self,
        container_selector: Optional[str] = None
    ) -> List[VideoInfo]:
        """
        Find all generated videos on the page.

        Args:
            container_selector: Optional CSS selector to limit search

        Returns:
            List of VideoInfo objects
        """
        self.refresh()

        if container_selector:
            container = self.soup.select_one(container_selector)
            if not container:
                return []
            search_area = container
        else:
            search_area = self.soup

        videos = []
        index = 0

        # Find video elements
        for video in search_area.find_all('video'):
            # Get source from video src or nested source element
            src = video.get('src')
            if not src:
                source = video.find('source')
                if source:
                    src = source.get('src')

            if src and not self._is_ui_video(src, video):
                videos.append(VideoInfo(
                    src=src,
                    poster=video.get('poster'),
                    data_id=video.get('data-id') or video.get('data-asset-id'),
                    index=index
                ))
                index += 1

        logger.debug(f"Found {len(videos)} generated videos")
        return videos

    def _is_ui_video(self, src: str, video: Tag) -> bool:
        """Check if video is a UI element (loading animation, etc.)"""
        ui_patterns = ['loading', 'spinner', 'animation', 'ui', 'placeholder']
        return any(p in src.lower() for p in ui_patterns)

    # ========================================================================
    # GENERATION STATUS
    # ========================================================================

    def get_generation_status(self) -> GenerationStatus:
        """
        Check current generation status on the page.

        Looks for loading indicators, progress bars, queue info, etc.

        Returns:
            GenerationStatus object
        """
        self.refresh()

        status = GenerationStatus()

        # Check for loading/pending indicators
        loading_indicators = [
            '.loading', '.spinner', '[data-loading="true"]',
            '.generating', '.pending', '.in-progress',
            '[class*="loading"]', '[class*="spinner"]'
        ]

        for selector in loading_indicators:
            if self.soup.select_one(selector):
                status.is_generating = True
                break

        # Check for queue position
        queue_element = self.soup.select_one('[class*="queue"], [class*="position"]')
        if queue_element:
            text = queue_element.get_text()
            numbers = re.findall(r'\d+', text)
            if numbers:
                status.queue_position = int(numbers[0])
                status.is_pending = True

        # Check for progress
        progress_element = self.soup.select_one('progress, [role="progressbar"], [class*="progress"]')
        if progress_element:
            value = progress_element.get('value') or progress_element.get('aria-valuenow')
            if value:
                try:
                    status.progress_percent = float(value)
                except ValueError:
                    pass

        # Check for completion indicators
        complete_indicators = [
            '.complete', '.done', '.finished', '.success',
            '[data-status="complete"]', '[data-status="done"]'
        ]

        for selector in complete_indicators:
            if self.soup.select_one(selector):
                status.is_complete = True
                status.is_generating = False
                break

        # Check for error messages
        error_element = self.soup.select_one('.error, [class*="error"], [role="alert"]')
        if error_element:
            status.error_message = error_element.get_text(strip=True)

        return status

    def is_generation_pending(self) -> bool:
        """Quick check if generation is still pending"""
        status = self.get_generation_status()
        return status.is_generating or status.is_pending

    # ========================================================================
    # GENERAL SELECTORS
    # ========================================================================

    def find(self, selector: str) -> Optional[Tag]:
        """Find first element matching CSS selector"""
        self.refresh()
        return self.soup.select_one(selector)

    def find_all(self, selector: str) -> List[Tag]:
        """Find all elements matching CSS selector"""
        self.refresh()
        return self.soup.select(selector)

    def find_by_text(
        self,
        text: str,
        tag: str = None,
        exact: bool = False
    ) -> List[Tag]:
        """
        Find elements containing specific text.

        Args:
            text: Text to search for
            tag: Optional tag name to filter (e.g., "button", "span")
            exact: Match exact text (True) or contains (False)
        """
        self.refresh()

        results = []
        elements = self.soup.find_all(tag) if tag else self.soup.find_all()

        for el in elements:
            el_text = el.get_text(strip=True)
            if exact:
                if el_text == text:
                    results.append(el)
            else:
                if text.lower() in el_text.lower():
                    results.append(el)

        return results

    def get_text(self, selector: str) -> Optional[str]:
        """Get text content of element"""
        element = self.find(selector)
        if element:
            return element.get_text(strip=True)
        return None

    def get_attribute(self, selector: str, attribute: str) -> Optional[str]:
        """Get attribute value of element"""
        element = self.find(selector)
        if element:
            return element.get(attribute)
        return None

    def element_exists(self, selector: str) -> bool:
        """Check if element exists"""
        return self.find(selector) is not None

    def count_elements(self, selector: str) -> int:
        """Count elements matching selector"""
        return len(self.find_all(selector))

    # ========================================================================
    # UTILITIES
    # ========================================================================

    def get_all_links(self) -> List[Dict[str, str]]:
        """Get all links on the page"""
        self.refresh()
        links = []
        for a in self.soup.find_all('a', href=True):
            links.append({
                'href': a['href'],
                'text': a.get_text(strip=True),
            })
        return links

    def get_all_image_urls(self) -> List[str]:
        """Get all image URLs on the page"""
        self.refresh()
        urls = []
        for img in self.soup.find_all('img', src=True):
            urls.append(img['src'])
        return urls

    def get_page_title(self) -> Optional[str]:
        """Get page title"""
        self.refresh()
        title = self.soup.find('title')
        if title:
            return title.get_text(strip=True)
        return None

    def extract_json_from_script(self, pattern: str = None) -> Optional[Dict[str, Any]]:
        """
        Extract JSON data from script tags.

        Args:
            pattern: Optional regex pattern to find specific script

        Returns:
            Parsed JSON data if found
        """
        import json

        self.refresh()

        for script in self.soup.find_all('script'):
            content = script.string
            if not content:
                continue

            if pattern and not re.search(pattern, content):
                continue

            # Try to find JSON object
            json_match = re.search(r'\{[^{}]*\}', content)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    continue

        return None
