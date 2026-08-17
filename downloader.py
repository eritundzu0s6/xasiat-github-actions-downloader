import asyncio
import aiohttp
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

# ============================================================
# GitHub Actions / 本地均可运行
# ============================================================

BASE_URL = "https://www.xasiat.com/albums/{}/cosplay-g44-32p-396mb/"

# 第一次测试默认只跑 1~20
START_ID = int(os.getenv("START_ID", "1"))
END_ID = int(os.getenv("END_ID", "20"))

# GitHub 项目里的保存目录
ROOT_DIR = Path(os.getenv("ROOT_DIR", "downloads"))

IMAGE_CONCURRENCY = int(os.getenv("IMAGE_CONCURRENCY", "10"))
RETRIES = int(os.getenv("RETRIES", "5"))

PAGE_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=20, sock_read=60)
IMAGE_TIMEOUT = aiohttp.ClientTimeout(total=180, connect=30, sock_read=180)

DOWNLOADED_FILE = ROOT_DIR / "downloaded.txt"
COMPLETE_FILE = ".complete"

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}


def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = name.strip()
    return name.rstrip(" .")


def get_filename_from_original(data_original):
    if not data_original:
        return None

    clean_url = data_original.split("?", 1)[0].rstrip("/")
    filename = os.path.basename(urlparse(clean_url).path)

    if not filename:
        return None

    if not re.search(r"\.(jpg|jpeg|png|webp|gif)$", filename, re.IGNORECASE):
        return None

    return filename


def is_image_url(url):
    return bool(
        re.search(
            r"\.(jpg|jpeg|png|webp|gif)(?:[/ ?]|$)",
            url,
            re.IGNORECASE,
        )
    )


