import asyncio
import json
import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from loguru import logger
from crawl4ai.docker_client import Crawl4aiDockerClient
from crawl4ai import (
    BrowserConfig,
    CrawlerRunConfig
)
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# 配置 loguru 日志
logger.remove()  # 移除默认处理器
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)
# 同时保存到文件
logger.add(
    "hawh_spider.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="10 MB"
)


class HAWHMediaSpider:
    """HAWH媒体爬虫 - 爬取音视频节目信息和媒体链接"""

    def __init__(self, docker_url: str = "http://172.17.13.16:11235"):
        self.docker_url = docker_url
        self.base_url = "http://www.hawh.cn/hawh/audioVisual/index.html"
        self.all_programs = []
        self.all_categories = []
        self.output_dir = Path("hawh_data")
        self.output_dir.mkdir(exist_ok=True)

    async def crawl(self, url: str, wait_for: Optional[str] = None):
        """使用crawl4ai Docker客户端爬取页面内容"""
        async with Crawl4aiDockerClient(base_url=self.docker_url, verbose=False) as client:
            crawler_config = CrawlerRunConfig(
                exclude_external_links=False,
                remove_overlay_elements=False,
                excluded_tags=['form', 'header', 'footer', 'nav', 'aside'],
                excluded_selector='#mozi-assist, #main > section.main__body.article.main__body__article-wrap > div > div > div > article > div.common-component-content-share-box.share-component.social-share '                )
            browser_config = BrowserConfig(headless=True)

            try:
                results = await client.crawl(
                    [url],
                    browser_config=browser_config,
                    crawler_config=crawler_config
                )
                return results
            except Exception as e:
                logger.error(f"爬取 {url} 失败: {e}")
                return ""

    def extract_categories_from_internal(self, internal_links: []) -> List[str]:
        """从内部链接中提取栏目分类信息 - 只提取包含 index 的链接"""
        seen_urls = set()

        for item in internal_links:
            try:
                item_url = item.get('href', '')
                item_text = item.get('title', '')

                # 过滤条件：URL要以audioVisual开头且以index.html结尾
                if (item_url.startswith('http://www.hawh.cn/hawh/audioVisual') and
                    item_url.endswith('index.html') and
                    item_url != self.base_url and
                    item_url not in seen_urls):

                    seen_urls.add(item_url)

            except Exception as e:
                logger.error(f"提取栏目分类出错: {e}")
                continue

        return seen_urls


    async def scrape_categories(self):
        """爬取所有栏目 - 从主页面提取所有带index的栏目链接"""
        logger.info("开始爬取栏目信息...")

        # 从主页面爬取
        index_url = self.base_url
        results = await self.crawl(index_url, wait_for="a[href*='index']")

        self.all_categories = self.extract_categories_from_internal(results.links.get('internal', []))
        logger.info(f"发现 {len(self.all_categories)} 个栏目")

        return self.all_categories


    def _extract_bg_image(self, element, base_url, default_base):
        """
        内部辅助函数：从元素的 style 属性中提取 background-image url
        """
        image_url = ""
        # 查找包含背景图样式的 div
        img_div = element.select_one('.aspect-ratio-content')
        
        if img_div and img_div.has_attr('style'):
            style_content = img_div['style']
            # 正则匹配 url('...') 或 url("...") 或 url(...)
            match = re.search(r"url\(['\"]?(.*?)['\"]?\)", style_content)
            if match:
                raw_img_url = match.group(1)
                image_url = urljoin(base_url if base_url else default_base, raw_img_url)
        
        # 兜底：如果没找到背景图，找找普通 img 标签
        if not image_url:
            img_tag = element.select_one('img')
            if img_tag and img_tag.get('src'):
                image_url = urljoin(base_url if base_url else default_base, img_tag.get('src'))
        
        return image_url

    def extract_programs_from_html(self, html_content: str, base_url: str) -> List[Dict[str, Any]]:
        """
        解析 HTML 提取视频标题、链接和图片（兼容 网格模式 和 列表模式）
        """
        programs = []
        default_base = "http://www.hawh.cn"
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            target = soup.find('li', attrs={'aria-current': 'page'})
            if target:
                print(target.get_text(strip=True)) 
            #main > section.head__diagram.aspect-ratio.wow.animate__fadeIn.animate__animated > div > div > nav > ol

            # ==================================================
            # 模式 A: 网格布局 (Block Style)
            # 结构: <li class="article__block__item"> <a class="article__link"> ... </a> </li>
            # ==================================================
            block_items = soup.select('li.article__block__item')
            for item in block_items:
                link_tag = item.select_one('a.article__link')
                if not link_tag:
                    continue
                
                href = link_tag.get('href')
                title = link_tag.get('title')
                if not title:
                    # 尝试从内部文本获取
                    title_tag = link_tag.select_one('.article__block__title')
                    if title_tag:
                        title = title_tag.get_text(strip=True)

                if href and title:
                    full_url = urljoin(base_url if base_url else default_base, href)
                    img_url = self._extract_bg_image(link_tag, base_url, default_base)
                    
                    programs.append({
                        "title": title,
                        "url": full_url,
                        "image": img_url,
                        'category': target.get_text(strip=True) if target else '',
                    })

            # ==================================================
            # 模式 B: 列表布局 (Thumbnail/List Style)
            # 结构: <a class="article__thumbnail__link"> ... </a> (A标签本身就是容器)
            # ==================================================
            list_items = soup.select('a.article__thumbnail__link')
            for link_tag in list_items:
                href = link_tag.get('href')
                
                # 标题可能在 title 属性，也可能在 h3 标签里
                title = link_tag.get('title')
                if not title:
                    title_tag = link_tag.select_one('.article__thumbnail__title')
                    if title_tag:
                        title = title_tag.get_text(strip=True)

                if href and title:
                    full_url = urljoin(base_url if base_url else default_base, href)
                    img_url = self._extract_bg_image(link_tag, base_url, default_base)

                    programs.append({
                        "title": title,
                        "url": full_url,
                        "image": img_url
                    })

        except Exception as e:
            logger.error(f"解析 HTML 提取节目时出错: {e}")
            
        return programs

    async def scrape_programs_for_category(self, category_url: str) -> List[Dict[str, Any]]:
        """
        爬取某个栏目下的所有节目（自动识别分页、兼容两种布局）
        """
        logger.info(f"开始爬取栏目: {category_url}")
        all_programs = []

        # CSS 选择器：等待 "网格项" OR "列表项" 任意一个出现即视为加载成功
        wait_selector = ".article__block__item, .article__thumbnail__link"

        try:
            # --- 1. 爬取第一页 ---
            results = await self.crawl(category_url, wait_for=wait_selector)
            first_page_html = results.html
            
            # 解析数据
            current_programs = self.extract_programs_from_html(first_page_html, category_url)
            all_programs.extend(current_programs)
            logger.info(f"第 1 页抓取完成，找到 {len(current_programs)} 个节目")

            # --- 2. 探测总页数 ---
            soup = BeautifulSoup(first_page_html, 'html.parser')
            pagination_input = soup.select_one('input.common-component-pagination-input[name="pageIndex"]')
            
            total_pages = 1
            if pagination_input and pagination_input.has_attr('max'):
                try:
                    total_pages = int(pagination_input['max'])
                    logger.info(f"检测到分页组件，最大页数为: {total_pages}")
                except ValueError:
                    pass
            
            # --- 3. 循环爬取剩余页面 ---
            if total_pages > 1:
                for page_num in range(2, total_pages + 1):
                    separator = "&" if "?" in category_url else "?"
                    page_url = f"{category_url}{separator}pageIndex={page_num}"
                    
                    logger.info(f"正在爬取第 {page_num}/{total_pages} 页: {page_url}")
                    
                    try:
                        page_results = await self.crawl(page_url, wait_for=wait_selector)
                        new_programs = self.extract_programs_from_html(page_results.html, category_url)
                        all_programs.extend(new_programs)
                        
                    except Exception as e:
                        logger.error(f"爬取第 {page_num} 页失败: {e}")

        except Exception as e:
            logger.error(f"爬取栏目失败: {e}")

        logger.info(f"栏目爬取结束，总共发现 {len(all_programs)} 个节目")
        return all_programs

    async def scrape_program_details(self, program: Dict[str, Any]) -> Dict[str, Any]:
        """爬取节目详情和媒体链接"""
        html_content = await self.crawl(program['url'], wait_for="video,audio,[data-video],[data-audio]")

        program['media_urls'] = ''
        program['publish_time'] = ''

        # 提取媒体链接
        if len(html_content.media['videos']) > 0:
            for video_info in html_content.media['videos']:
                if video_info.get('src'):
                    program['media_urls'] = video_info.get('src')
                    break

        for line in html_content.markdown.split('\n'):
            if "发布时间" in line:
                publish_time = line.replace("发布时间：", "").strip()
                program['publish_time'] = publish_time
                break

        return program

    async def run(self):
        """执行完整的爬取流程"""
        logger.info("=" * 60)
        logger.info("🚀 HAWH媒体爬虫启动")
        logger.info("=" * 60)

        try:
            # 1. 爬取栏目
            categories = await self.scrape_categories()
            if not categories:
                logger.error("未能获取栏目信息")
                return

            # 2. 爬取每个栏目的节目
            logger.info("=" * 60)
            logger.info(f"📺 开始爬取 {len(categories)} 个栏目的节目")
            logger.info("=" * 60)

            for idx, category_url in enumerate(categories, 1):
                logger.info(f"[{idx}/{len(categories)}]")
                programs = await self.scrape_programs_for_category(category_url)
                self.all_programs.extend(programs)

            # 3. 爬取节目详情和媒体链接（限制前10个节目）
            if self.all_programs:
                logger.info("=" * 60)
                logger.info("🎬 正在获取节目详情和媒体链接")
                logger.info("=" * 60)

                limit = min(10, len(self.all_programs))
                for i, program in enumerate(self.all_programs[:limit], 1):
                    # title_display = program['title'][:40] + "..." if len(program['title']) > 40 else program['title']
                    # logger.info(f"[{i}/{limit}] {title_display}")
                    await self.scrape_program_details(program)

            # 4. 保存数据
            await self.save_data()

            logger.info("=" * 60)
            logger.info("✨ 爬取完成！")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"爬取过程出错: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def save_data(self):
        """保存爬取的数据"""
        logger.info(f"💾 保存数据到 {self.output_dir}/")


        # 保存节目信息
        programs_file = self.output_dir / "programs.json"
        with open(programs_file, 'w', encoding='utf-8') as f:
            json.dump(self.all_programs, f, ensure_ascii=False, indent=2)
        logger.info(f"节目信息: {programs_file} ({len(self.all_programs)} 条)")

        # 保存媒体链接
        media_links_file = self.output_dir / "media_links.json"
        media_data = [
            {
                'program_title': p['title'],
                'category': p['category'],
                'program_url': p['url'],
                'media_urls': p.get('media_urls', []),
                'media_count': p.get('media_count', 0)
            }
            for p in self.all_programs if p.get('media_urls')
        ]
        with open(media_links_file, 'w', encoding='utf-8') as f:
            json.dump(media_data, f, ensure_ascii=False, indent=2)
        logger.info(f"媒体链接: {media_links_file} ({len(media_data)} 条)")

        # 保存CSV格式（用于表格查看）
        csv_file = self.output_dir / "programs_summary.csv"
        if self.all_programs:
            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['栏目', '节目标题', '节目链接', '媒体数量', '爬取时间'])
                for p in self.all_programs:
                    writer.writerow([
                        p.get('category', ''),
                        p.get('title', ''),
                        p.get('url', ''),
                        p.get('media_count', 0),
                        p.get('crawler_time', '')
                    ])
            logger.info(f"汇总表格: {csv_file}")


async def main():
    """主函数"""
    spider = HAWHMediaSpider(docker_url="http://172.17.13.16:11235")
    await spider.run()


if __name__ == "__main__":
    asyncio.run(main())