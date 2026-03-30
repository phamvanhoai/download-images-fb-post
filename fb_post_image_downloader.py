import argparse
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


IMAGE_HOST_MARKERS = ("fbcdn.net", "scontent")
PHOTO_LINK_MARKERS = ("/photo/", "fbid=", "/posts/", "/media/set/")


def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*]+', "_", name).strip(" .")
    return sanitized or "download"


def looks_like_facebook_image(url: str) -> bool:
    return bool(url) and any(marker in url for marker in IMAGE_HOST_MARKERS)


def normalize_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    return url


def collect_photo_links(page, post_url: str) -> list[str]:
    raw_links = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]')).map((a) => a.href)
        """
    )
    links: list[str] = []
    seen = set()

    for raw_link in raw_links:
        link = normalize_url(raw_link)
        if not link:
            continue

        absolute = urljoin(post_url, link)
        if "facebook.com" not in absolute and "fb.watch" not in absolute:
            continue
        if not any(marker in absolute for marker in PHOTO_LINK_MARKERS):
            continue
        if absolute in seen:
            continue

        seen.add(absolute)
        links.append(absolute)

    return links


def collect_inline_images(page) -> list[str]:
    candidates = page.evaluate(
        """
        () => {
          const results = [];
          for (const img of document.querySelectorAll('img')) {
            const rect = img.getBoundingClientRect();
            const source =
              img.currentSrc ||
              img.src ||
              img.getAttribute('src') ||
              img.getAttribute('data-src') ||
              '';
            results.push({
              src: source,
              width: Math.max(img.naturalWidth || 0, rect.width || 0),
              height: Math.max(img.naturalHeight || 0, rect.height || 0),
              alt: img.alt || '',
            });
          }
          return results;
        }
        """
    )
    urls: list[str] = []
    seen = set()

    for item in candidates:
        src = normalize_url(item.get("src", ""))
        width = item.get("width", 0)
        height = item.get("height", 0)
        alt = (item.get("alt", "") or "").lower()

        if not looks_like_facebook_image(src):
            continue
        if width < 250 or height < 250:
            continue
        if "profile picture" in alt or "avatar" in alt:
            continue
        if src in seen:
            continue

        seen.add(src)
        urls.append(src)

    return urls


def collect_largest_image(page) -> str | None:
    candidates = page.evaluate(
        """
        () => {
          const results = [];
          for (const img of document.querySelectorAll('img')) {
            const source =
              img.currentSrc ||
              img.src ||
              img.getAttribute('src') ||
              img.getAttribute('data-src') ||
              '';
            const width = img.naturalWidth || 0;
            const height = img.naturalHeight || 0;
            results.push({ src: source, area: width * height, width, height });
          }
          results.sort((a, b) => b.area - a.area);
          return results;
        }
        """
    )
    for item in candidates:
        src = normalize_url(item.get("src", ""))
        if looks_like_facebook_image(src) and item.get("width", 0) >= 400:
            return src
    return None


def build_filename(index: int, url: str) -> str:
    parsed = urlparse(url)
    path_name = Path(parsed.path).name or f"image_{index:03d}.jpg"
    query = parse_qs(parsed.query)
    extension = Path(path_name).suffix or ".jpg"

    if "stp" in query:
        base_name = f"image_{index:03d}_{query['stp'][0]}"
    else:
        base_name = f"image_{index:03d}"

    return sanitize_filename(f"{base_name}{extension}")


def save_image(context, url: str, destination: Path) -> None:
    response = context.request.get(
        url,
        headers={
            "Referer": "https://www.facebook.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
        },
    )
    if not response.ok:
        raise RuntimeError(f"Download failed: {response.status} {url}")
    destination.write_bytes(response.body())


def scroll_page(page, rounds: int = 6) -> None:
    for _ in range(rounds):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1200)


def extract_image_urls_from_post(page, post_url: str, log_callback=None) -> list[str]:
    scroll_page(page)
    urls: list[str] = []
    seen = set()
    photo_links = collect_photo_links(page, post_url)

    if log_callback:
        log_callback(f"Tim thay {len(photo_links)} link anh trong bai post.")

    for index, link in enumerate(photo_links, start=1):
        if log_callback:
            log_callback(f"Dang mo anh {index}/{len(photo_links)}")

        photo_page = page.context.new_page()
        try:
            photo_page.goto(link, wait_until="domcontentloaded", timeout=60000)
            photo_page.wait_for_timeout(2000)
            scroll_page(photo_page, rounds=2)
            biggest = collect_largest_image(photo_page)
            if biggest and biggest not in seen:
                seen.add(biggest)
                urls.append(biggest)
        except PlaywrightTimeoutError:
            if log_callback:
                log_callback(f"Bo qua 1 anh do timeout: {link}")
        finally:
            photo_page.close()

    if urls:
        return urls

    inline_images = collect_inline_images(page)
    if log_callback:
        log_callback(f"Khong mo duoc link photo rieng, thu fallback voi {len(inline_images)} anh inline.")

    for src in inline_images:
        if src not in seen:
            seen.add(src)
            urls.append(src)

    return urls


def ensure_logged_in(page, post_url: str) -> None:
    page.goto(post_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    current_url = page.url.lower()
    content = page.content().lower()
    if "login" in current_url or "log in" in content:
        raise RuntimeError(
            "Facebook chua dang nhap. Hay bat mo trinh duyet de dang nhap vao profile Playwright truoc."
        )


def normalize_browser_profile_inputs(
    browser_user_data_dir: str | Path | None,
    browser_profile_directory: str | None,
) -> tuple[str | None, str | None]:
    user_data_dir = str(browser_user_data_dir).strip() if browser_user_data_dir else None
    profile_directory = browser_profile_directory.strip() if browser_profile_directory else None

    if profile_directory and ("\\" in profile_directory or "/" in profile_directory):
        profile_path = Path(profile_directory)
        if not user_data_dir:
            user_data_dir = str(profile_path.parent)
        profile_directory = profile_path.name

    return user_data_dir, profile_directory


def discover_profile_candidates(
    browser_user_data_dir: str | None,
    browser_profile_directory: str | None,
) -> list[str | None]:
    candidates: list[str | None] = []

    def add_candidate(value: str | None) -> None:
        if value not in candidates:
            candidates.append(value)

    add_candidate(browser_profile_directory or None)

    if not browser_user_data_dir:
        if not candidates:
            add_candidate(None)
        return candidates

    user_data_path = Path(browser_user_data_dir)
    if not user_data_path.exists():
        return candidates or [browser_profile_directory or None]

    add_candidate("Default")
    for child in sorted(user_data_path.iterdir()):
        if child.is_dir() and child.name.startswith("Profile "):
            add_candidate(child.name)

    if not candidates:
        add_candidate(None)
    return candidates


def build_launch_kwargs(
    user_data_dir: str,
    headful: bool,
    browser_channel: str | None,
    browser_executable_path: str | Path | None,
    browser_profile_directory: str | None,
) -> dict:
    launch_kwargs = {
        "user_data_dir": user_data_dir,
        "headless": not headful,
        "viewport": {"width": 1400, "height": 1200},
    }
    if browser_channel:
        launch_kwargs["channel"] = browser_channel
    if browser_executable_path:
        launch_kwargs["executable_path"] = str(browser_executable_path)
    if browser_profile_directory:
        launch_kwargs["args"] = [f"--profile-directory={browser_profile_directory}"]
    return launch_kwargs


def resolve_or_create_page(browser, post_url: str):
    for context in browser.contexts:
        for page in context.pages:
            if "facebook.com" in page.url or page.url == "about:blank":
                return context, page

    if browser.contexts:
        context = browser.contexts[0]
    else:
        context = browser.new_context()

    if context.pages:
        return context, context.pages[0]
    return context, context.new_page()


def download_with_connected_browser(browser, post_url: str, output_path: Path, log_callback=None) -> list[Path]:
    context, page = resolve_or_create_page(browser, post_url)

    if log_callback:
        log_callback("Dang mo bai post Facebook tren trinh duyet dang chay...")
    ensure_logged_in(page, post_url)

    image_urls = extract_image_urls_from_post(page, post_url, log_callback=log_callback)
    if not image_urls:
        raise RuntimeError("Khong tim thay anh nao trong bai post.")

    saved_files = []
    total = len(image_urls)
    for index, url in enumerate(image_urls, start=1):
        filename = build_filename(index, url)
        destination = output_path / filename
        if log_callback:
            log_callback(f"Dang tai anh {index}/{total}: {filename}")
        save_image(context, url, destination)
        saved_files.append(destination)

    if log_callback:
        log_callback(f"Hoan tat. Da tai {len(saved_files)} anh.")
    return saved_files


def download_post_images(
    post_url: str,
    output_dir: str | Path = "downloads",
    profile_dir: str | Path = ".playwright-facebook-profile",
    headful: bool = False,
    browser_channel: str | None = None,
    browser_executable_path: str | Path | None = None,
    browser_user_data_dir: str | Path | None = None,
    browser_profile_directory: str | None = None,
    cdp_url: str | None = None,
    log_callback=None,
) -> list[Path]:
    if not post_url.strip():
        raise ValueError("Ban chua nhap link bai post Facebook.")

    browser_user_data_dir, browser_profile_directory = normalize_browser_profile_inputs(
        browser_user_data_dir,
        browser_profile_directory,
    )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        if cdp_url:
            if log_callback:
                log_callback(f"Dang ket noi vao trinh duyet co san: {cdp_url}")
            try:
                browser = playwright.chromium.connect_over_cdp(cdp_url)
            except Exception as exc:
                raise RuntimeError(
                    "Khong ket noi duoc vao Coc Coc dang mo. Hay mo Coc Coc bang remote debugging, "
                    "vi du voi --remote-debugging-port=9222."
                ) from exc
            try:
                return download_with_connected_browser(browser, post_url, output_path, log_callback=log_callback)
            finally:
                browser.close()

        if log_callback:
            log_callback("Dang khoi dong trinh duyet...")

        user_data_dir = str(browser_user_data_dir or profile_dir)
        profile_candidates = discover_profile_candidates(user_data_dir, browser_profile_directory)
        last_error: Exception | None = None

        for profile_candidate in profile_candidates:
            context = None
            try:
                if log_callback:
                    profile_label = profile_candidate or "mac dinh"
                    log_callback(f"Thu profile: {profile_label}")

                launch_kwargs = build_launch_kwargs(
                    user_data_dir=user_data_dir,
                    headful=headful,
                    browser_channel=browser_channel,
                    browser_executable_path=browser_executable_path,
                    browser_profile_directory=profile_candidate,
                )
                context = playwright.chromium.launch_persistent_context(**launch_kwargs)
                page = context.new_page()

                if log_callback:
                    log_callback("Dang mo bai post Facebook...")
                ensure_logged_in(page, post_url)

                image_urls = extract_image_urls_from_post(page, post_url, log_callback=log_callback)
                if not image_urls:
                    raise RuntimeError("Khong tim thay anh nao trong bai post.")

                saved_files = []
                total = len(image_urls)
                for index, url in enumerate(image_urls, start=1):
                    filename = build_filename(index, url)
                    destination = output_path / filename
                    if log_callback:
                        log_callback(f"Dang tai anh {index}/{total}: {filename}")
                    save_image(context, url, destination)
                    saved_files.append(destination)

                if log_callback:
                    log_callback(f"Hoan tat. Da tai {len(saved_files)} anh.")
                return saved_files
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if log_callback:
                    log_callback(f"Profile khong dung duoc: {profile_candidate or 'mac dinh'}")

                if "Target page, context or browser has been closed" in message:
                    continue
                if "Facebook chua dang nhap" in message and profile_candidate != profile_candidates[-1]:
                    continue
                if "net::ERR_ABORTED" in message and profile_candidate != profile_candidates[-1]:
                    continue
                if profile_candidate != profile_candidates[-1]:
                    continue
            finally:
                if context:
                    context.close()

        if last_error and "Target page, context or browser has been closed" in str(last_error):
            raise RuntimeError(
                "Khong mo duoc profile trinh duyet. Hay dong Coc Coc/Chrome/Edge truoc, "
                "roi mo lai tool. Neu van loi, bat tuy chon nang cao va chon dung User Data."
            ) from last_error
        if last_error:
            raise last_error
        raise RuntimeError("Khong tim thay profile trinh duyet phu hop.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download all images from a Facebook post."
    )
    parser.add_argument("post_url", help="Facebook post URL")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="downloads",
        help="Directory to save images (default: downloads)",
    )
    parser.add_argument(
        "--profile-dir",
        default=".playwright-facebook-profile",
        help="Persistent Chromium profile directory",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Open browser UI so you can log in to Facebook if needed",
    )
    parser.add_argument(
        "--browser-channel",
        choices=["chrome", "msedge"],
        help="Use installed Chrome or Edge instead of bundled Chromium",
    )
    parser.add_argument(
        "--browser-user-data-dir",
        help="Browser user data dir to reuse existing login session",
    )
    parser.add_argument(
        "--browser-executable-path",
        help="Full path to a Chromium-based browser executable such as Coc Coc browser.exe",
    )
    parser.add_argument(
        "--browser-profile-directory",
        help="Browser profile directory name such as Default or Profile 1",
    )
    parser.add_argument(
        "--cdp-url",
        help="Connect to an already running Chromium browser via CDP, for example http://127.0.0.1:9222",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        saved_files = download_post_images(
            post_url=args.post_url,
            output_dir=args.output_dir,
            profile_dir=args.profile_dir,
            headful=args.headful,
            browser_channel=args.browser_channel,
            browser_executable_path=args.browser_executable_path,
            browser_user_data_dir=args.browser_user_data_dir,
            browser_profile_directory=args.browser_profile_directory,
            cdp_url=args.cdp_url,
            log_callback=print,
        )
    except Exception as exc:
        print(f"Loi: {exc}")
        return 1

    print(f"Anh da luu tai: {Path(args.output_dir).resolve()}")
    print(f"Tong so anh: {len(saved_files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