def load_downloaded():
    downloaded = set()

    if not DOWNLOADED_FILE.exists():
        return downloaded

    try:
        with open(DOWNLOADED_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                album_id = line.split("|", 1)[0].strip()
                if album_id.isdigit():
                    downloaded.add(int(album_id))
    except Exception as e:
        print(f"[警告] 读取记忆失败：{e}", flush=True)

    return downloaded


def append_downloaded(album_id, folder_name):
    with open(DOWNLOADED_FILE, "a", encoding="utf-8") as f:
        f.write(f"{album_id}|{folder_name}\n")


def parse_page(html, page_url):
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    if not h1:
        return None, []

    folder_name = safe_filename(h1.get_text(" ", strip=True))

    images_container = soup.select_one(".images")
    if not images_container:
        return folder_name, []

    image_list = []

    for a in images_container.find_all("a", href=True):
        href = a["href"].strip()

        if not is_image_url(href):
            continue

        img = a.find("img")
        if not img:
            continue

        data_original = img.get("data-original", "").strip()
        if not data_original:
            continue

        filename = get_filename_from_original(data_original)
        if not filename:
            continue

        image_url = urljoin(page_url, href)

        if any(x["filename"] == filename for x in image_list):
            continue

        image_list.append({"url": image_url, "filename": filename})

    return folder_name, image_list


async def fetch_page(session, album_id):
    page_url = BASE_URL.format(album_id)

    print(f"\n[{album_id}/{END_ID}] 正在获取页面...", flush=True)

    for attempt in range(1, RETRIES + 1):
        try:
            headers = {
                **BASE_HEADERS,
                "Referer": "https://www.xasiat.com/",
            }

            async with session.get(
                page_url, headers=headers, timeout=PAGE_TIMEOUT
            ) as response:

                if response.status == 404:
                    print(f"[{album_id}/{END_ID}] HTTP 404", flush=True)
                    return {"status": "404", "folder": None, "images": []}

                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")

                html = await response.text(errors="ignore")

            folder_name, images = parse_page(html, page_url)

            if not folder_name:
                print(f"[{album_id}/{END_ID}] 没有找到 H1", flush=True)
                return {"status": "no_h1", "folder": None, "images": []}

            if not images:
                print(f"[{album_id}/{END_ID}] 文件夹：{folder_name}", flush=True)
                print(f"[{album_id}/{END_ID}] 图片数量：0", flush=True)
                return {"status": "empty", "folder": folder_name, "images": []}

            print(f"[{album_id}/{END_ID}] 文件夹：{folder_name}", flush=True)
            print(f"[{album_id}/{END_ID}] 图片数量：{len(images)}", flush=True)

            return {"status": "ok", "folder": folder_name, "images": images}

        except Exception as e:
            print(
                f"[{album_id}/{END_ID}] 获取页面失败 "
                f"({attempt}/{RETRIES})：{e}",
                flush=True,
            )
            if attempt < RETRIES:
                await asyncio.sleep(1.5 * attempt)

    return {"status": "error", "folder": None, "images": []}


async def download_image(
    session, semaphore, album_id, image_url, filepath, index, total
):
    if filepath.exists() and filepath.stat().st_size > 0:
        print(f"    [{index}/{total}] 跳过：{filepath.name}", flush=True)
        return "skip"

    async with semaphore:
        for attempt in range(1, RETRIES + 1):
            temp_file = filepath.with_name(filepath.name + ".part")

            try:
                headers = {
                    **BASE_HEADERS,
                    "Referer": BASE_URL.format(album_id),
                    "Accept": (
                        "image/avif,image/webp,image/apng,image/svg+xml,"
                        "image/*,*/*;q=0.8"
                    ),
                }

                async with session.get(
                    image_url, headers=headers, timeout=IMAGE_TIMEOUT
                ) as response:
                    if response.status != 200:
                        raise RuntimeError(f"HTTP {response.status}")

                    with open(temp_file, "wb") as f:
                        while True:
                            chunk = await response.content.read(256 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)

                if not temp_file.exists() or temp_file.stat().st_size == 0:
                    raise RuntimeError("下载文件为空")

                os.replace(temp_file, filepath)

                print(
                    f"    [{index}/{total}] ✓ {filepath.name}",
                    flush=True,
                )
                return "success"

            except Exception as e:
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass

                if attempt < RETRIES:
                    await asyncio.sleep(1.5 * attempt)
                else:
                    print(
                        f"    [{index}/{total}] ✗ {filepath.name} "
                        f"失败：{e}",
                        flush=True,
                    )

    return "failed"


async def download_folder(session, album_id, folder_name, images):
    save_dir = ROOT_DIR / folder_name
    save_dir.mkdir(parents=True, exist_ok=True)

    total = len(images)

    print("\n" + "=" * 70)
    print(f"[{album_id}/{END_ID}] 开始处理文件夹")
    print(f"文件夹：{folder_name}")
    print(f"图片数量：{total}")
    print(f"图片并发：{IMAGE_CONCURRENCY}")
    print("=" * 70)

    semaphore = asyncio.Semaphore(IMAGE_CONCURRENCY)
    tasks = []

    for index, item in enumerate(images, start=1):
        filepath = save_dir / item["filename"]
        tasks.append(
            download_image(
                session=session,
                semaphore=semaphore,
                album_id=album_id,
                image_url=item["url"],
                filepath=filepath,
                index=index,
                total=total,
            )
        )

    results = await asyncio.gather(*tasks)

    success = results.count("success")
    skipped = results.count("skip")
    failed = results.count("failed")

    if failed == 0:
        complete_file = save_dir / COMPLETE_FILE
        try:
            with open(complete_file, "w", encoding="utf-8") as f:
                f.write(
                    f"album_id={album_id}\n"
                    f"folder={folder_name}\n"
                    f"images={total}\n"
                    f"success={success}\n"
                    f"skip={skipped}\n"
                )
        except Exception as e:
            print(f"[警告] 创建 .complete 失败：{e}", flush=True)

        print(f"[{album_id}/{END_ID}] ✓ 文件夹处理完成")
        print(f"成功：{success}")
        print(f"跳过：{skipped}")
        print(f"失败：{failed}")
        return True

    print(f"[{album_id}/{END_ID}] ✗ 文件夹没有完成")
    print(f"成功：{success}")
    print(f"跳过：{skipped}")
    print(f"失败：{failed}")
    return False


async def main():
    ROOT_DIR.mkdir(parents=True, exist_ok=True)

    downloaded = load_downloaded()
    total = END_ID - START_ID + 1

    print("\n" + "=" * 80)
    print("XAsiaT GitHub Actions 单文件夹顺序下载器")
    print("=" * 80)
    print(f"ID：{START_ID} ~ {END_ID}")
    print(f"总数：{total:,}")
    print(f"根目录：{ROOT_DIR}")
    print("文件夹并发：1")
    print(f"单文件夹图片并发：{IMAGE_CONCURRENCY}")
    print(f"已经记忆：{len(downloaded):,}")
    print(f"记忆文件：{DOWNLOADED_FILE}")
    print("=" * 80)

    connector = aiohttp.TCPConnector(
        limit=IMAGE_CONCURRENCY,
        limit_per_host=IMAGE_CONCURRENCY,
        ssl=False,
        keepalive_timeout=30,
    )

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=PAGE_TIMEOUT,
        headers=BASE_HEADERS,
    ) as session:

        for album_id in range(START_ID, END_ID + 1):

            if album_id in downloaded:
                print(
                    f"[{album_id}/{END_ID}] ✓ 已下载 → 跳过",
                    flush=True,
                )
                continue

            result = await fetch_page(session, album_id)
            status = result["status"]

            if status == "404":
                continue

            if status == "error":
                print(
                    f"[{album_id}/{END_ID}] ✗ 页面获取失败，进入下一个",
                    flush=True,
                )
                continue

            if status in ("no_h1", "empty"):
                continue

            completed = await download_folder(
                session=session,
                album_id=album_id,
                folder_name=result["folder"],
                images=result["images"],
            )

            if completed:
                append_downloaded(album_id, result["folder"])
                downloaded.add(album_id)
                print(
                    f"[{album_id}/{END_ID}] ✓ 已写入 downloaded.txt",
                    flush=True,
                )
            else:
                print(
                    f"[{album_id}/{END_ID}] ⚠ 本文件夹存在失败图片，"
                    f"不会写入完成记录",
                    flush=True,
                )

    print("\n" + "=" * 80)
    print("全部扫描完成")
    print(f"记忆数量：{len(downloaded):,}")
    print(f"目录：{ROOT_DIR}")
    print("=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断")
        print("已经完成的文件夹已经写入 downloaded.txt")
        print("下次运行会自动继续")
