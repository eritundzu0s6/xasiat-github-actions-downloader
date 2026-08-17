import asyncio
import aiohttp
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup


# ============================================================
# 配置
# ============================================================

BASE_URL = (
    "https://www.xasiat.com/albums/"
    "{}/cosplay-g44-32p-396mb/"
)

# GitHub Actions 可以通过环境变量修改
START_ID = int(os.getenv("START_ID", "1"))
END_ID = int(os.getenv("END_ID", "20"))

# GitHub 项目里的下载目录
ROOT_DIR = Path(
    os.getenv("ROOT_DIR", "downloads")
)

# 同一个文件夹里面的图片并发数量
IMAGE_CONCURRENCY = int(
    os.getenv("IMAGE_CONCURRENCY", "10")
)

# 请求重试次数
RETRIES = int(
    os.getenv("RETRIES", "5")
)

# Git Push 重试次数
GIT_PUSH_RETRIES = 5

# Git Push 重试等待时间
GIT_PUSH_WAIT = 20


# ============================================================
# 超时
# ============================================================

PAGE_TIMEOUT = aiohttp.ClientTimeout(
    total=60,
    connect=20,
    sock_read=60
)

IMAGE_TIMEOUT = aiohttp.ClientTimeout(
    total=180,
    connect=30,
    sock_read=180
)


# ============================================================
# 记忆文件
# ============================================================

DOWNLOADED_FILE = ROOT_DIR / "downloaded.txt"

COMPLETE_FILE = ".complete"


# ============================================================
# Headers
# ============================================================

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),

    "Accept-Language":
        "zh-CN,zh;q=0.9,en;q=0.8",

    "Connection":
        "keep-alive",
}


# ============================================================
# Windows / Linux 文件名清理
# ============================================================

def safe_filename(name):

    name = re.sub(
        r'[<>:"/\\|?*]',
        "_",
        name
    )

    name = name.strip()

    name = name.rstrip(" .")

    return name


# ============================================================
# 从 data-original 获取文件名
# ============================================================

def get_filename_from_original(data_original):

    if not data_original:
        return None

    clean_url = data_original.split(
        "?",
        1
    )[0]

    clean_url = clean_url.rstrip("/")

    filename = os.path.basename(
        urlparse(clean_url).path
    )

    if not filename:
        return None

    if not re.search(
        r"\.(jpg|jpeg|png|webp|gif)$",
        filename,
        re.IGNORECASE
    ):
        return None

    return filename


# ============================================================
# 判断是否图片 URL
# ============================================================

def is_image_url(url):

    return bool(
        re.search(
            r"\.(jpg|jpeg|png|webp|gif)"
            r"(?:[/ ?]|$)",
            url,
            re.IGNORECASE
        )
    )


# ============================================================
# 读取下载记忆
# ============================================================

def load_downloaded():

    downloaded = set()

    if not DOWNLOADED_FILE.exists():
        return downloaded

    try:

        with open(
            DOWNLOADED_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            for line in f:

                line = line.strip()

                if not line:
                    continue

                album_id = line.split(
                    "|",
                    1
                )[0].strip()

                if album_id.isdigit():

                    downloaded.add(
                        int(album_id)
                    )

    except Exception as e:

        print(
            f"[警告] 读取记忆失败：{e}",
            flush=True
        )

    return downloaded


# ============================================================
# 写入下载记忆
# ============================================================

def append_downloaded(
    album_id,
    folder_name
):

    ROOT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        DOWNLOADED_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            f"{album_id}|{folder_name}\n"
        )


# ============================================================
# Git 命令
# ============================================================

