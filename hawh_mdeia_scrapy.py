import scrapy
from scrapy.crawler import CrawlerProcess

from urllib.parse import urlparse, parse_qs
import re
# from crawlab import save_item

# ==========================================
# 1. 定义 Pipeline (数据处理逻辑)
# ==========================================
class MyCustomPipeline:

    def process_item(self, item, spider):
        # 【在这里写存入 MySQL / MongoDB 的代码】
        
        # 示例：写入 JSONL 文件
        # save_item(item)  # 使用 Crawlab 提供的保存方法
        # 打印日志证明 Pipeline 在工作
        print(f">>> Pipeline ============捕获数据: {item['page_url']}")
        print(f">>> Pipeline 捕获数据: {item['cover_image']}")
        return item
    
# ==========================================
# 2. 定义 Spider (爬虫逻辑)
# ==========================================    
class HawhFinalSpider(scrapy.Spider):
    name = 'hawh_universal'
    allowed_domains = ['hawh.cn']
    # 入口URL，可以根据需要修改
    start_urls = ['http://www.hawh.cn/hawh/audioVisual/index.html']

    def parse(self, response):
        """ 第一层：首页入口 """
        self.logger.info(f"正在解析首页: {response.url}")
        
        # 1. 提取所有板块入口 (列表页)
        # 匹配所有可能的“更多”按钮
        entry_links = response.css('a.link__btn::attr(href), a.category__link::attr(href), a.art__link::attr(href), a.old__movies__link::attr(href)').getall()
        for link in entry_links:
            yield response.follow(link, callback=self.parse_list)

        # 2. 提取首页直接展示的文章 (详情页)
        direct_articles = response.css('a.article__link::attr(href), a.swiper__link::attr(href), a.cultural__category__link::attr(href)').getall()
        for link in direct_articles:
            yield response.follow(link, callback=self.parse_detail)

    def parse_list(self, response):
        """ 第二层：列表页 """
        self.logger.info(f"正在解析列表页: {response.url}")
        
        # ==========================================================
        # 1. 提取文章 (兼容多种布局)
        # ==========================================================
        
        # 策略：不依赖具体的 item class (因为有 wow animate... 等干扰)
        # 直接寻找所有包含 "article__" 类名的链接，或者是列表项中的链接
        
        # 查找所有可能的容器节点
        # 使用 contains 模糊匹配，防止因为多了 wow animate 类导致匹配失败
        link_nodes = response.css('a.article__thumbnail__link, a.article__block__link')
        
        self.logger.info(f"提取到 {len(link_nodes)} 个文章链接节点")

        
        for node in link_nodes:
            # A. 提取链接 (href 就在当前 a 标签上)
            link = node.attrib.get('href')
            if not link:
                continue

            # B. 提取图片
            # 图片 div (aspect-ratio-content) 是 a 标签的子元素
            # HTML: <a ...> ... <div style="background-image: url('...')"> ... </a>
            
            cover_img = None
            
            # 1. 尝试从 style 提取背景图
            style_text = node.css('.aspect-ratio-content::attr(style)').get()
            if style_text:
                import re
                match = re.search(r"url\s*\(\s*['\"]?(.*?)['\"]?\s*\)", style_text)
                if match:
                    cover_img = match.group(1)
            
            # 2. 备用: 尝试 img 标签
            if not cover_img:
                cover_img = node.css('img::attr(src)').get()
            
            # 3. 补全绝对路径
            if cover_img and not cover_img.startswith('http'):
                cover_img = response.urljoin(cover_img)

            # C. 带着图片去详情页
            yield response.follow(link, callback=self.parse_detail, meta={'cover_image': cover_img})


        # ==========================================================
        # 2. 翻页逻辑 (双重策略)
        # ==========================================================
        
        # 策略 A: 页面上现成的翻页链接 (非遗板块)
        # 你的 HTML 中有 <a ... class="common-component-pagination-item">1</a>
        existing_pagination = response.css('a.common-component-pagination-item::attr(href)').getall()
        
        if existing_pagination:
            for page_link in existing_pagination:
                yield response.follow(page_link, callback=self.parse_list)
        
        # 策略 B: 构造静态翻页 (国内经典板块)
        else:
            # 只有在第一页才进行猜测
            parsed = urlparse(response.url)
            params = parse_qs(parsed.query)
            is_page_1 = 'pageIndex' not in params or params['pageIndex'][0] == '1'
            
            # 并且 URL 看起来像是一个 index.html
            if is_page_1 and "index.html" in response.url:
                # 尝试获取最大页数
                max_page_str = response.css('input[name="pageIndex"]::attr(max)').get()
                
                if max_page_str:
                    max_page = int(max_page_str)
                    if max_page > 1:
                        self.logger.info(f"构造静态翻页: {max_page} 页")
                        base_url = response.url.split('/index.html')[0]
                        for i in range(2, max_page + 1):
                            # 尝试 index_2.html
                            static_url = f"{base_url}/index_{i}.html"
                            yield scrapy.Request(static_url, callback=self.parse_list)
                            
                            # 同时尝试参数翻页 (以防万一选择器修好了就能用了)
                            param_url = f"{base_url}/index.html?pageIndex={i}#list"
                            yield scrapy.Request(param_url, callback=self.parse_list)

    def parse_detail(self, response):
        """ 第三层：详情页 """
        item = {}
        item['page_url'] = response.url
        item['cover_image'] = response.meta.get('cover_image', '') # 接收封面图

        item['title'] = response.css('h2.article__title::text').get(default='').strip()
        
        item['video_url'] = response.css('div.video__wrap video source::attr(src)').get()
        if item['video_url']:
            item['video_url'] = response.urljoin(item['video_url'])
            
        # 作者/来源/时间
        meta_items = response.css('.body__article__meta .body__article__meta-item::text').getall()
        item['author'] = ''
        item['publish_time'] = ''
        for meta in meta_items:
            text = meta.strip()
            if "作者" in text:
                 item['author'] = text.replace("作者：", "").replace("作者:", "").strip()
            elif "来源" in text and not item['author']:
                item['author'] = text.replace("来源：", "").replace("来源:", "").strip()
            elif "时间" in text or "-" in text: 
                item['publish_time'] = text.replace("发布时间：", "").replace("发布时间:", "").strip()

        # 分类 (面包屑)
        breadcrumb_items = response.css('ol.breadcrumb li.breadcrumb-item')
        item['category'] = "其他"
        if len(breadcrumb_items) >= 3:
            # 尝试提取第3级分类
            cat_node = breadcrumb_items[2]
            # 优先取 a 标签文本，其次取直接文本
            item['category'] = cat_node.css('a::text').get() or cat_node.css('::text').get() or "未知"
            item['category'] = item['category'].strip()

        if item['video_url']:
            yield item



# ==========================================
# 3. 启动逻辑 (核心配置)
# ==========================================
if __name__ == "__main__":
    process = CrawlerProcess(settings={

        'ITEM_PIPELINES': {
            '__main__.MyCustomPipeline': 300, 
        },
        
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "ROBOTSTXT_OBEY": False,
        "LOG_LEVEL": "INFO",
        "CONCURRENT_REQUESTS": 4,
        "AUTOTHROTTLE_ENABLED": True
    })

    process.crawl(HawhFinalSpider)
    process.start()