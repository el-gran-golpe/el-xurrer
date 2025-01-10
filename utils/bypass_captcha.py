import cv2
import numpy as np
import os

async def detect_and_solve_captcha(page):
    """Detect and solve Cloudflare Turnstile CAPTCHA on the page."""
    
    # Define the path for saving the screenshot
    screenshot_path = "page_screenshot.png"
    
    # Capture a screenshot of the page using Playwright
    try:
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"Screenshot saved at: {os.path.abspath(screenshot_path)}")
    except Exception as e:
        print(f"[ERROR] Failed to capture screenshot: {e}")
        return False

    # Load the screenshot and template
    screenshot = cv2.imread(screenshot_path, cv2.IMREAD_GRAYSCALE)
    template = cv2.imread("captcha_template.png", cv2.IMREAD_GRAYSCALE)

    # Check if images were loaded correctly
    if screenshot is None:
        print("[ERROR] Failed to load screenshot. Please check the file path and format.")
        return False
    if template is None:
        print("[ERROR] Failed to load template image. Please check the file path.")
        return False

    # Check if template is smaller than the screenshot
    if template.shape[0] > screenshot.shape[0] or template.shape[1] > screenshot.shape[1]:
        print("[ERROR] Template is larger than the screenshot. Please use a smaller template.")
        return False

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

    # Simulate a click at the center of the detected checkbox
    center_x = top_left[0] + w // 2
    center_y = top_left[1] + h // 2
    await page.mouse.click(center_x, center_y)
    return True
