import scrapy
from urllib.parse import urlparse, parse_qs

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
        article_links = response.css(
            'li.article__thumbnail__item a.article__thumbnail__link::attr(href), '
            'li.article__block__item a.article__block__link::attr(href)'
        ).getall()
        
        self.logger.info(f"列表页 {response.url} 提取到 {len(article_links)} 篇文章")
        
        for link in article_links:
            yield response.follow(link, callback=self.parse_detail)


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
        item['page_url'] = response.url
        item['title'] = response.css('h2.article__title::text').get(default='').strip()
        
        item['video_url'] = response.css('div.video__wrap video source::attr(src)').get()
        if item['video_url']:
            item['video_url'] = response.urljoin(item['video_url'])
            
        meta_items = response.css('.body__article__meta .body__article__meta-item::text').getall()
        item['author'] = ''
        item['publish_time'] = ''
        for meta in meta_items:
            text = meta.strip()
            if "来源" in text:
                item['author'] = text.replace("来源：", "").replace("来源:", "").strip()
            elif "时间" in text or "-" in text: 
                item['publish_time'] = text.replace("发布时间：", "").replace("发布时间:", "").strip()

        breadcrumb_items = response.css('ol.breadcrumb li.breadcrumb-item')
        item['category'] = "其他"
        if len(breadcrumb_items) >= 3:
            cat_node = breadcrumb_items[2]
            item['category'] = cat_node.css('a::text').get() or cat_node.css('::text').get() or "未知"
            item['category'] = item['category'].strip()

        if item['video_url']:
            yield item