"""
Browser Automation Tool for Hive Agents.

Provides browser-based web interaction capabilities for
scraping dynamic content, filling forms, taking screenshots,
and interacting with JavaScript-rendered pages.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastmcp import FastMCP
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

# Browser-like User-Agent for actual page requests
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def register_tools(mcp: FastMCP) -> None:
    """Register browser automation tools with the MCP server."""

    @mcp.tool()
    async def browser_get_page_content(
        url: str,
        wait_for: str | None = None,
        timeout: int = 30000,
    ) -> dict:
        """
        Navigate to a URL using a headless browser and return the fully rendered HTML content.

        Use this when you need to extract HTML from JavaScript-rendered pages,
        SPAs, or dynamic content that requires browser execution.

        Args:
            url: The URL to navigate to
            wait_for: Optional CSS selector to wait for before extracting content
            timeout: Maximum time in milliseconds to wait for page load (default: 30000)

        Returns:
            Dict with keys: html, title, url (final URL after redirects) or error dict
        """
        try:
            # Validate URL
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            # Validate timeout
            timeout = max(5000, min(timeout, 300000))  # 5s to 5min

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                try:
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent=BROWSER_USER_AGENT,
                        locale="en-US",
                    )
                    page = await context.new_page()

                    await page.goto(url, timeout=timeout, wait_until="networkidle")

                    # Wait for specific selector if provided
                    if wait_for:
                        await page.wait_for_selector(wait_for, timeout=timeout)

                    content = await page.content()
                    title = await page.title()
                    final_url = page.url

                    return {
                        "html": content,
                        "title": title,
                        "url": final_url,
                    }
                finally:
                    await browser.close()

        except PlaywrightTimeout:
            return {"error": f"Request timed out after {timeout}ms"}
        except PlaywrightError as e:
            return {"error": f"Browser error: {e!s}"}
        except Exception as e:
            return {"error": f"Failed to get page content: {e!s}"}

    @mcp.tool()
    async def browser_screenshot(
        url: str,
        output_path: str = "screenshot.png",
        full_page: bool = True,
        timeout: int = 30000,
    ) -> dict:
        """
        Navigate to a URL and capture a screenshot.

        Use this when you need a visual snapshot of a webpage for reporting,
        monitoring, debugging, or documentation purposes.

        Args:
            url: The URL to screenshot
            output_path: File path to save the screenshot (default: "screenshot.png")
            full_page: If True, capture full scrollable page; if False, capture viewport only
            timeout: Maximum time in milliseconds to wait for page load (default: 30000)

        Returns:
            Dict with keys: path, width, height or error dict
        """
        try:
            # Validate URL
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            # Validate timeout
            timeout = max(5000, min(timeout, 300000))  # 5s to 5min

            # Ensure output directory exists and path is within working directory
            output_file = Path(output_path).resolve()
            allowed_base = Path.cwd().resolve()
            if not str(output_file).startswith(str(allowed_base)):
                return {"error": "output_path must be within the working directory"}
            output_file.parent.mkdir(parents=True, exist_ok=True)

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                try:
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent=BROWSER_USER_AGENT,
                        locale="en-US",
                    )
                    page = await context.new_page()

                    await page.goto(url, timeout=timeout, wait_until="networkidle")

                    await page.screenshot(path=str(output_path), full_page=full_page)

                    viewport = page.viewport_size

                    return {
                        "path": str(output_path),
                        "width": viewport["width"] if viewport else None,
                        "height": viewport["height"] if viewport else None,
                    }
                finally:
                    await browser.close()

        except PlaywrightTimeout:
            return {"error": f"Request timed out after {timeout}ms"}
        except PlaywrightError as e:
            return {"error": f"Browser error: {e!s}"}
        except Exception as e:
            return {"error": f"Failed to capture screenshot: {e!s}"}

    @mcp.tool()
    async def browser_extract_text(
        url: str,
        selector: str | None = None,
        timeout: int = 30000,
    ) -> dict:
        """
        Navigate to a URL and extract visible text content.

        Use this when you need clean text content from a page without HTML tags.
        Works with JavaScript-rendered content.

        Args:
            url: The URL to extract text from
            selector: Optional CSS selector to extract text from a specific element.
                     If None, extracts from body
            timeout: Maximum time in milliseconds to wait for page load (default: 30000)

        Returns:
            Dict with keys: text, title, url or error dict
        """
        try:
            # Validate URL
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            # Validate timeout
            timeout = max(5000, min(timeout, 300000))  # 5s to 5min

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                try:
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent=BROWSER_USER_AGENT,
                        locale="en-US",
                    )
                    page = await context.new_page()

                    await page.goto(url, timeout=timeout, wait_until="networkidle")

                    if selector:
                        element = await page.query_selector(selector)
                        if not element:
                            return {"error": f"No element found matching selector: {selector}"}
                        text = await element.inner_text()
                    else:
                        text = await page.inner_text("body")

                    title = await page.title()
                    final_url = page.url

                    return {
                        "text": text,
                        "title": title,
                        "url": final_url,
                    }
                finally:
                    await browser.close()

        except PlaywrightTimeout:
            return {"error": f"Request timed out after {timeout}ms"}
        except PlaywrightError as e:
            return {"error": f"Browser error: {e!s}"}
        except Exception as e:
            return {"error": f"Failed to extract text: {e!s}"}

    @mcp.tool()
    async def browser_click_and_extract(
        url: str,
        click_selector: str,
        wait_for_selector: str | None = None,
        timeout: int = 30000,
    ) -> dict:
        """
        Navigate to a URL, click an element, wait for result, and return updated page content.

        Use this when you need to interact with a page (e.g., click a button, link, or tab)
        and then extract the resulting content.

        Args:
            url: The URL to navigate to
            click_selector: CSS selector of the element to click
            wait_for_selector: Optional CSS selector to wait for after clicking
                              (defaults to waiting for network idle)
            timeout: Maximum time in milliseconds to wait for page load (default: 30000)

        Returns:
            Dict with keys: html, title, url, clicked_element or error dict
        """
        try:
            # Validate URL
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            # Validate timeout
            timeout = max(5000, min(timeout, 300000))  # 5s to 5min

            if not click_selector:
                return {"error": "click_selector is required"}

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                try:
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent=BROWSER_USER_AGENT,
                        locale="en-US",
                    )
                    page = await context.new_page()

                    await page.goto(url, timeout=timeout, wait_until="networkidle")

                    # Wait for the element to be clickable
                    await page.wait_for_selector(click_selector, timeout=timeout, state="visible")

                    # Click the element
                    await page.click(click_selector)

                    # Wait for result
                    if wait_for_selector:
                        await page.wait_for_selector(wait_for_selector, timeout=timeout)
                    else:
                        # Wait for network to settle after click
                        await page.wait_for_load_state("networkidle", timeout=timeout)

                    content = await page.content()
                    title = await page.title()
                    final_url = page.url

                    return {
                        "html": content,
                        "title": title,
                        "url": final_url,
                        "clicked_element": click_selector,
                    }
                finally:
                    await browser.close()

        except PlaywrightTimeout:
            return {"error": f"Request timed out after {timeout}ms"}
        except PlaywrightError as e:
            return {"error": f"Browser error: {e!s}"}
        except Exception as e:
            return {"error": f"Failed to click and extract: {e!s}"}

    @mcp.tool()
    async def browser_inspect_form(
        url: str,
        form_selector: str | None = None,
        timeout: int = 30000,
    ) -> dict:
        """
        Inspect a form on a webpage and return human-readable field information with CSS selectors.

        Use this before browser_fill_form to discover what fields are available on a form.
        The LLM can use this information to ask users for values, then convert those values
        to CSS selectors for browser_fill_form.

        Args:
            url: The URL to navigate to
            form_selector: Optional CSS selector for a specific form element.
                        If None, inspects all forms on the page
            timeout: Maximum time in milliseconds to wait for page load (default: 30000)

        Returns:
            Dict with keys: forms (list of form objects, each containing fields list),
            forms_found (count), title, url, or error dict.
        """
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            timeout = max(5000, min(timeout, 300000))

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                try:
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent=BROWSER_USER_AGENT,
                        locale="en-US",
                    )

                    page = await context.new_page()
                    await page.goto(url, timeout=timeout, wait_until="networkidle")

                    inspect_script = """
                (formSelector) => {

                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };

                    const getSelector = (el, form) => {
                        if (el.id) return `#${el.id}`;
                        if (el.name) return `[name="${el.name}"]`;

                        const tag = el.tagName.toLowerCase();
                        const siblings = Array.from(form.querySelectorAll(tag));
                        const index = siblings.indexOf(el);
                        return `${tag}:nth-of-type(${index + 1})`;
                    };

                    const forms = formSelector
                        ? document.querySelectorAll(formSelector)
                        : document.querySelectorAll("form");

                    if (!forms || forms.length === 0) {
                        return { forms: [], forms_found: 0 };
                    }

                    const results = [];

                    forms.forEach((form, formIndex) => {

                        const fields = [];
                        const elements = form.querySelectorAll("input, textarea, select");

                        elements.forEach((el) => {
                            const type = (el.type || el.tagName).toLowerCase();

                            if (
                                el.disabled ||
                                type === "hidden" ||
                                type === "submit" ||
                                type === "button" ||
                                type === "reset" ||
                                !visible(el)
                            ) {
                                return;
                            }

                            let label = "";

                            if (el.id) {
                                const labelEl = form.querySelector(`label[for="${el.id}"]`);
                                if (labelEl) {
                                    label = labelEl.textContent?.trim() || "";
                                }
                            }

                            if (!label) {
                                const parentLabel = el.closest("label");
                                if (parentLabel) {
                                    label = parentLabel.textContent?.trim() || "";
                                }
                            }

                            label = label || el.placeholder || el.name || "Unnamed Field";

                            const field = {
                                label: label,
                                name: el.name || "",
                                type: type,
                                selector: getSelector(el, form),
                                required: el.required || false,
                                placeholder: el.placeholder || "",
                            };

                            if (el.tagName.toLowerCase() === "select") {
                                field.options = Array.from(el.options).map(o => ({
                                    value: o.value,
                                    text: o.text
                                }));
                            }

                            if (type === "checkbox" || type === "radio") {
                                field.checked = el.checked;
                                field.value = el.value;
                            }

                            fields.push(field);
                        });

                        results.push({
                            form_index: formIndex,
                            form_selector: formSelector || `form:nth-of-type(${formIndex + 1})`,
                            fields: fields
                        });
                    });

                    return {
                        forms: results,
                        forms_found: results.length
                    };
                }
                """

                    result = await page.evaluate(inspect_script, form_selector)

                    forms = result.get("forms", [])

                    for form in forms:
                        form_index = form["form_index"]

                        # Document-order aligned form locator
                        form_locator = page.locator("form").nth(form_index)

                        # Deterministic Playwright selector
                        generated_form_selector = f"form >> nth={form_index}"
                        form["generated_form_selector"] = generated_form_selector

                        # 1️⃣ Try strict submit types inside this form
                        strict_selector = 'button[type="submit"], input[type="submit"]'
                        text_selector = "button:has-text('Submit'), button:has-text('submit')"

                        submit_locator = form_locator.locator(strict_selector)
                        used_selector = strict_selector

                        if await submit_locator.count() == 0:
                            # 2️⃣ Fallback: visible Submit text
                            submit_locator = form_locator.locator(text_selector)
                            used_selector = text_selector

                        if await submit_locator.count() == 0:
                            form["submit_selector"] = None
                            continue

                        form["submit_selector"] = (
                            f"{generated_form_selector} >> {used_selector} >> nth=0"
                        )

                    title = await page.title()
                    final_url = page.url

                    return {
                        "forms": forms,
                        "forms_found": result.get("forms_found", 0),
                        "title": title,
                        "url": final_url,
                    }
                finally:
                    await browser.close()

        except PlaywrightTimeout:
            return {"error": f"Request timed out after {timeout}ms"}
        except PlaywrightError as e:
            return {"error": f"Browser error: {e!s}"}
        except Exception as e:
            return {"error": f"Failed to inspect form: {e!s}"}

    @mcp.tool()
    async def browser_fill_form(
        url: str,
        form_fields: str,
        submit: bool = False,
        submit_selector: str | None = None,
        wait_for_selector: str | None = None,
        timeout: int = 30000,
    ) -> dict:
        """
        Navigate to a URL, fill form fields by CSS selector, optionally submit, and return result.
        Use this when you need to automate form submissions, login flows, or data entry.
        Form fields should be provided as a JSON string mapping CSS selectors to values.

        Args:
            url: The URL to navigate to
            form_fields: JSON string mapping CSS selectors to values.
                Use browser_inspect_form tool to get the correct selectors.
                Example: '{"#username": "user@example.com", "#password": "secret123"}'
            submit: Whether to submit the form after filling (default: False)
            submit_selector: CSS selector of submit button (if different from form submit)
            wait_for_selector: Optional CSS selector to wait for after submission
                (defaults to waiting for network idle)
            timeout: Maximum time in milliseconds to wait for page load (default: 30000)

        Returns: Dict with keys: html, title, url, filled_fields, submitted or error dict

        """

        try:
            # Normalize URL
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            timeout = max(5000, min(timeout, 300000))

            # Parse JSON
            try:
                fields_dict = json.loads(form_fields)
            except json.JSONDecodeError as e:
                return {"error": f"Invalid JSON in form_fields: {e!s}"}

            if not isinstance(fields_dict, dict):
                return {"error": "form_fields must be a JSON object mapping selectors to values"}

            if not fields_dict:
                return {"error": "form_fields cannot be empty"}

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )

                try:
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent=BROWSER_USER_AGENT,
                        locale="en-US",
                    )
                    page = await context.new_page()

                    await page.goto(url, timeout=timeout, wait_until="domcontentloaded")

                    filled_fields: dict[str, str] = {}

                    # Fill Fields
                    for selector, value in fields_dict.items():
                        try:
                            await page.wait_for_selector(selector, timeout=timeout, state="visible")

                            element = await page.query_selector(selector)
                            if not element:
                                return {"error": f"Element not found: {selector}"}

                            tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
                            input_type = (await element.get_attribute("type") or "").lower()

                            # SELECT
                            if tag_name == "select":
                                await page.select_option(selector, str(value))

                            # CHECKBOX / RADIO
                            elif input_type in ("checkbox", "radio"):
                                should_check = str(value).lower() in (
                                    "true",
                                    "1",
                                    "yes",
                                    "on",
                                )
                                is_checked = await element.is_checked()
                                if should_check != is_checked:
                                    await page.click(selector)

                            # TEXT / TEXTAREA / OTHER
                            else:
                                try:
                                    await page.fill(selector, str(value))
                                except Exception:
                                    # Fallback for React-controlled inputs
                                    await page.click(selector)
                                    await page.type(selector, str(value), delay=20)

                            filled_fields[selector] = str(value)

                        except PlaywrightTimeout:
                            return {"error": f"Timeout waiting for field: {selector}"}
                        except Exception as e:
                            return {"error": f"Failed to fill field {selector}: {e!s}"}

                    submitted = False

                    # Submit Handling (Robust)
                    if submit:
                        try:
                            old_length = await page.evaluate(
                                "() => document.documentElement.outerHTML.length"
                            )

                            if submit_selector:
                                await page.wait_for_selector(
                                    submit_selector, timeout=timeout, state="visible"
                                )
                                await page.click(submit_selector)
                            else:
                                submit_button = await page.query_selector(
                                    'button[type="submit"], input[type="submit"]'
                                )
                                if not submit_button:
                                    submit_button = await page.query_selector(
                                        "button:has-text('Submit'), button:has-text('submit')"
                                    )

                                if submit_button:
                                    await submit_button.click()
                                else:
                                    last_selector = list(fields_dict.keys())[-1]
                                    await page.press(last_selector, "Enter")

                            submitted = True

                            if wait_for_selector:
                                await page.wait_for_selector(wait_for_selector, timeout=timeout)
                            else:
                                # Wait for any DOM change (short window)
                                try:
                                    await page.wait_for_function(
                                        """
                                        (oldLen) =>
                                            document.documentElement.outerHTML.length !== oldLen
                                        """,
                                        arg=old_length,
                                        timeout=5000,
                                    )
                                except PlaywrightTimeout:
                                    pass

                                # Small stabilization delay
                                await page.wait_for_timeout(1500)

                        except Exception as e:
                            return {"error": f"Failed to submit form: {e!s}"}

                    # Capture Final State
                    content = await page.content()
                    title = await page.title()
                    final_url = page.url

                    return {
                        "html": content,
                        "title": title,
                        "url": final_url,
                        "filled_fields": filled_fields,
                        "submitted": submitted,
                    }

                finally:
                    await browser.close()

        except PlaywrightTimeout:
            return {"error": f"Request timed out after {timeout}ms"}
        except PlaywrightError as e:
            return {"error": f"Browser error: {e!s}"}
        except Exception as e:
            return {"error": f"Failed to fill form: {e!s}"}
