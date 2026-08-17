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
# 基本配置
# ============================================================

BASE_URL = (
    "https://www.xasiat.com/albums/"
    "{}/cosplay-g44-32p-396mb/"
)

# ------------------------------------------------------------
# GitHub Actions 参数
# ------------------------------------------------------------

START_ID = int(
    os.getenv("START_ID", "1")
)

END_ID = int(
    os.getenv("END_ID", "20")
)

IMAGE_CONCURRENCY = int(
    os.getenv("IMAGE_CONCURRENCY", "10")
)

# ------------------------------------------------------------
# 保存目录
# ------------------------------------------------------------

ROOT_DIR = Path(
    os.getenv("ROOT_DIR", "downloads")
)

# ------------------------------------------------------------
# 重试
# ------------------------------------------------------------

DOWNLOAD_RETRIES = 5
PAGE_RETRIES = 5
GIT_PUSH_RETRIES = 5

GIT_PUSH_WAIT = 20


# ============================================================
# HTTP 超时
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
# 文件
# ============================================================

DOWNLOADED_FILE = (
    ROOT_DIR / "downloaded.txt"
)

COMPLETE_FILE = ".complete"


# ============================================================
# HTTP Headers
# ============================================================

BASE_HEADERS = {

    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36",

    "Accept-Language":
        "zh-CN,zh;q=0.9,en;q=0.8",

    "Connection":
        "keep-alive",
}


# ============================================================
# 安全文件名
# ============================================================

def safe_filename(name):

    name = re.sub(
        r'[<>:"/\\|?*]',
        "_",
        name
    )

    name = name.strip()

    name = name.rstrip(
        " ."
    )

    return name


# ============================================================
# 从 data-original 获取文件名
# ============================================================

def get_filename_from_original(
    data_original
):

    if not data_original:

        return None

    clean_url = (
        data_original
        .split("?", 1)[0]
        .rstrip("/")
    )

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
# 读取 downloaded.txt
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

                album_id = (
                    line
                    .split("|", 1)[0]
                    .strip()
                )

                if album_id.isdigit():

                    downloaded.add(
                        int(album_id)
                    )

    except Exception as e:

        print(
            f"[警告] 读取 downloaded.txt 失败：{e}",
            flush=True
        )

    return downloaded


# ============================================================
# 写入 downloaded.txt
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

def run_git(
    args,
    check=True
):

    command = [
        "git"
    ] + args

    print(
        "[GIT]",
        " ".join(command),
        flush=True
    )

    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    if result.stdout:

        print(
            result.stdout,
            flush=True
        )

    if (
        check
        and result.returncode != 0
    ):

        raise RuntimeError(
            "Git 命令失败："
            + " ".join(command)
        )

    return result


# ============================================================
# 获取当前 GitHub 分支
# ============================================================

