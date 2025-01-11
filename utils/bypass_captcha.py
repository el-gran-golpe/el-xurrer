import cv2
import numpy as np
import os

async def detect_and_solve_captcha(page, screenshot_path, template_path):
    """Detect and solve Cloudflare Turnstile CAPTCHA by template matching and automated click."""

    # Capture a screenshot of the full page using Playwright
    try:
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"Screenshot saved at: {os.path.abspath(screenshot_path)}")
    except Exception as e:
        raise RuntimeError(f"[ERROR] Failed to capture screenshot: {e}")

    # Load the screenshot and the captcha template image
    screenshot = cv2.imread(screenshot_path, cv2.IMREAD_GRAYSCALE)
    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)

    # Check if images were loaded correctly
    if screenshot is None:
        raise FileNotFoundError("[ERROR] Failed to load screenshot. Please check the file path and format.")
    if template is None:
        raise FileNotFoundError("[ERROR] Failed to load template image. Please check the file path.")

    # Apply edge detection to both images
    edges_screenshot = cv2.Canny(screenshot, 50, 150)
    edges_template = cv2.Canny(template, 50, 150)

    # Template matching to find the checkbox
    result = cv2.matchTemplate(edges_screenshot, edges_template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    if max_val < 0.8:  # Threshold for matching
        print("CAPTCHA checkbox not detected with sufficient confidence.")
        return False

    # Define the bounding box for the detected checkbox
    top_left = max_loc
    h, w = template.shape
    bottom_right = (top_left[0] + w, top_left[1] + h)

    # Draw a rectangle around the detected checkbox (for visualization)
    detected_image = cv2.imread(screenshot_path)
    cv2.rectangle(detected_image, top_left, bottom_right, (0, 255, 0), 2)
    cv2.imwrite("detected_checkbox.png", detected_image)

    print(f"Checkbox detected at: {top_left}, {bottom_right}")

    # Calculate the center of the detected checkbox
    center_x = top_left[0] + w // 2
    center_y = top_left[1] + h // 2

    # Get the actual window size using JavaScript
    viewport_size = await page.evaluate("""
        () => ({ width: window.innerWidth, height: window.innerHeight })
    """)
    screenshot_height, screenshot_width = screenshot.shape

    # Calculate scaling factors
    scale_x = viewport_size['width'] / screenshot_width
    scale_y = viewport_size['height'] / screenshot_height

    # Scale the detected coordinates to match the actual viewport size
    real_x = int(center_x * scale_x)
    real_y = int(center_y * scale_y)

    print(f"Simulating click at scaled coordinates: ({real_x}, {real_y})")

    # Simulate a click at the scaled coordinates
    await page.mouse.click(real_x, real_y)
    return True