from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("https://www.linkedin.com/login")
        print("Please log in to LinkedIn in the opened browser window.")
        input("Press Enter here when you have logged in...")
        
        # Now search connections
        print("Logged in. Ready to proceed.")
        browser.close()

if __name__ == "__main__":
    main()