# HAWH媒体爬虫 (HAWH Media Spider)

一个使用 crawl4ai Docker客户端 的高效网络爬虫，用于爬取HAWH音视频节目平台的栏目、节目和媒体链接信息。

## 功能特性

✅ **智能栏目识别** - 只爬取带 `index` 的链接作为栏目
✅ **递归节目爬取** - 进入每个栏目后获取具体的节目列表
✅ **媒体链接提取** - 识别视频、音频、直播流等媒体文件链接
✅ **多格式数据导出** - 支持 JSON 和 CSV 格式
✅ **容错处理** - 完善的错误处理和重试机制

## 文件结构

```
hawh_media_sp.py          # 主爬虫脚本
README.md                 # 使用说明（本文件）

运行后生成：
hawh_data/
├── categories.json       # 栏目信息列表
├── programs.json         # 所有节目详细信息
├── media_links.json      # 媒体链接数据
└── programs_summary.csv  # CSV格式的数据汇总
```

## 使用方法

### 前置条件

1. 确保 crawl4ai Docker 服务正在运行
2. Docker 服务地址配置在代码中（默认: `http://172.17.13.16:11235`）

### 运行爬虫

```bash
# 使用 uv 运行
uv run hawh_media_sp.py

# 或者直接用 Python 运行（需要安装依赖）
python hawh_media_sp.py
```

## 爬虫工作流程

```
1️⃣ 爬取主页面
   └─ 提取所有带 index 的链接作为栏目

2️⃣ 遍历每个栏目
   └─ 进入栏目页面 (index.html)
   └─ 提取栏目下的所有节目链接
      （排除 index 链接，避免递归）

3️⃣ 处理每个节目 (限制前10个)
   └─ 爬取节目详情页面
   └─ 提取媒体文件链接
      - mp4, m3u8, flv, webm 等视频格式
      - mp3, wav, ogg 等音频格式

4️⃣ 数据保存
   └─ 生成 categories.json (栏目)
   └─ 生成 programs.json (节目)
   └─ 生成 media_links.json (媒体链接)
   └─ 生成 programs_summary.csv (汇总表格)
```

## 类和方法说明

### HAWHMediaSpider 类

#### 核心方法

- **`async crawl(url, wait_for=None)`**
  - 使用 crawl4ai Docker客户端爬取页面
  - `wait_for` - 等待特定 CSS 选择器元素加载

- **`extract_categories_from_html(html_content)`**
  - 从HTML中提取栏目分类（只提取包含 index 的链接）
  - 返回栏目列表

- **`extract_programs_from_html(html_content, category_name)`**
  - 从HTML中提取节目信息（排除 index 链接）
  - 返回节目列表

- **`extract_media_urls(html_content)`**
  - 从HTML中提取媒体文件链接
  - 支持多种媒体格式（mp4, m3u8, flv, mp3等）

#### 爬取方法

- **`async scrape_categories()`** - 爬取所有栏目
- **`async scrape_programs_for_category(category)`** - 爯取栏目下的节目
- **`async scrape_program_details(program)`** - 爬取节目详情和媒体链接
- **`async run()`** - 执行完整的爬取流程
- **`async save_data()`** - 保存爬取的数据

## 数据格式

### categories.json
```json
[
  {
    "name": "栏目名称",
    "url": "http://www.hawh.cn/hawh/audioVisual/category/index.html",
    "crawler_time": "2024-12-17T11:30:45.123456"
  }
]
```

### programs.json
```json
[
  {
    "title": "节目标题",
    "url": "http://www.hawh.cn/hawh/audioVisual/detail/xxx",
    "category": "所属栏目",
    "crawler_time": "2024-12-17T11:30:45.123456",
    "media_urls": [
      "https://media.example.com/video.mp4",
      "https://media.example.com/stream.m3u8"
    ],
    "media_count": 2
  }
]
```

### media_links.json
```json
[
  {
    "program_title": "节目标题",
    "category": "栏目名称",
    "program_url": "http://www.hawh.cn/...",
    "media_urls": ["url1", "url2"],
    "media_count": 2
  }
]
```

### programs_summary.csv
```
栏目,节目标题,节目链接,媒体数量,爬取时间
栏目1,节目1,http://...,2,2024-12-17T11:30:45
栏目1,节目2,http://...,1,2024-12-17T11:30:50
```

## 配置选项

在 `HAWHMediaSpider.__init__()` 中可配置：

```python
spider = HAWHMediaSpider(
    docker_url="http://172.17.13.16:11235"  # Docker服务地址
)
```

在 `spider.run()` 中可配置爬取数量：

```python
# 栏目限制（第173行）
for category in categories[:5]:  # 爬取前5个栏目

# 节目详情限制（第212行）
for i, program in enumerate(self.all_programs[:10]):  # 处理前10个节目
```

## 关键特性

### 1. 栏目识别
- ✅ 只提取包含 `index` 的链接
- ✅ 自动去重
- ✅ 清理无效链接

### 2. 节目提取
- ✅ 排除 `index` 链接（避免循环）
- ✅ 排除 `javascript:` 伪协议
- ✅ 排除 `#` 锚点链接
- ✅ 自动URL规范化

### 3. 媒体识别
支持以下媒体格式：
- 视频: `mp4`, `m3u8`, `flv`, `webm`
- 音频: `mp3`, `wav`, `ogg`

### 4. 数据导出
- ✅ JSON 格式（完整数据）
- ✅ CSV 格式（表格查看）
- ✅ 字符编码处理（UTF-8）

## 错误处理

- 网络请求失败时自动捕获并报告
- 继续处理其他条目，不中断整体流程
- 完整的异常堆栈追踪用于调试

## 性能考虑

- 当前限制爬取前5个栏目和前10个节目（演示用）
- 可根据需要调整限制参数
- 使用 `wait_for` 机制等待动态加载完成
- 支持异步并发处理

## 常见问题

**Q: 如何修改爬取的栏目数量？**
A: 修改 `run()` 方法第192行的 `categories[:5]` 参数

**Q: 如何修改爬取的节目数量？**
A: 修改 `run()` 方法第212行的 `self.all_programs[:10]` 参数

**Q: 如何修改 Docker 服务地址？**
A: 修改 `main()` 函数中的 `docker_url` 参数

**Q: 爬虫卡住了怎么办？**
A: 检查 Docker 服务是否正常运行，网络连接是否正常

## 注意事项

⚠️ 遵守网站的 `robots.txt` 和爬虫协议
⚠️ 合理设置爬虫速度，避免对服务器造成压力
⚠️ 爬取内容仅供个人学习使用

## License

MIT License - 自由使用和修改
