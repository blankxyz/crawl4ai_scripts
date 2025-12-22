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
    name = 'hawh_final'
    allowed_domains = ['hawh.cn']
    start_urls = ['http://www.hawh.cn/hawh/audioVisual/index.html']

    def parse(self, response):
        """ 第一层：首页入口 """
        # 1. 提取所有板块入口 (列表页)
        entry_links = response.css('a.link__btn::attr(href), a.category__link::attr(href), a.art__link::attr(href), a.old__movies__link::attr(href)').getall()
        for link in entry_links:
            yield response.follow(link, callback=self.parse_list)

        # 2. 提取首页直接展示的文章 (详情页)
        direct_articles = response.css('a.article__link::attr(href), a.swiper__link::attr(href), a.cultural__category__link::attr(href)').getall()
        for link in direct_articles:
            yield response.follow(link, callback=self.parse_detail)

    def parse_list(self, response):
        """ 第二层：列表页 (已修复选择器) """
        
        # ==========================================================
        # 修复点 1: 使用联合选择器，同时匹配 "列表布局" 和 "方块布局"
        # ==========================================================
        # thumbnail_link: 用于 "动态" 等文字列表
        # block_link: 用于 "非遗"、"老片" 等图片方块列表
        # 1. 选中列表项容器
        article_nodes = response.css('li.article__block__item')
        self.logger.info(f"列表页 {response.url} 提取到 {len(article_nodes)} 个文章节点")
        
        for node in article_nodes:
            # ==========================
            # 修复点：放宽链接提取条件
            # ==========================
            # 只要是 li 里面的 a 标签，就提取它的 href
            link = node.css('a::attr(href)').get()
            
            if not link:
                self.logger.warning(f"节点中未找到链接，跳过: {node.get()[:50]}...")
                continue

            # 2. 提取图片链接
            # 图片通常在 style="background-image: url('...')" 或者 <img> 标签中
            # 先尝试提取 style 属性
            # --- B. 提取背景图片 (针对你提供的 HTML 结构) ---
            # 目标 HTML: <div class="aspect-ratio-content" style="background-image: url('http://...');"></div>
            
            # 步骤 1: 获取 style 属性的完整内容
            style_text = node.css('.aspect-ratio-content::attr(style)').get()
            
            cover_img = None
            if style_text:
                # 步骤 2: 使用正则提取 url('...') 中间的内容
                # 解释: url\s*\(  匹配 url(
                #      ['"]?    匹配可选的单引号或双引号
                #      (.*?)    非贪婪匹配，提取我们要的链接
                #      ['"]?    匹配可选的结束引号
                #      \)       匹配结束括号
                import re
                match = re.search(r"url\s*\(\s*['\"]?(.*?)['\"]?\s*\)", style_text)
                if match:
                    cover_img = match.group(1)
            
            # 步骤 3: 如果提取到了，确保是绝对路径
            if cover_img and not cover_img.startswith('http'):
                cover_img = response.urljoin(cover_img)

            # 3. 带着图片信息去访问详情页
            # 使用 meta 参数传递数据
            yield response.follow(link, callback=self.parse_detail, meta={'cover_image': cover_img})

        # ==========================================================
        # 翻页逻辑 (保持智能判断)
        # ==========================================================
        
        # 1. 优先提取页面现成的翻页链接 (针对非遗、动态等正常板块)
        existing_pagination = response.css('a.common-component-pagination-item::attr(href)').getall()
        if existing_pagination:
            for page_link in existing_pagination:
                yield response.follow(page_link, callback=self.parse_list)

        # 2. 补救措施：如果页面上没有翻页链接，或者提取到了 0 篇文章(可能需要静态翻页)
        # 针对 "国内经典" 这种可能需要 index_2.html 的板块
        else:
            parsed = urlparse(response.url)
            params = parse_qs(parsed.query)
            # 仅在第一页执行猜测逻辑
            is_page_1 = 'pageIndex' not in params or params['pageIndex'][0] == '1'
            
            if is_page_1 and "index.html" in response.url:
                max_page_str = response.css('input[name="pageIndex"]::attr(max)').get()
                if max_page_str:
                    max_page = int(max_page_str)
                    if max_page > 1:
                        self.logger.info(f"尝试构造静态翻页链接 (共{max_page}页): {response.url}")
                        base_url = response.url.split('/index.html')[0]
                        for i in range(2, max_page + 1):
                            # 这里同时尝试两种可能性，反正404会被Scrapy忽略
                            
                            # 可能性A: 静态文件 index_2.html (最常见)
                            url_static = f"{base_url}/index_{i}.html"
                            yield scrapy.Request(url_static, callback=self.parse_list)
                            
                            # 可能性B: 参数翻页 ?pageIndex=2 (虽然之前失败了，但在新选择器下可能成功)
                            # 如果之前的失败是因为选择器没写对，那现在加上这个可能就行了
                            url_param = f"{base_url}/index.html?pageIndex={i}#list"
                            yield scrapy.Request(url_param, callback=self.parse_list)

    def parse_detail(self, response):
        """ 第三层：详情页 """


        item = {}

        item['cover_image'] = response.meta.get('cover_image', '')
        
        item['page_url'] = response.url
        item['title'] = response.css('h2.article__title::text').get(default='').strip()
        
        item['video_url'] = response.css('div.video__wrap video source::attr(src)').get()
        if item['video_url']:
            item['video_url'] = response.urljoin(item['video_url'])
            
        # ==========================================================
        # 提取作者和发布时间 (兼容 "作者" 和 "来源" 两种写法)
        # ==========================================================
        meta_items = response.css('.body__article__meta .body__article__meta-item::text').getall()
        
        item['author'] = '管理员'
        item['publish_time'] = ''

        for meta in meta_items:
            text = meta.strip()
            
            # 情况1: 提取 "作者" (例如: 作者：管理员)
            if "作者" in text:
                item['author'] = text.replace("作者：", "").replace("作者:", "").strip()
            
            # 情况2: 提取 "来源" (例如: 来源：新华社) - 如果没找到作者，来源也可以作为作者字段
            elif "来源" in text and not item['author']:
                item['author'] = text.replace("来源：", "").replace("来源:", "").strip()
            
            # 情况3: 提取时间
            elif "时间" in text or "-" in text: 
                # 简单判断是否包含 "发布时间" 字样或者类似 2018-01-11 的日期格式
                clean_time = text.replace("发布时间：", "").replace("发布时间:", "").strip()
                item['publish_time'] = clean_time

        breadcrumb_items = response.css('ol.breadcrumb li.breadcrumb-item')
        item['category'] = "其他"
        if len(breadcrumb_items) >= 3:
            cat_node = breadcrumb_items[2]
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
        
        # 其他设置
        "USER_AGENT": "Mozilla/5.0 ...",
        "ROBOTSTXT_OBEY": False,
        "LOG_LEVEL": "INFO",
    })

    process.crawl(HawhFinalSpider)
    process.start()