def run_git_command(
    args,
    check=True
):

    print(
        "[GIT] git " + " ".join(args),
        flush=True
    )

    result = subprocess.run(
        ["git"] + args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    if result.stdout:
        print(
            result.stdout,
            flush=True
        )

    if check and result.returncode != 0:

        raise RuntimeError(
            f"Git 命令失败，退出码："
            f"{result.returncode}"
        )

    return result


# ============================================================
# Git Push
# ============================================================

def git_push_with_retry():

    for attempt in range(
        1,
        GIT_PUSH_RETRIES + 1
    ):

        print()
        print(
            "=" * 70
        )

        print(
            f"[GIT] Push "
            f"{attempt}/{GIT_PUSH_RETRIES}",
            flush=True
        )

        print(
            "=" * 70
        )

        result = subprocess.run(
            [
                "git",
                "push",
                "origin",
                "HEAD:${GITHUB_REF_NAME}"
            ],
            shell=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )

        if result.stdout:

            print(
                result.stdout,
                flush=True
            )

        if result.returncode == 0:

            print(
                "[GIT] ✓ Push 成功",
                flush=True
            )

            return True

        print(
            f"[GIT] ✗ Push 失败，退出码："
            f"{result.returncode}",
            flush=True
        )

        if attempt < GIT_PUSH_RETRIES:

            print(
                f"[GIT] 等待 "
                f"{GIT_PUSH_WAIT} 秒后重试...",
                flush=True
            )

            time.sleep(
                GIT_PUSH_WAIT
            )

    return False


# ============================================================
# 每个文件夹完成后提交
# ============================================================

def commit_and_push_folder(
    album_id,
    folder_name
):

    print()
    print(
        "=" * 80
    )

    print(
        f"[{album_id}/{END_ID}] "
        f"开始提交 GitHub",
        flush=True
    )

    print(
        f"文件夹：{folder_name}",
        flush=True
    )

    print(
        "=" * 80
    )

    try:

        # ----------------------------------------------------
        # 加入当前文件夹
        # ----------------------------------------------------

        folder_path = (
            ROOT_DIR /
            folder_name
        )

        run_git_command(
            [
                "add",
                "--",
                str(folder_path),
                str(DOWNLOADED_FILE)
            ]
        )

        # ----------------------------------------------------
        # 检查是否有变化
        # ----------------------------------------------------

        result = run_git_command(
            [
                "diff",
                "--cached",
                "--quiet"
            ],
            check=False
        )

        if result.returncode == 0:

            print(
                "[GIT] 没有新的变化",
                flush=True
            )

            return True

        # ----------------------------------------------------
        # Commit
        # ----------------------------------------------------

        commit_message = (
            f"Download album {album_id}: "
            f"{folder_name}"
        )

        run_git_command(
            [
                "commit",
                "-m",
                commit_message
            ]
        )

        # ----------------------------------------------------
        # Push
        # ----------------------------------------------------

        success = git_push_with_retry()

        if not success:

            print(
                "[GIT] ✗ Push 连续失败",
                flush=True
            )

            return False

        print()
        print(
            f"[{album_id}/{END_ID}] "
            f"✓ GitHub 提交完成",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"[GIT] ✗ Git 操作失败：{e}",
            flush=True
        )

        return False


# ============================================================
# 解析网页
# ============================================================

def parse_page(
    html,
    page_url
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # ========================================================
    # H1
    # ========================================================

    h1 = soup.find("h1")

    if not h1:

        return None, []

    folder_name = h1.get_text(
        " ",
        strip=True
    )

    folder_name = safe_filename(
        folder_name
    )

    # ========================================================
    # 图片区域
    # ========================================================

    images_container = soup.select_one(
        ".images"
    )

    if not images_container:

        return folder_name, []

    image_list = []

    # ========================================================
    # A
    # ========================================================

    for a in images_container.find_all(
        "a",
        href=True
    ):

        href = a["href"].strip()

        # ----------------------------------------------------
        # href 必须是图片
        # ----------------------------------------------------

        if not is_image_url(href):

            continue

        # ----------------------------------------------------
        # IMG
        # ----------------------------------------------------

        img = a.find("img")

        if not img:

            continue

        # ----------------------------------------------------
        # data-original
        # ----------------------------------------------------

        data_original = img.get(
            "data-original",
            ""
        ).strip()

        if not data_original:

            continue

        # ----------------------------------------------------
        # 文件名
        # ----------------------------------------------------

        filename = get_filename_from_original(
            data_original
        )

        if not filename:

            continue

        # ----------------------------------------------------
        # 原图 URL
        # ----------------------------------------------------

        image_url = urljoin(
            page_url,
            href
        )

        # ----------------------------------------------------
        # 去重
        # ----------------------------------------------------

        if any(
            x["filename"] == filename
            for x in image_list
        ):

            continue

        image_list.append({
            "url": image_url,
            "filename": filename,
        })

    return folder_name, image_list


# ============================================================
# 获取页面
# ============================================================

async def fetch_page(
    session,
    album_id
):

    page_url = BASE_URL.format(
        album_id
    )

    print(
        f"\n[{album_id}/{END_ID}] "
        f"正在获取页面...",
        flush=True
    )

    for attempt in range(
        1,
        RETRIES + 1
    ):

        try:

            headers = {
                **BASE_HEADERS,

                "Referer":
                    "https://www.xasiat.com/",
            }

            async with session.get(
                page_url,
                headers=headers,
                timeout=PAGE_TIMEOUT
            ) as response:

                # =================================================
                # 404
                # =================================================

                if response.status == 404:

                    print(
                        f"[{album_id}/{END_ID}] "
                        f"HTTP 404",
                        flush=True
                    )

                    return {
                        "status": "404",
                        "folder": None,
                        "images": []
                    }

                # =================================================
                # 其他错误
                # =================================================

                if response.status != 200:

                    raise RuntimeError(
                        f"HTTP {response.status}"
                    )

                html = await response.text(
                    errors="ignore"
                )

            # ====================================================
            # 解析
            # ====================================================

            folder_name, images = parse_page(
                html,
                page_url
            )

            # ====================================================
            # 没有 H1
            # ====================================================

            if not folder_name:

                print(
                    f"[{album_id}/{END_ID}] "
                    f"没有找到 H1",
                    flush=True
                )

                return {
                    "status": "no_h1",
                    "folder": None,
                    "images": []
                }

            # ====================================================
            # 没有图片
            # ====================================================

            if not images:

                print(
                    f"[{album_id}/{END_ID}] "
                    f"文件夹：{folder_name}",
                    flush=True
                )

                print(
                    f"[{album_id}/{END_ID}] "
                    f"图片数量：0",
                    flush=True
                )

                return {
                    "status": "empty",
                    "folder": folder_name,
                    "images": []
                }

            # ====================================================
            # 成功
            # ====================================================

            print(
                f"[{album_id}/{END_ID}] "
                f"文件夹：{folder_name}",
                flush=True
            )

            print(
                f"[{album_id}/{END_ID}] "
                f"图片数量：{len(images)}",
                flush=True
            )

            return {
                "status": "ok",
                "folder": folder_name,
                "images": images
            }

        except Exception as e:

            print(
                f"[{album_id}/{END_ID}] "
                f"获取页面失败 "
                f"({attempt}/{RETRIES})：{e}",
                flush=True
            )

            if attempt < RETRIES:

                await asyncio.sleep(
                    1.5 * attempt
                )

    return {
        "status": "error",
        "folder": None,
        "images": []
    }


# ============================================================
# 下载一张图片
# ============================================================

async def download_image(
    session,
    semaphore,
    album_id,
    image_url,
    filepath,
    index,
    total
):

    # ========================================================
    # 文件已经存在
    # ========================================================

    if (
        filepath.exists()
        and filepath.stat().st_size > 0
    ):

        print(
            f"    [{index}/{total}] "
            f"跳过：{filepath.name}",
            flush=True
        )

        return "skip"

    # ========================================================
    # 图片并发
    # ========================================================

    async with semaphore:

        for attempt in range(
            1,
            RETRIES + 1
        ):

            temp_file = filepath.with_name(
                filepath.name + ".part"
            )

            try:

                headers = {
                    **BASE_HEADERS,

                    "Referer":
                        BASE_URL.format(
                            album_id
                        ),

                    "Accept":
                        "image/avif,image/webp,"
                        "image/apng,image/svg+xml,"
                        "image/*,*/*;q=0.8"
                }

                # =================================================
                # 下载
                # =================================================

                async with session.get(
                    image_url,
                    headers=headers,
                    timeout=IMAGE_TIMEOUT
                ) as response:

                    if response.status != 200:

                        raise RuntimeError(
                            f"HTTP {response.status}"
                        )

                    with open(
                        temp_file,
                        "wb"
                    ) as f:

                        while True:

                            chunk = (
                                await response.content.read(
                                    256 * 1024
                                )
                            )

                            if not chunk:

                                break

                            f.write(chunk)

                # =================================================
                # 检查文件
                # =================================================

                if (
                    not temp_file.exists()
                    or temp_file.stat().st_size == 0
                ):

                    raise RuntimeError(
                        "下载文件为空"
                    )

                # =================================================
                # 正式文件
                # =================================================

                os.replace(
                    temp_file,
                    filepath
                )

                print(
                    f"    [{index}/{total}] "
                    f"✓ {filepath.name}",
                    flush=True
                )

                return "success"

            except Exception as e:

                if temp_file.exists():

                    try:

                        temp_file.unlink()

                    except Exception:

                        pass

                if attempt < RETRIES:

                    await asyncio.sleep(
                        1.5 * attempt
                    )

                else:

                    print(
                        f"    [{index}/{total}] "
                        f"✗ {filepath.name} "
                        f"失败：{e}",
                        flush=True
                    )

    return "failed"


# ============================================================
# 下载一个文件夹
#
# 文件夹之间绝对不并发
# 一个文件夹里面图片并发
# ============================================================

async def download_folder(
    session,
    album_id,
    folder_name,
    images
):

    save_dir = (
        ROOT_DIR /
        folder_name
    )

    save_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    total = len(images)

    print()
    print(
        "=" * 70
    )

    print(
        f"[{album_id}/{END_ID}] "
        f"开始处理文件夹"
    )

    print(
        f"文件夹：{folder_name}"
    )

    print(
        f"图片数量：{total}"
    )

    print(
        f"图片并发：{IMAGE_CONCURRENCY}"
    )

    print(
        "=" * 70
    )

    # ========================================================
    # 图片并发
    # ========================================================

    semaphore = asyncio.Semaphore(
        IMAGE_CONCURRENCY
    )

    tasks = []

    for index, item in enumerate(
        images,
        start=1
    ):

        filepath = (
            save_dir /
            item["filename"]
        )

        tasks.append(
            download_image(
                session=session,
                semaphore=semaphore,
                album_id=album_id,
                image_url=item["url"],
                filepath=filepath,
                index=index,
                total=total
            )
        )

    # ========================================================
    # 等待这个文件夹所有图片完成
    # ========================================================

    results = await asyncio.gather(
        *tasks
    )

    success = results.count(
        "success"
    )

    skipped = results.count(
        "skip"
    )

    failed = results.count(
        "failed"
    )

    # ========================================================
    # 全部成功
    # ========================================================

    if failed == 0:

        complete_file = (
            save_dir /
            COMPLETE_FILE
        )

        try:

            with open(
                complete_file,
                "w",
                encoding="utf-8"
            ) as f:

                f.write(
                    f"album_id={album_id}\n"
                    f"folder={folder_name}\n"
                    f"images={total}\n"
                    f"success={success}\n"
                    f"skip={skipped}\n"
                )

        except Exception as e:

            print(
                f"[警告] 创建 .complete 失败：{e}",
                flush=True
            )

        print()
        print(
            f"[{album_id}/{END_ID}] "
            f"✓ 文件夹处理完成"
        )

        print(
            f"成功：{success}"
        )

        print(
            f"跳过：{skipped}"
        )

        print(
            f"失败：{failed}"
        )

        return True

    # ========================================================
    # 有失败
    # ========================================================

    print()
    print(
        f"[{album_id}/{END_ID}] "
        f"✗ 文件夹没有完成"
    )

    print(
        f"成功：{success}"
    )

    print(
        f"跳过：{skipped}"
    )

    print(
        f"失败：{failed}"
    )

    return False


# ============================================================
# 主程序
# ============================================================

async def main():

    # ========================================================
    # 创建根目录
    # ========================================================

    ROOT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # ========================================================
    # Git 配置
    # ========================================================

    print()
    print(
        "=" * 80
    )

    print(
        "XAsiaT GitHub Actions 下载器"
    )

    print(
        "版本：逐文件夹下载 + 逐文件夹 Commit + Push"
    )

    print(
        "=" * 80
    )

    print(
        f"ID：{START_ID} ~ {END_ID}"
    )

    print(
        f"根目录：{ROOT_DIR}"
    )

    print(
        "文件夹并发：1"
    )

    print(
        f"图片并发：{IMAGE_CONCURRENCY}"
    )

    print(
        f"页面重试：{RETRIES}"
    )

    print(
        f"Git Push 重试：{GIT_PUSH_RETRIES}"
    )

    print(
        "=" * 80
    )

    # ========================================================
    # 读取下载记忆
    # ========================================================

    downloaded = load_downloaded()

    print(
        f"已经完成的 ID："
        f"{len(downloaded)}"
    )

    # ========================================================
    # HTTP 连接池
    # ========================================================

    connector = aiohttp.TCPConnector(
        limit=IMAGE_CONCURRENCY,
        limit_per_host=IMAGE_CONCURRENCY,
        ssl=False,
        keepalive_timeout=30
    )

    # ========================================================
    # Session
    # ========================================================

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=PAGE_TIMEOUT,
        headers=BASE_HEADERS
    ) as session:

        # ====================================================
        # 文件夹严格顺序
        # ====================================================

        for album_id in range(
            START_ID,
            END_ID + 1
        ):

            # =================================================
            # 已下载
            # =================================================

            if album_id in downloaded:

                print(
                    f"[{album_id}/{END_ID}] "
                    f"✓ 已下载 → 跳过",
                    flush=True
                )

                continue

            # =================================================
            # 获取页面
            # =================================================

            result = await fetch_page(
                session,
                album_id
            )

            status = result["status"]

            # =================================================
            # 404
            # =================================================

            if status == "404":

                continue

            # =================================================
            # 页面错误
            # =================================================

            if status == "error":

                print(
                    f"[{album_id}/{END_ID}] "
                    f"✗ 页面获取失败，进入下一个",
                    flush=True
                )

                continue

            # =================================================
            # 空页面
            # =================================================

            if status in (
                "no_h1",
                "empty"
            ):

                continue

            # =================================================
            # 下载当前文件夹
            # =================================================

            completed = await download_folder(
                session=session,
                album_id=album_id,
                folder_name=result["folder"],
                images=result["images"]
            )

            # =================================================
            # 下载成功
            # =================================================

            if completed:

                # -------------------------------------------------
                # 写入记忆
                # -------------------------------------------------

                append_downloaded(
                    album_id,
                    result["folder"]
                )

                downloaded.add(
                    album_id
                )

                print()
                print(
                    f"[{album_id}/{END_ID}] "
                    f"✓ 已写入 downloaded.txt",
                    flush=True
                )

                # =================================================
                # 关键：
                #
                # 当前文件夹完成后立即 Commit + Push
                #
                # 不再等 1~20 全部完成
                # =================================================

                git_success = (
                    commit_and_push_folder(
                        album_id,
                        result["folder"]
                    )
                )

                # =================================================
                # Git Push 失败
                #
                # 直接停止。
                #
                # 这样不会继续下载一堆文件，
                # 导致下一次 Push 更大。
                # =================================================

                if not git_success:

                    print()
                    print(
                        "=" * 80
                    )

                    print(
                        f"[{album_id}/{END_ID}] "
                        f"✗ GitHub Push 失败"
                    )

                    print(
                        "为了避免产生大量未提交文件，"
                        "程序停止。"
                    )

                    print(
                        "下一次运行会自动检查已经存在的文件。"
                    )

                    print(
                        "=" * 80
                    )

                    raise RuntimeError(
                        "GitHub Push 失败"
                    )

                # =================================================
                # 当前文件夹 Push 成功
                # =================================================

                print()
                print(
                    "=" * 80
                )

                print(
                    f"[{album_id}/{END_ID}] "
                    f"✓ 完成"
                )

                print(
                    "GitHub 已保存当前文件夹"
                )

                print(
                    "继续下一个 ID..."
                )

                print(
                    "=" * 80
                )

            else:

                print(
                    f"[{album_id}/{END_ID}] "
                    f"⚠ 本文件夹存在失败图片"
                    f"，不会写入完成记录",
                    flush=True
                )

                # 不继续下一个
                # 让下一次 Actions 重新尝试当前 ID

                print(
                    f"[{album_id}/{END_ID}] "
                    f"当前文件夹失败，程序停止。",
                    flush=True
                )

                raise RuntimeError(
                    f"Album {album_id} 下载失败"
                )

    # ========================================================
    # 全部完成
    # ========================================================

    print()
    print(
        "=" * 80
    )

    print(
        "全部扫描完成"
    )

    print(
        f"ID：{START_ID} ~ {END_ID}"
    )

    print(
        f"完成数量：{len(downloaded)}"
    )

    print(
        f"目录：{ROOT_DIR}"
    )

    print(
        "=" * 80
    )


# ============================================================
# Windows / GitHub Actions
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print()
        print(
            "=" * 80
        )

        print(
            "程序被用户中断"
        )

        print(
            "已经完成并 Push 的文件夹不会重复下载。"
        )

        print(
            "=" * 80
        )

    except Exception as e:

        print()
        print(
            "=" * 80
        )

        print(
            f"程序异常停止：{e}"
        )

        print(
            "=" * 80
        )

        raise
