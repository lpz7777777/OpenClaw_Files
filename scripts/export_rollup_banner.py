from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright


WIDTH = 4724
HEIGHT = 11811
VIEWPORT_HEIGHT = 1800


def export_banner():
    project_root = Path(__file__).resolve().parent.parent
    html_path = (project_root / "banner_rollup.html").resolve().as_uri()
    output_path = project_root / "banner_rollup_150dpi.png"
    parts_dir = project_root / "tmp_banner_parts"
    parts_dir.mkdir(exist_ok=True)

    for part in parts_dir.glob("part_*.png"):
        part.unlink()
    if output_path.exists():
        output_path.unlink()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(
            viewport={"width": WIDTH, "height": VIEWPORT_HEIGHT},
            device_scale_factor=1,
        )
        page.goto(html_path, wait_until="networkidle")
        page.evaluate(
            """
            async () => {
                const images = Array.from(document.images);
                await Promise.all(images.map((img) =>
                    img.complete
                        ? Promise.resolve()
                        : new Promise((resolve) => {
                              img.addEventListener("load", resolve, { once: true });
                              img.addEventListener("error", resolve, { once: true });
                          })
                ));
                if (document.fonts && document.fonts.ready) {
                    await document.fonts.ready;
                }
                document.documentElement.style.scrollBehavior = "auto";
                document.body.style.scrollBehavior = "auto";
            }
            """
        )

        stitched = Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, 255))
        current_y = 0
        index = 0
        while current_y < HEIGHT:
            page.evaluate(f"window.scrollTo(0, {current_y})")
            page.wait_for_timeout(250)
            clip_height = min(VIEWPORT_HEIGHT, HEIGHT - current_y)
            part_path = parts_dir / f"part_{index:02d}.png"
            page.screenshot(
                path=str(part_path),
                clip={"x": 0, "y": 0, "width": WIDTH, "height": clip_height},
            )
            stitched.paste(Image.open(part_path).convert("RGBA"), (0, current_y))
            current_y += clip_height
            index += 1

        browser.close()

    stitched.save(output_path, dpi=(150, 150))

    for part in parts_dir.glob("part_*.png"):
        part.unlink()
    parts_dir.rmdir()

    print(output_path)
    print(Image.open(output_path).size)
    print(Image.open(output_path).info.get("dpi"))


if __name__ == "__main__":
    export_banner()