def get_git_branch():

    # --------------------------------------------------------
    # GitHub Actions
    # --------------------------------------------------------

    branch = os.getenv(
        "GITHUB_REF_NAME"
    )

    if branch:

        return branch

    # --------------------------------------------------------
    # 本地运行
    # --------------------------------------------------------

    result = subprocess.run(
        [
            "git",
            "branch",
            "--show-current"
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    branch = (
        result.stdout
        .strip()
    )

    if branch:

        return branch

    return "main"


# ============================================================
# Git Push
# ============================================================

def git_push_with_retry():

    branch = get_git_branch()

    print()
    print(
        "=" * 70
    )

    print(
        f"[GIT] 当前分支：{branch}",
        flush=True
    )

    print(
        "=" * 70
    )

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

        try:

            # =================================================
            # 获取远程最新状态
            # =================================================

            fetch = subprocess.run(
                [
                    "git",
                    "fetch",
                    "origin",
                    branch
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT
            )

            if fetch.stdout:

                print(
                    fetch.stdout,
                    flush=True
                )

            if fetch.returncode != 0:

                raise RuntimeError(
                    "git fetch 失败"
                )

            # =================================================
            # 获取本地 HEAD
            # =================================================

            local = subprocess.run(
                [
                    "git",
                    "rev-parse",
                    "HEAD"
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT
            )

            local_hash = (
                local.stdout.strip()
            )

            # =================================================
            # 获取远程 HEAD
            # =================================================

            remote = subprocess.run(
                [
                    "git",
                    "rev-parse",
                    f"origin/{branch}"
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT
            )

            remote_hash = (
                remote.stdout.strip()
            )

            print(
                f"[GIT] 本地：{local_hash}",
                flush=True
            )

            print(
                f"[GIT] 远程：{remote_hash}",
                flush=True
            )

            # =================================================
            # 判断是否需要 rebase
            # =================================================

            if (
                local_hash
                != remote_hash
            ):

                print(
                    "[GIT] 远程存在新提交",
                    flush=True
                )

                print(
                    "[GIT] 正在执行 rebase...",
                    flush=True
                )

                rebase = subprocess.run(
                    [
                        "git",
                        "rebase",
                        f"origin/{branch}"
                    ],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT
                )

                if rebase.stdout:

                    print(
                        rebase.stdout,
                        flush=True
                    )

                if rebase.returncode != 0:

                    print(
                        "[GIT] rebase 失败",
                        flush=True
                    )

                    subprocess.run(
                        [
                            "git",
                            "rebase",
                            "--abort"
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT
                    )

                    raise RuntimeError(
                        "Git rebase 失败"
                    )

            # =================================================
            # Push
            #
            # 注意：
            # 这里必须使用 Python 拼接 branch。
            #
            # 不能写：
            #
            # HEAD:${GITHUB_REF_NAME}
            #
            # 因为 subprocess 不会展开变量。
            # =================================================

            push = subprocess.run(
                [
                    "git",
                    "push",
                    "origin",
                    f"HEAD:{branch}"
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT
            )

            if push.stdout:

                print(
                    push.stdout,
                    flush=True
                )

            if push.returncode == 0:

                print(
                    "[GIT] ✓ Push 成功",
                    flush=True
                )

                return True

            print(
                f"[GIT] ✗ Push 失败 "
                f"退出码：{push.returncode}",
                flush=True
            )

        except Exception as e:

            print(
                f"[GIT] Push 错误：{e}",
                flush=True
            )

        # =====================================================
        # Retry
        # =====================================================

        if attempt < GIT_PUSH_RETRIES:

            print(
                f"[GIT] {GIT_PUSH_WAIT} 秒后重试...",
                flush=True
            )

            time.sleep(
                GIT_PUSH_WAIT
            )

    print(
        "[GIT] ✗ Push 连续失败",
        flush=True
    )

    return False


# ============================================================
# Commit + Push
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
        f"准备提交 GitHub",
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

        folder_path = (
            ROOT_DIR /
            folder_name
        )

        # =================================================
        # Git Add
        # =================================================

        run_git(
            [
                "add",
                "--",
                str(folder_path),
                str(DOWNLOADED_FILE)
            ]
        )

        # =================================================
        # 检查暂存区
        # =================================================

        result = run_git(
            [
                "diff",
                "--cached",
                "--quiet"
            ],
            check=False
        )

        if result.returncode == 0:

            print(
                "[GIT] 没有新的内容需要提交",
                flush=True
            )

            return True

        # =================================================
        # Commit
        # =================================================

        commit_message = (
            f"Download album {album_id}: "
            f"{folder_name}"
        )

        run_git(
            [
                "commit",
                "-m",
                commit_message
            ]
        )

        # =================================================
        # Push
        # =================================================

        if not git_push_with_retry():

            return False

        print(
            f"[{album_id}/{END_ID}] "
            f"✓ Commit + Push 完成",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"[GIT] Commit/Push 失败：{e}",
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

    h1 = soup.find(
        "h1"
    )

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
    # 图片容器
    # ========================================================

    images_container = (
        soup.select_one(
            ".images"
        )
    )

    if not images_container:

        return folder_name, []

    image_list = []

    # ========================================================
    # 找图片
    # ========================================================

    for a in images_container.find_all(
        "a",
        href=True
    ):

        href = (
            a["href"]
            .strip()
        )

        if not is_image_url(
            href
        ):

            continue

        img = a.find(
            "img"
        )

        if not img:

            continue

        data_original = (
            img.get(
                "data-original",
                ""
            )
            .strip()
        )

        if not data_original:

            continue

        filename = (
            get_filename_from_original(
                data_original
            )
        )

        if not filename:

            continue

        image_url = urljoin(
            page_url,
            href
        )

        # ----------------------------------------------------
        # 去重
        # ----------------------------------------------------

        if any(
            item["filename"]
            == filename
            for item in image_list
        ):

            continue

        image_list.append(
            {
                "url": image_url,
                "filename": filename
            }
        )

    return (
        folder_name,
        image_list
    )


# ============================================================
# 获取网页
# ============================================================

async def fetch_page(
    session,
    album_id
):

    page_url = (
        BASE_URL.format(
            album_id
        )
    )

    print()
    print(
        f"[{album_id}/{END_ID}] "
        f"正在获取页面...",
        flush=True
    )

    for attempt in range(
        1,
        PAGE_RETRIES + 1
    ):

        try:

            headers = {
                **BASE_HEADERS,

                "Referer":
                    "https://www.xasiat.com/"
            }

            async with session.get(
                page_url,
                headers=headers,
                timeout=PAGE_TIMEOUT
            ) as response:

                # =============================================
                # 404
                # =============================================

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

                # =============================================
                # HTTP 错误
                # =============================================

                if response.status != 200:

                    raise RuntimeError(
                        f"HTTP {response.status}"
                    )

                html = await response.text(
                    errors="ignore"
                )

            # =================================================
            # 解析
            # =================================================

            folder_name, images = (
                parse_page(
                    html,
                    page_url
                )
            )

            # =================================================
            # H1 不存在
            # =================================================

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

            # =================================================
            # 没有图片
            # =================================================

            if not images:

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

            # =================================================
            # 成功
            # =================================================

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
                f"({attempt}/{PAGE_RETRIES})：{e}",
                flush=True
            )

            if attempt < PAGE_RETRIES:

                await asyncio.sleep(
                    1.5 * attempt
                )

    return {
        "status": "error",
        "folder": None,
        "images": []
    }


# ============================================================
# 下载单张图片
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
    # 并发限制
    # ========================================================

    async with semaphore:

        for attempt in range(
            1,
            DOWNLOAD_RETRIES + 1
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
                # 请求
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

                            f.write(
                                chunk
                            )

                # =================================================
                # 检查
                # =================================================

                if (
                    not temp_file.exists()
                    or temp_file.stat().st_size == 0
                ):

                    raise RuntimeError(
                        "下载文件为空"
                    )

                # =================================================
                # 原子替换
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

                if attempt < DOWNLOAD_RETRIES:

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
# 下载整个文件夹
#
# 文件夹之间：
#   严格串行
#
# 文件夹内部：
#   图片并发
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

    total = len(
        images
    )

    print()
    print(
        "=" * 70
    )

    print(
        f"[{album_id}/{END_ID}] "
        f"开始下载文件夹"
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

    print()
    print(
        f"[{album_id}/{END_ID}] "
        f"下载统计："
    )

    print(
        f"成功：{success}"
    )

    print(
        f"已存在：{skipped}"
    )

    print(
        f"失败：{failed}"
    )

    # ========================================================
    # 所有图片成功
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
                )

                f.write(
                    f"folder={folder_name}\n"
                )

                f.write(
                    f"images={total}\n"
                )

                f.write(
                    f"success={success}\n"
                )

                f.write(
                    f"skipped={skipped}\n"
                )

        except Exception as e:

            print(
                f"[警告] 创建 .complete 失败：{e}",
                flush=True
            )

        print(
            f"[{album_id}/{END_ID}] "
            f"✓ 文件夹下载完成",
            flush=True
        )

        return True

    # ========================================================
    # 有图片失败
    # ========================================================

    print(
        f"[{album_id}/{END_ID}] "
        f"✗ 文件夹下载失败",
        flush=True
    )

    return False


# ============================================================
# 主程序
# ============================================================

async def main():

    # ========================================================
    # 创建目录
    # ========================================================

    ROOT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # ========================================================
    # 基本信息
    # ========================================================

    branch = get_git_branch()

    print()
    print(
        "=" * 80
    )

    print(
        "XAsiaT GitHub Actions Downloader"
    )

    print(
        "=" * 80
    )

    print(
        f"ID 范围：{START_ID} ~ {END_ID}"
    )

    print(
        f"下载目录：{ROOT_DIR}"
    )

    print(
        f"图片并发：{IMAGE_CONCURRENCY}"
    )

    print(
        f"Git 分支：{branch}"
    )

    print(
        "=" * 80
    )

    # ========================================================
    # 读取已完成 ID
    # ========================================================

    downloaded = load_downloaded()

    print(
        f"已完成 ID 数量："
        f"{len(downloaded)}"
    )

    # ========================================================
    # HTTP 连接器
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
        # ID 严格顺序
        # ====================================================

        for album_id in range(
            START_ID,
            END_ID + 1
        ):

            print()
            print(
                "#" * 80
            )

            print(
                f"处理 ID："
                f"{album_id}/{END_ID}"
            )

            print(
                "#" * 80
            )

            # =================================================
            # 已完成
            # =================================================

            if album_id in downloaded:

                print(
                    f"[{album_id}/{END_ID}] "
                    f"✓ downloaded.txt 已记录"
                    f" → 跳过",
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

            status = result[
                "status"
            ]

            # =================================================
            # 404
            # =================================================

            if status == "404":

                print(
                    f"[{album_id}/{END_ID}] "
                    f"页面不存在，跳过",
                    flush=True
                )

                continue

            # =================================================
            # 页面错误
            # =================================================

            if status == "error":

                raise RuntimeError(
                    f"Album {album_id} "
                    f"页面获取失败"
                )

            # =================================================
            # 没有 H1
            # =================================================

            if status == "no_h1":

                print(
                    f"[{album_id}/{END_ID}] "
                    f"页面没有 H1，跳过",
                    flush=True
                )

                continue

            # =================================================
            # 没有图片
            # =================================================

            if status == "empty":

                print(
                    f"[{album_id}/{END_ID}] "
                    f"没有图片，跳过",
                    flush=True
                )

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
            # 下载失败
            # =================================================

            if not completed:

                print()
                print(
                    "=" * 80
                )

                print(
                    f"[{album_id}/{END_ID}] "
                    f"✗ 当前文件夹失败"
                )

                print(
                    "不会写入 downloaded.txt"
                )

                print(
                    "程序停止，下一次运行会继续当前 ID"
                )

                print(
                    "=" * 80
                )

                raise RuntimeError(
                    f"Album {album_id} "
                    f"download failed"
                )

            # =================================================
            # 下载成功
            # =================================================

            append_downloaded(
                album_id,
                result["folder"]
            )

            downloaded.add(
                album_id
            )

            print(
                f"[{album_id}/{END_ID}] "
                f"✓ 写入 downloaded.txt",
                flush=True
            )

            # =================================================
            # 立即 Commit + Push
            # =================================================

            git_success = (
                commit_and_push_folder(
                    album_id,
                    result["folder"]
                )
            )

            # =================================================
            # Push 失败
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
                    "为了防止继续产生大量未提交文件，"
                    "程序停止。"
                )

                print(
                    "下一次运行会自动跳过已经下载的图片。"
                )

                print(
                    "=" * 80
                )

                raise RuntimeError(
                    "GitHub Push 失败"
                )

            # =================================================
            # 当前 ID 完成
            # =================================================

            print()
            print(
                "=" * 80
            )

            print(
                f"[{album_id}/{END_ID}] "
                f"✓ 全部完成"
            )

            print(
                "✓ 图片下载完成"
            )

            print(
                "✓ .complete 已生成"
            )

            print(
                "✓ downloaded.txt 已更新"
            )

            print(
                "✓ Git commit 已完成"
            )

            print(
                "✓ Git push 已完成"
            )

            print(
                "=" * 80
            )

    # ========================================================
    # 全部完成
    # ========================================================

    print()
    print(
        "=" * 80
    )

    print(
        "🎉 全部任务完成"
    )

    print(
        f"ID：{START_ID} ~ {END_ID}"
    )

    print(
        f"已完成数量：{len(downloaded)}"
    )

    print(
        "=" * 80
    )


# ============================================================
# 程序入口
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
            "程序被中断"
        )

        print(
            "=" * 80
        )

        raise

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
