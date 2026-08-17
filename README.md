# GitHub Actions 图片下载测试项目

这个项目把原来的 Windows 本地下载程序改成了 GitHub Actions 版本。

## 第一次测试

默认配置：

- ID：`1 ~ 20`
- 图片保存目录：`downloads/`
- 文件夹之间：严格串行
- 同一个文件夹内部：默认 10 张图片并发
- 下载完成后自动 `git add / commit / push`
- `downloaded.txt` 用于记录已经完成的 album ID
- 每个完成的文件夹会创建 `.complete`

## 部署

1. 新建一个 GitHub Repository。
2. 把本项目全部文件上传到仓库。
3. 进入仓库：
   `Settings -> Actions -> General`
4. 找到 `Workflow permissions`，确认允许 GitHub Actions 写入仓库。
   本项目的 workflow 已经声明：

   `permissions: contents: write`

5. 打开：
   `Actions -> Download albums and commit to repository`
6. 点击 `Run workflow`。
7. 第一次直接使用默认值：
   - start_id = `1`
   - end_id = `20`
   - image_concurrency = `10`

运行结束后，下载的文件会出现在仓库的 `downloads/` 目录。

## 下一次扩大范围

例如测试成功后，可以运行：

- `21 ~ 40`
- `41 ~ 60`

也可以直接改成更大的范围。

## 注意

GitHub 仓库和 Actions 都不适合无限量保存大量二进制图片。图片很多时，仓库会快速膨胀，后续可能碰到 GitHub 的仓库大小、单文件大小、Actions 时间或存储限制。

建议先用 `1 ~ 20` 验证：

1. 页面能否正常访问；
2. 图片能否正常下载；
3. 文件夹和文件名是否正确；
4. Actions 是否能成功 commit/push。

确认没有问题后，再决定是否继续扩大范围。

本项目只实现下载、保存和 GitHub Actions 自动提交；请确保你对目标网站内容的下载和再分发拥有相应权限，并遵守目标网站的 robots、服务条款和适用法律。
