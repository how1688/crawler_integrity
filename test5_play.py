
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import time
import datetime as dt
from datetime import datetime, timedelta
import requests
from supabase import create_client, Client
import uuid
import os
import json
import random
import re
from urllib.parse import urljoin, urlparse
from collections import defaultdict
from dateutil import parser
from google import genai
from google.genai import types
import shutil
from dotenv import load_dotenv

load_dotenv()  # 這行會讀 .env 檔

# Supabase imports
from supabase import create_client, Client

# Supabase 配置
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# 初始化 Supabase 客戶端
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("請先設定你的 GEMINI_API_KEY 環境變數。")

try:
    gemini_client = genai.Client()
except Exception as e:
    raise ValueError(f"無法初始化 Gemini Client，請檢查 API 金鑰：{e}")

def clean_data(data):
    for i, article in enumerate(data):
            print(f"正在處理第 {i+1} 篇文章...")
            if "articles" in article:
                for j, sub_article in enumerate(article["articles"]):
                    print(f"   正在處理第 {j+1} 篇子文章...")

                    # (1) 去除 HTML
                    raw_content = sub_article.get("content", "")
                    soup = BeautifulSoup(raw_content, "html.parser")
                    cleaned_text = soup.get_text(separator="\n", strip=True)
                    print(cleaned_text)

                    # (2) 使用 Gemini API 去除雜訊
                    prompt = f"""
                    請去除以下文章中的雜訊，例如多餘的標題、時間戳記、來源資訊等，並最大量的保留所有新聞內容：

                    {cleaned_text}

                    你只需要回覆經過處理的內容，不需要任何其他說明或標題。
                    如果沒有文章內容，請回覆 "[清洗失敗]"。
                    """
                    
                    max_retries = 3
                    retries = 0
                    success = False
                    
                    while not success and retries < max_retries:
                        try:
                            response = gemini_client.models.generate_content(
                                model="gemini-2.0-flash",
                                contents=prompt
                            )
                            sub_article["content"] = response.candidates[0].content.parts[0].text.strip()
                            success = True
                            time.sleep(1)
                        except Exception as e:
                            if "503 UNAVAILABLE" in str(e):
                                retries += 1
                                print(f"偵測到模型過載，正在嘗試第 {retries} 次重試...")
                                time.sleep(3 * retries)
                            else:
                                print(f"發生錯誤，錯誤訊息：{e}")
                                sub_article["content"] = "[清洗失敗]"
                                break
                    
                    if not success:
                        print(f"嘗試 {max_retries} 次後仍無法成功處理文章")
                        sub_article["content"] = "[清洗失敗]"

    return data

def create_robust_browser(playwright, headless: bool = True):
    """創建一個更穩健的 Playwright Browser"""
    try:
        # 設定瀏覽器選項
        browser_args = [
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "--disable-blink-features=AutomationControlled",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=TranslateUI",
            "--disable-ipc-flooding-protection",
            "--disable-background-media",
            "--disable-background-downloads",
            "--aggressive-cache-discard",
            "--disable-sync",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-plugins",
            "--disable-notifications",
            "--disable-popup-blocking",
            "--memory-pressure-off",
            "--max_old_space_size=4096"
        ]

        if not headless:
            browser_args.append("--start-maximized")

        browser = playwright.chromium.launch(
            headless=headless,
            args=browser_args
        )
        
        # 創建上下文
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080} if not headless else {"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            locale="zh-TW",
            timezone_id="Asia/Taipei"
        )
        
        # 添加初始化腳本，防止被偵測為自動化
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-TW', 'zh', 'en'],
            });
        """)
        
        # 阻擋某些資源類型以提升效能
        context.route("**/*", lambda route: (
            route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"] 
            else route.continue_()
        ))
        
        return browser, context
        
    except Exception as e:
        print(f"創建 Playwright Browser 失敗: {e}")
        raise

def get_main_story_links(main_url, category):
    """步驟 1: 從主頁抓取所有主要故事連結"""
    story_links = []
    
    with sync_playwright() as p:
        try:
            browser, context = create_robust_browser(p, headless=True)
            page = context.new_page()
            
            print(f"正在抓取 {category} 領域的主要故事連結...")
            
            # 設定超時時間
            page.set_default_timeout(15000)
            
            page.goto(main_url)
            
            # 等待特定元素載入
            page.wait_for_selector('c-wiz[jsrenderer="jeGyVb"]', timeout=15000)
            
            # 取得頁面內容
            content = page.content()
            soup = BeautifulSoup(content, "html.parser")
            c_wiz_blocks = soup.find_all("c-wiz", {"jsrenderer": "jeGyVb"})
            
            print(f"找到 {len(c_wiz_blocks)} 個 c-wiz 區塊")
            
            for i, block in enumerate(c_wiz_blocks, start=1):
                try:
                    story_link = block.find("a", class_="jKHa4e")
                    
                    if story_link:
                        href = story_link.get("href")
                        title = story_link.text.strip()
                        
                        if href:
                            if href.startswith("./"):
                                full_link = "https://news.google.com" + href[1:]
                            else:
                                full_link = "https://news.google.com" + href
                            
                            # 檢查資料庫
                            should_skip, action_type, story_data, skip_reason = check_story_exists_in_supabase(
                                full_link, category, "", ""
                            )
                            
                            print(f"   處理故事 {i}: {href}")
                            print(f"   檢查結果: {skip_reason}")
                            
                            # 根據action_type決定story_id
                            if action_type == "add_to_existing_story" and story_data:
                                story_id = story_data["story_id"]
                            else:
                                story_id = str(uuid.uuid4())
                            
                            story_links.append({
                                "index": i,
                                "story_id": story_id,
                                "title": title,
                                "url": full_link,
                                "category": category,
                                "action_type": action_type,
                                "existing_story_data": story_data
                            })
                            
                            print(f"{i}. [{category}] {title}")
                            print(f"   故事ID: {story_id}")
                            print(f"   {full_link}")
                            print(f"   處理類型: {action_type}")
                            
                except Exception as e:
                    print(f"處理故事區塊 {i} 時出錯: {e}")
                    continue
            
            print(f"\n總共收集到 {len(story_links)} 個 {category} 領域需要處理的主要故事連結")
            
        except PlaywrightTimeoutError:
            print(f"頁面載入超時: {main_url}")
        except Exception as e:
            print(f"抓取主要故事連結時出錯: {e}")
        finally:
            try:
                browser.close()
            except:
                pass
    
    return story_links

def get_article_links_from_story(story_info):
    """步驟 2: 進入每個故事頁面，找出所有 article 下的文章連結和相關信息"""
    article_links = []
    
    with sync_playwright() as p:
        try:
            browser, context = create_robust_browser(p, headless=True)
            page = context.new_page()
            
            print(f"\n正在處理故事 {story_info['index']}: [{story_info['category']}] {story_info['title']}")
            print(f"   故事ID: {story_info['story_id']}")
            
            # 取得現有故事的 crawl_date (如果有的話)
            existing_story_data = story_info.get('existing_story_data')
            cutoff_date = None
            if existing_story_data and existing_story_data.get('crawl_date'):
                try:
                    cutoff_date_str = existing_story_data['crawl_date']
                    if isinstance(cutoff_date_str, str):
                        try:
                            cutoff_date = parser.parse(cutoff_date_str)
                        except:
                            cutoff_date = datetime.strptime(cutoff_date_str, "%Y/%m/%d %H:%M")
                    print(f"   只處理 {cutoff_date_str} 之後的文章")
                except Exception as e:
                    print(f"   解析 cutoff_date 時出錯: {e}")
            
            page.goto(story_info['url'])
            time.sleep(random.randint(3, 6))
            
            content = page.content()
            soup = BeautifulSoup(content, "html.parser")
            article_elements = soup.find_all("article", class_="MQsxIb xTewfe tXImLc R7GTQ keNKEd keNKEd VkAdve GU7x0c JMJvke q4atFc")
            
            print(f"   找到 {len(article_elements)} 個 article 元素")
            
            processed_count = 0
            
            for j, article in enumerate(article_elements, start=1):
                try:
                    if processed_count >= 15:
                        break
                    
                    h4_element = article.find("h4", class_="ipQwMb ekueJc RD0gLb")
                    
                    if h4_element:
                        link = h4_element.find("a", class_="DY5T1d RZIKme")
                        
                        if link:
                            href = link.get("href")
                            link_text = link.text.strip()
                            
                            media_element = article.find("a", class_="wEwyrc")
                            media = media_element.text.strip() if media_element else "未知來源"

                            # 跳過特定媒體
                            if media in ["MSN", "自由時報", "chinatimes.com", "中時電子報", 
                                         "中時新聞網", "上報Up Media", "點新聞", "香港文匯網", 
                                         "天下雜誌", "自由健康網", "知新聞", "SUPERMOTO8", 
                                         "警政時報", "大紀元", "新唐人電視台", "arch-web.com.tw",
                                         "韓聯社", "公視新聞網PNN", "優分析UAnalyze", "AASTOCKS.com",
                                         "KSD 韓星網", "商周", "自由財經", "鉅亨號",
                                         "wownews.tw", "utravel.com.hk", "更生新聞網", "香港電台",
                                         "citytimes.tw"]:
                                continue

                            time_element = article.find(class_="WW6dff uQIVzc Sksgp slhocf")
                            article_datetime = "未知時間"
                            
                            if time_element and time_element.get("datetime"):
                                dt_str = time_element.get("datetime")
                                dt_obj = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                                article_datetime_obj = dt_obj + timedelta(hours=8)
                                article_datetime = article_datetime_obj.strftime("%Y/%m/%d %H:%M:%S")
                                
                                # 檢查文章時間是否在 cutoff_date 之後
                                if cutoff_date and article_datetime_obj <= cutoff_date:
                                    print(f"     跳過舊文章: {link_text}")
                                    print(f"        文章時間: {article_datetime} <= 截止時間: {cutoff_date}")
                                    continue
                            
                            if href:
                                if href.startswith("./"):
                                    full_href = "https://news.google.com" + href[1:]
                                else:
                                    full_href = "https://news.google.com" + href
                                
                                # 檢查文章是否需要處理
                                should_skip, action_type, story_data, skip_reason = check_story_exists_in_supabase(
                                    story_info['url'], story_info['category'], article_datetime, full_href
                                )
                                
                                if should_skip and action_type == "skip":
                                    print(f"     跳過文章: {link_text}")
                                    print(f"        原因: {skip_reason}")
                                    continue
                                
                                article_links.append({
                                    "story_id": story_info['story_id'],
                                    "story_title": story_info['title'],
                                    "story_category": story_info['category'],
                                    "story_url": story_info['url'],
                                    "article_index": processed_count + 1,
                                    "article_title": link_text,
                                    "article_url": full_href,
                                    "media": media,
                                    "article_datetime": article_datetime,
                                    "action_type": action_type,
                                    "existing_story_data": story_data
                                })
                                
                                processed_count += 1
                                print(f"     {processed_count}. {link_text}")
                                print(f"        媒體: {media}")
                                print(f"        時間: {article_datetime}")
                                print(f"        處理類型: {action_type}")
                                print(f"        {full_href}")
                                
                except Exception as e:
                    print(f"     處理文章元素 {j} 時出錯: {e}")
                    continue
            
            if processed_count == 0 and cutoff_date:
                print(f"   此故事沒有 {cutoff_date} 之後的新文章")
            
        except Exception as e:
            print(f"處理故事時出錯: {e}")
        finally:
            try:
                browser.close()
            except:
                pass
    
    return article_links

def get_final_content(article_info, page):
    """步驟 3: 跳轉到原始網站並抓取內容 - 使用 Playwright (修正版本)"""
    MAX_RETRIES = 2
    TIMEOUT = 15000  # 15秒 (Playwright使用毫秒)
    
    for attempt in range(MAX_RETRIES):
        try:
            print(f"   尝试第 {attempt + 1} 次访问...")
            
            # 设定页面超时
            page.set_default_timeout(TIMEOUT)
            
            try:
                # 使用 wait_until 参数确保页面完全加载
                page.goto(article_info['article_url'], timeout=TIMEOUT, wait_until='domcontentloaded')
                
                # 等待页面稳定
                try:
                    # 等待网络空闲，确保页面完全加载
                    page.wait_for_load_state('networkidle', timeout=10000)
                except PlaywrightTimeoutError:
                    # 如果网络空闲超时，至少等待DOM加载完成
                    page.wait_for_load_state('domcontentloaded', timeout=5000)
                    
            except PlaywrightTimeoutError:
                print(f"   页面加载超时，尝试继续...")
                # 即使超时也尝试获取内容
                try:
                    page.wait_for_load_state('domcontentloaded', timeout=3000)
                except:
                    pass
            except Exception as e:
                print(f"   页面导航错误: {e}")
                if attempt < MAX_RETRIES - 1:
                    print(f"   {TIMEOUT//4000} 秒后重试...")
                    time.sleep(TIMEOUT//4000)
                    continue
                else:
                    return None
            
            # 额外等待确保页面稳定
            time.sleep(random.randint(2, 4))
            
            try:
                skip_patterns = [
                    "https://www.gamereactor.cn/video",
                    "https://wantrich.chinatimes.com",
                    "https://taongafarm.site", 
                    "https://www.cmoney.tw",
                    "https://www.cw.com.tw",
                    "https://www.msn.com/",
                    "https://cn.wsj.com/",
                    "https://about.pts.org.tw/pr/latestnews",
                    "https://www.chinatimes.com",
                    "https://sports.ltn.com.tw",
                    "https://video.ltn.com.tw",
                    "https://def.ltn.com.tw",
                    "https://www.upmedia.mg",
                    "http://www.aastocks.com",
                    "https://news.futunn.com",
                    "https://ec.ltn.com.tw/",
                    "https://health.ltn.com.tw",
                    "https://www.taiwannews",
                    "https://www.ftvnews.com.tw",
                    "https://tw.nextapple.com",
                    "https://talk.ltn.com.tw",
                    "https://www.mobile01.com/",
                    "https://www.worldjournal.com/"
                ]
                
                try:
                    # 安全获取当前URL
                    final_url = None
                    url_attempts = 0
                    max_url_attempts = 3
                    
                    while url_attempts < max_url_attempts and final_url is None:
                        try:
                            final_url = page.url
                            break
                        except Exception as url_error:
                            if "navigating" in str(url_error).lower():
                                print(f"   页面仍在导航，等待获取URL... (第 {url_attempts + 1} 次)")
                                time.sleep(1)
                                url_attempts += 1
                            else:
                                print(f"   获取URL时出错: {url_error}")
                                break
                    
                    if final_url is None:
                        final_url = article_info['article_url']
                        print(f"   无法获取最终URL，使用原始URL")
                    else:
                        print(f"   最终网址: {final_url}")
                        
                except Exception as e:
                    print(f"   URL处理异常: {e}")
                    final_url = article_info['article_url']
                
                if final_url.startswith("https://www.google.com/sorry/index?continue=https://news.google.com/read"):
                    print(f"   遇到 Google 验证页面，尝试刷新...")
                    try:
                        page.reload()
                        time.sleep(random.randint(2, 4))
                        final_url = page.url
                    except:
                        print(f"   刷新失败")
                        return None
                        
                elif any(final_url.startswith(pattern) for pattern in skip_patterns):
                    print(f"   跳过连结: {final_url}")
                    return None
                
            except Exception as e:
                print(f"   获取 URL 时出错: {e}")
                final_url = article_info['article_url']
            
            try:
                # 检查页面状态，确保没有在导航中
                page_state = None
                max_wait_attempts = 10
                wait_attempt = 0
                
                while wait_attempt < max_wait_attempts:
                    try:
                        # 检查页面是否处于稳定状态
                        current_url = page.url
                        page_state = "stable"
                        break
                    except Exception as url_error:
                        if "navigating" in str(url_error).lower():
                            print(f"   页面仍在导航中，等待... (第 {wait_attempt + 1} 次)")
                            time.sleep(1)
                            wait_attempt += 1
                        else:
                            print(f"   页面状态检查错误: {url_error}")
                            break
                
                if wait_attempt >= max_wait_attempts:
                    print(f"   页面导航超时，尝试强制获取内容")
                
                # 等待一小段时间确保页面完全渲染
                time.sleep(2)
                
                # 尝试多次获取页面内容，直到成功
                html = None
                content_attempts = 0
                max_content_attempts = 5
                
                while content_attempts < max_content_attempts and html is None:
                    try:
                        html = page.content()
                        if html and len(html) > 100:
                            break
                        else:
                            html = None
                    except Exception as content_error:
                        if "navigating" in str(content_error).lower():
                            print(f"   页面仍在变化中，等待... (内容获取第 {content_attempts + 1} 次)")
                            time.sleep(2)
                            content_attempts += 1
                        else:
                            print(f"   获取页面内容错误: {content_error}")
                            break
                
                if not html or len(html) < 100:
                    print(f"   页面内容过短或为空")
                    if attempt < MAX_RETRIES - 1:
                        continue
                    else:
                        return None
                        
                soup = BeautifulSoup(html, "html.parser")
            except Exception as e:
                print(f"   解析页面时出错: {e}")
                if "navigating" in str(e).lower():
                    print(f"   页面仍在导航中，等待后重试...")
                    time.sleep(3)
                    if attempt < MAX_RETRIES - 1:
                        continue
                return None

            # 内容提取逻辑（保持原有逻辑）
            content_to_clean = None
            article_tag = soup.find('article')
            if article_tag and article_info['media'] != 'Now 新聞':
                content_to_clean = str(article_tag)
            elif soup.find('artical'):
                article_tag = soup.find('artical')
                content_to_clean = str(article_tag)
            else:
                target_ids = [
                    'text ivu-mt', 'content-box', 'text', 'boxTitle', 
                    'news-detail-content', 'story', 'article-content__editor', 'article-body', 
                    'artical-content', 'article_text', 'newsText'
                ]
                
                div_by_id = None
                for target_id in target_ids:
                    try:
                        div_by_id = soup.find('div', id=target_id)
                        if div_by_id:
                            break
                    except Exception as e:
                        continue
                
                if div_by_id:
                    content_to_clean = str(div_by_id)
                else:
                    target_classes = ['articleBody clearfix', 'text boxTitle','text ivu-mt', 'paragraph', 'atoms', 
                                      'news-box-text border', 'newsLeading', 'text']

                    div_by_class = None
                    for target_class in target_classes:
                        try:
                            div_by_class = soup.find('div', class_=target_class)
                            if div_by_class:
                                break
                        except Exception as e:
                            continue
                    
                    if div_by_class:
                        content_to_clean = str(div_by_class)
                    else:
                        if soup.body:
                            content_to_clean = str(soup.body)

            if content_to_clean:
                try:
                    content_soup = BeautifulSoup(content_to_clean, "html.parser")
                    
                    excluded_divs = content_soup.find_all('div', class_='paragraph moreArticle')
                    for div in excluded_divs:
                        div.decompose()
                    
                    excluded_p_classes = [
                        'mb-module-gap read-more-vendor break-words leading-[1.4] text-px20 lg:text-px18 lg:leading-[1.8] text-batcave __web-inspector-hide-shortcut__',
                        'mb-module-gap read-more-editor break-words leading-[1.4] text-px20 lg:text-px18 lg:leading-[1.8] text-batcave'
                    ]
                    
                    for p_class in excluded_p_classes:
                        excluded_ps = content_soup.find_all('p', class_=p_class)
                        for p in excluded_ps:
                            p.decompose()
                    
                    body_content = str(content_soup)
                    body_content = body_content.replace("\x00", "").replace("\r", "").replace("\n", "")
                    body_content = body_content.replace('"', '\\"')
                    
                except Exception as e:
                    print(f"   内容清理时出错: {e}")
                    body_content = ""
            else:
                body_content = ""
                print(f"   未找到可用的内容")
                
            article_id = str(uuid.uuid4())

            if ("您的網路已遭到停止訪問本網站的權利。" in body_content or 
                "我們的系統偵測到您的電腦網路送出的流量有異常情況。" in body_content):
                print(f"   文章 {article_id} 被封锁，无法访问")
                return None

            return {
                "story_id": article_info['story_id'],
                "story_title": article_info['story_title'],
                "story_category": article_info['story_category'],
                "story_url": article_info['story_url'],
                "id": article_id,
                "article_index": article_info['article_index'],
                "article_title": article_info['article_title'],
                "google_news_url": article_info['article_url'],
                "final_url": final_url,
                "media": article_info.get('media', '未知来源'),
                "content": body_content,
                "article_datetime": article_info.get('article_datetime', '未知时间'),
                "action_type": article_info.get('action_type', 'process'),
                "existing_story_data": article_info.get('existing_story_data')
            }
            
        except Exception as e:
            print(f"   第 {attempt + 1} 次尝试失败: {e}")
            if attempt < MAX_RETRIES - 1:
                print(f"   {TIMEOUT//2000} 秒后重试...")
                time.sleep(TIMEOUT//2000)
            else:
                print(f"   已达到最大重试次数，放弃该文章")
    
    return None

def check_story_exists_in_supabase(story_url, category, article_datetime="", article_url=""):
    """
    检查故事是否存在于数据库中，并返回相应的处理逻辑
    
    Args:
        story_url: 故事URL
        category: 新闻分类
        article_datetime: 文章时间
        article_url: 文章URL
    
    Returns:
        tuple: (should_skip, action_type, story_data, skip_reason)
    """
    try:
        # 1. 检查 story_url 是否存在，按 crawl_date 降序排列取最新的
        story_response = supabase.table("stories").select("*").eq("story_url", story_url).order("crawl_date", desc=True).limit(1).execute()

        if not story_response.data:
            # 故事不存在，需要创建新故事
            return False, "create_new_story", None, "新故事"
        
        existing_story = story_response.data[0]
        story_id = existing_story["story_id"]
        existing_crawl_date = existing_story["crawl_date"]
        
        # 2. 检查时间范围（3天内）
        try:
            if existing_crawl_date:
                # 处理不同的日期格式
                if isinstance(existing_crawl_date, str):
                    try:
                        existing_dt = parser.parse(existing_crawl_date)
                    except:
                        existing_dt = datetime.strptime(existing_crawl_date, "%Y/%m/%d %H:%M")
                else:
                    existing_dt = existing_crawl_date
                    
                current_dt = datetime.now()
                days_diff = (current_dt - existing_dt).days
                
                if days_diff <= 3:
                    # 在3天内，使用现有故事ID
                    print(f"   使用现有故事ID: {story_id} (距离上次爬取 {days_diff} 天)")
                    print(f"   上次爬取时间: {existing_crawl_date}")
                    
                    # 3. 检查文章是否在 crawl_date 之后
                    if article_datetime and article_datetime != "未知时间":
                        try:
                            article_dt = parser.parse(article_datetime)
                            
                            # 比较文章时间和上次爬取时间
                            if article_dt <= existing_dt:
                                # 文章时间早于或等于上次爬取时间，跳过
                                return True, "skip", existing_story, f"文章时间 {article_datetime} 早于上次爬取时间 {existing_crawl_date}"
                                
                        except Exception as date_parse_error:
                            print(f"   文章时间解析错误: {date_parse_error}")
                            # 如果无法解析文章时间，继续检查 URL
                    
                    # 4. 检查文章URL是否已存在
                    if article_url:
                        article_response = supabase.table("cleaned_news").select("article_id").eq("article_url", article_url).execute()
                        
                        if article_response.data:
                            # 文章已存在，跳过
                            return True, "skip", existing_story, f"文章已存在于故事 {story_id}"
                        else:
                            # 文章不存在且时间符合，加入现有故事
                            return False, "add_to_existing_story", existing_story, f"加入现有故事 {story_id} (新文章)"
                    else:
                        # 没有文章URL（故事层级的检查）
                        return False, "add_to_existing_story", existing_story, f"使用现有故事 {story_id}"
                else:
                    # 超过3天，创建新故事
                    return False, "create_new_story", None, f"超过时间限制 ({days_diff} 天)，创建新故事"
            else:
                # 没有 crawl_date，创建新故事
                return False, "create_new_story", None, "缺少爬取日期，创建新故事"
                
        except Exception as date_error:
            print(f"   日期解析错误: {date_error}")
            return False, "create_new_story", None, f"日期解析错误: {date_error}"
            
    except Exception as e:
        print(f"   检查Supabase时出错: {e}")
        return False, "create_new_story", None, f"数据库检查错误: {e}"

def save_story_to_supabase(story_data):
    """
    保存故事到 Supabase stories 表
    """
    try:
        story_record = {
            "story_id": story_data["story_id"],
            "story_url": story_data["story_url"],
            "story_title": story_data["story_title"],
            "category": story_data["category"],
            "crawl_date": story_data["crawl_date"]
        }
        
        # 使用 upsert 来避免重复插入
        response = supabase.table("stories").upsert(story_record, on_conflict="story_id").execute()
        print(f"   故事已保存到数据库: {story_data['story_id']}")
        return True
        
    except Exception as e:
        print(f"   保存故事到数据库失败: {e}")
        return False


def save_article_to_supabase(article_data, story_id):
    """
    保存文章到 Supabase cleaned_news 表
    """
    try:
        article_record = {
            "article_id": article_data["article_id"],
            "article_title": article_data["article_title"],
            "article_url": article_data["article_url"],
            "content": article_data["content"],
            "media": article_data["media"],
            "story_id": story_id
        }
        
        # 使用 upsert 来避免重复插入
        article_url = article_data["article_url"]
        existing_article = supabase.table("cleaned_news").select("article_id").eq("article_url", article_url).execute()
        
        if existing_article.data:
            print(f"   文章已存在，跳过保存: {article_data['article_id']}")
            return True
        elif not article_data["content"] or "[清洗失败]" in article_data["content"] or "请提供" in article_data["content"]:
            print(f"   文章内容无效，跳过保存: {article_data['article_id']}")
            return True
            
        response = supabase.table("cleaned_news").upsert(article_record, on_conflict="article_id").execute()
        print(f"   文章已保存到数据库: {article_data['article_id']}")
        return True
        
    except Exception as e:
        print(f"   保存文章到数据库失败: {e}")
        return False


def group_articles_by_story_and_time(processed_articles, time_window_days=3):
    """
    根据故事分组，然后在每个故事内按时间将文章分组
    同时支持现有故事的更新功能
    
    Args:
        processed_articles: 从 get_final_content 处理后的文章列表
        time_window_days: 时间窗口天数（真正的每N天分组）
    
    Returns:
        list: 处理后的故事列表，包含 action_type 字段
    """
    print(f"\n=== 开始基于故事和时间分组文章 ===")
    print(f"时间窗口: {time_window_days}天")
    
    # 按故事ID分组
    story_grouped = defaultdict(list)
    for article in processed_articles:
        story_id = article["story_id"]
        story_grouped[story_id].append(article)
    
    all_final_stories = []
    
    for story_id, articles in story_grouped.items():
        if not articles:
            continue
            
        # 获取故事基本信息（从第一篇文章）
        first_article = articles[0]
        story_title = first_article["article_title"]
        story_url = first_article["story_url"]
        story_category = first_article["story_category"]
        
        # 检查是否为现有故事更新
        existing_story_data = first_article.get("existing_story_data")
        is_existing_story = existing_story_data and first_article.get("action_type") == "add_to_existing_story"
        
        if is_existing_story:
            print(f"\n更新现有故事: {story_title}")
            print(f"   Story ID: {story_id}")
            print(f"   原有 Crawl Date: {existing_story_data.get('crawl_date', '未知')}")
            print(f"   原有时间范围: {existing_story_data.get('time_range', '未知')}")
            base_action_type = "update_existing_story"
        else:
            print(f"\n处理新故事: {story_title}")
            print(f"   Story ID: {story_id}")
            base_action_type = "create_new_story"
        
        print(f"   包含 {len(articles)} 篇文章")
        
        # 解析所有文章的时间
        articles_with_time = []
        for article in articles:
            article_datetime = article.get('article_datetime', '未知时间')
            if article_datetime and article_datetime != '未知时间':
                try:
                    parsed_dt = parser.parse(article_datetime)
                    articles_with_time.append({
                        'article': article,
                        'datetime': parsed_dt
                    })
                except (ValueError, TypeError) as e:
                    print(f"解析时间失败: {article_datetime}, 使用当前时间")
                    articles_with_time.append({
                        'article': article,
                        'datetime': datetime.now()
                    })
            else:
                # 没有时间的文章使用当前时间
                articles_with_time.append({
                    'article': article,
                    'datetime': datetime.now()
                })
        
        # 按时间排序
        articles_with_time.sort(key=lambda x: x['datetime'])
        
        # 执行时间窗口分组
        time_groups = _create_time_groups(articles_with_time, time_window_days)
        print(f"   在故事内分成 {len(time_groups)} 个时间组")

        # 为每个时间组创建最终的故事数据
        for group_idx, group in enumerate(time_groups):
            # 找到组内最早和最晚的时间
            earliest_time = min(item['datetime'] for item in group)
            latest_time = max(item['datetime'] for item in group)
            
            # 决定使用哪个时间作为 crawl_date
            if is_existing_story:
                # 现有故事：优先使用原有的 crawl_date，如果没有则使用当前时间
                original_crawl_date = existing_story_data.get('crawl_date')
                if original_crawl_date:
                    crawl_date = original_crawl_date
                    print(f"      保持原有 Crawl Date: {crawl_date}")
                else:
                    crawl_date = datetime.now().strftime("%Y/%m/%d %H:%M")
                    print(f"      使用当前时间作为 Crawl Date: {crawl_date}")
            else:
                # 新故事：使用最早文章时间
                crawl_date = earliest_time.strftime("%Y/%m/%d %H:%M")
            
            # 计算实际的时间范围 - 对于现有故事，优先使用原有时间范围
            if is_existing_story and existing_story_data.get('time_range'):
                # 现有故事且有时间范围：合并新旧时间范围
                original_time_range = existing_story_data.get('time_range')
                try:
                    # 解析原有时间范围
                    if ' - ' in original_time_range:
                        orig_start_str, orig_end_str = original_time_range.split(' - ')
                        orig_start = datetime.strptime(orig_start_str, '%Y/%m/%d')
                        orig_end = datetime.strptime(orig_end_str, '%Y/%m/%d')
                    else:
                        orig_start = orig_end = datetime.strptime(original_time_range, '%Y/%m/%d')
                    
                    # 计算合并后的时间范围
                    combined_start = min(orig_start, earliest_time.replace(hour=0, minute=0, second=0, microsecond=0))
                    combined_end = max(orig_end, latest_time.replace(hour=0, minute=0, second=0, microsecond=0))
                    
                    if combined_start.date() == combined_end.date():
                        time_range = combined_start.strftime('%Y/%m/%d')
                    else:
                        time_range = f"{combined_start.strftime('%Y/%m/%d')} - {combined_end.strftime('%Y/%m/%d')}"
                    
                    print(f"      合并时间范围: {original_time_range} + {earliest_time.strftime('%Y/%m/%d')}~{latest_time.strftime('%Y/%m/%d')} = {time_range}")
                    
                except (ValueError, TypeError) as e:
                    print(f"      解析原有时间范围失败: {original_time_range}，使用新文章时间范围")
                    # 如果解析失败，使用新文章的时间范围
                    if earliest_time.date() == latest_time.date():
                        time_range = earliest_time.strftime('%Y/%m/%d')
                    else:
                        time_range = f"{earliest_time.strftime('%Y/%m/%d')} - {latest_time.strftime('%Y/%m/%d')}"
            else:
                # 新故事或现有故事没有时间范围：使用新文章的时间范围
                if earliest_time.date() == latest_time.date():
                    time_range = earliest_time.strftime('%Y/%m/%d')
                else:
                    time_range = f"{earliest_time.strftime('%Y/%m/%d')} - {latest_time.strftime('%Y/%m/%d')}"
            
            # 生成最终的故事ID和标题
            if len(time_groups) > 1:
                # 多个时间组：需要为每组生成新的ID
                if is_existing_story:
                    # 现有故事分组：保持原ID并添加组别后缀
                    base_story_id = story_id
                    final_story_id = f"{base_story_id}_G{group_idx + 1:02d}"
                    final_action_type = f"{base_action_type}_with_time_grouping"
                else:
                    # 新故事分组：标准的分组逻辑
                    base_story_id = story_id[:-2] if len(story_id) >= 2 else story_id
                    final_story_id = f"{base_story_id}{group_idx + 1:02d}"
                    final_action_type = f"{base_action_type}_with_time_grouping"
                
                final_story_title = f"{story_title} (第{group_idx + 1}组)"
            else:
                # 单一组：保持原有ID和标题
                final_story_id = story_id
                final_story_title = story_title
                final_action_type = base_action_type
            
            # 准备文章列表
            grouped_articles = []
            for article_idx, item in enumerate(group, 1):
                article = item['article']
                grouped_articles.append({
                    "article_id": article["id"],
                    "article_title": article["article_title"],
                    "article_index": article_idx,  # 重新编号
                    "google_news_url": article["google_news_url"],
                    "article_url": article["final_url"],
                    "media": article["media"],
                    "content": article["content"],
                    "original_datetime": article.get("article_datetime", "未知时间")
                })
            
            # 创建故事数据结构
            story_data = {
                "story_id": final_story_id,
                "story_title": final_story_title,
                "story_url": story_url,
                "crawl_date": crawl_date,
                "time_range": time_range,
                "category": story_category,
                "articles": grouped_articles,
                "action_type": final_action_type,
                "is_time_grouped": len(time_groups) > 1,
                "group_index": group_idx + 1 if len(time_groups) > 1 else None,
                "total_groups": len(time_groups) if len(time_groups) > 1 else None
            }
            
            # 如果是现有故事，保留更多原有数据的参考
            if is_existing_story:
                story_data["original_story_data"] = existing_story_data
                story_data["time_range_updated"] = existing_story_data.get('time_range') != time_range
                story_data["crawl_date_preserved"] = existing_story_data.get('crawl_date') == crawl_date
            
            all_final_stories.append(story_data)
            
            # 计算实际天数跨度
            actual_days = (latest_time.date() - earliest_time.date()).days + 1
            
            if len(time_groups) > 1:
                print(f"   时间组 {group_idx + 1}: {time_range} (实际跨度: {actual_days}天)")
            else:
                print(f"   完整故事: {time_range} (实际跨度: {actual_days}天)")
            
            print(f"      最终 Story ID: {final_story_id}")
            print(f"      Crawl Date: {crawl_date}")
            print(f"      文章数: {len(grouped_articles)} 篇")
            print(f"      处理类型: {final_action_type}")
    
    print(f"\n总共处理完成 {len(all_final_stories)} 个最终故事")
    return all_final_stories


def _create_time_groups(articles_with_time, time_window_days):
    """
    根据时间窗口将文章分组的内部函数
    """
    time_groups = []
    current_group = []
    current_group_start_time = None
    current_group_end_time = None
    
    for item in articles_with_time:
        article_time = item['datetime']
        
        if current_group_start_time is None:
            # 第一篇文章，开始第一组
            current_group_start_time = article_time
            current_group_end_time = article_time + timedelta(days=time_window_days)
            current_group.append(item)
            print(f"      开始新组: {current_group_start_time.strftime('%Y/%m/%d %H:%M')} - {current_group_end_time.strftime('%Y/%m/%d %H:%M')}")
        else:
            # 检查是否在当前组的时间窗口内
            if article_time < current_group_end_time:
                # 在同一组内
                current_group.append(item)
                print(f"         加入当前组: {article_time.strftime('%Y/%m/%d %H:%M')}")
            else:
                # 超出时间窗口，开始新的一组
                if current_group:
                    time_groups.append(current_group)
                    print(f"      完成组别，包含 {len(current_group)} 篇文章")
                
                # 开始新组
                current_group = [item]
                current_group_start_time = article_time
                current_group_end_time = article_time + timedelta(days=time_window_days)
                print(f"      开始新组: {current_group_start_time.strftime('%Y/%m/%d %H:%M')} - {current_group_end_time.strftime('%Y/%m/%d %H:%M')}")
    
    # 添加最后一组
    if current_group:
        time_groups.append(current_group)
        print(f"      完成最后组别，包含 {len(current_group)} 篇文章")
    
    return time_groups


def save_stories_to_supabase(stories):
    """
    批量保存故事和文章到Supabase数据库
    """
    try:
        saved_stories = 0
        updated_stories = 0
        saved_articles = 0
        
        for story in stories:
            story_id = story["story_id"]
            action_type = story.get("action_type", "create_new_story")
            
            # 根据 action_type 决定如何处理故事
            if action_type == "create_new_story":
                # 保存新故事
                if save_story_to_supabase(story):
                    saved_stories += 1
            elif action_type == "update_existing_story":
                # 更新现有故事的 crawl_date
                try:
                    update_data = {
                        "crawl_date": story["crawl_date"]
                    }
                    # response = supabase.table("stories").update(update_data).eq("story_id", story_id).execute()
                    print(f"   故事 crawl_date 已更新: {story_id}")
                    updated_stories += 1
                except Exception as e:
                    print(f"   更新故事 crawl_date 失败: {e}")
            
            # 保存文章（无论是新故事还是现有故事）
            for article in story["articles"]:
                if save_article_to_supabase(article, story_id):
                    saved_articles += 1
        
        print(f"批量保存完成: {saved_stories} 个新故事, {updated_stories} 个更新故事, {saved_articles} 篇文章")
        return True
        
    except Exception as e:
        print(f"批量保存到Supabase时出错: {e}")
        return False


def save_stories_to_json(stories, filename):
    """
    将故事数据保存到JSON文件
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(stories, f, ensure_ascii=False, indent=2)
        print(f"数据已保存到 {filename}")
        return True
    except Exception as e:
        print(f"保存文件时出错: {e}")
        return False
    
def process_news_pipeline(main_url, category):
    """
    完整的新聞處理管道 - 修正的 Playwright 版本
    """
    print(f"开始处理 {category} 分类的新闻...")
    
    # 步驟1: 獲取所有故事連結
    story_links = get_main_story_links(main_url, category)
    if not story_links:
        print("没有找到任何故事连结")
        return []
    
    # 步驟2: 處理每個故事，獲取所有文章連結
    all_article_links = []
    for story_info in story_links[:10]:
        article_links = get_article_links_from_story(story_info)
        all_article_links.extend(article_links)
    
    if not all_article_links:
        print("没有找到任何文章连结")
        return []
    
    print(f"\n总共收集到 {len(all_article_links)} 篇文章待处理")
    
    # 步驟3: 獲取每篇文章的完整內容 - 修正的错误处理
    final_articles = []
    browser = None
    context = None
    page = None
    consecutive_failures = 0  # 連續失敗計數
    max_consecutive_failures = 3  # 最大連續失敗次數
    
    def create_fresh_browser_and_page():
        """創建新的 browser 和 page 實例"""
        try:
            with sync_playwright() as p:
                browser, context = create_robust_browser(p, headless=True)
                page = context.new_page()
                initialize_page_with_cookies(page)
                return browser, context, page
        except Exception as e:
            print(f"   创建新 Browser/Page 失败: {e}")
            return None, None, None
    
    # 初始化 browser 和 page
    try:
        with sync_playwright() as p:
            browser, context = create_robust_browser(p, headless=True)
            page = context.new_page()
            initialize_page_with_cookies(page)
            
            if not page:
                print("无法创建初始 Page，终止处理")
                return []
            
            try:
                for i, article_info in enumerate(all_article_links, 1):
                    print(f"\n处理文章 {i}/{len(all_article_links)}: {article_info['article_title']}")
                    
                    # 检查 page 是否仍然有效
                    try:
                        # 改进的 page 健康检查 - 使用更安全的方法
                        page_is_healthy = False
                        health_check_attempts = 0
                        max_health_attempts = 3
                        
                        while health_check_attempts < max_health_attempts and not page_is_healthy:
                            try:
                                # 尝试执行简单的页面操作来检查健康状态
                                current_title = page.title()
                                page_is_healthy = True
                            except Exception as health_error:
                                if "closed" in str(health_error).lower() or "target" in str(health_error).lower():
                                    print(f"   Page 已关闭或无效")
                                    break
                                else:
                                    health_check_attempts += 1
                                    time.sleep(1)
                        
                        if not page_is_healthy:
                            raise Exception("Page 健康检查失败")
                            
                    except Exception as e:
                        print(f"   Page 异常，重新创建: {e}")
                        try:
                            page.close()
                            context.close()
                            browser.close()
                        except:
                            pass
                        
                        browser, context = create_robust_browser(p, headless=True)
                        page = context.new_page()
                        initialize_page_with_cookies(page)
                        
                        if not page:
                            print(f"   无法重新创建 Page，跳过剩余 {len(all_article_links) - i + 1} 篇文章")
                            break
                    
                    article_content = get_final_content(article_info, page)
                    
                    if article_content:
                        final_articles.append(article_content)
                        print(f"   成功获取内容")
                        consecutive_failures = 0  # 重置連續失敗計數
                        
                    else:
                        print(f"   无法获取内容")
                        consecutive_failures += 1
                        
                        # 检查是否需要重新创建 page
                        if consecutive_failures >= max_consecutive_failures:
                            print(f"   连续 {consecutive_failures} 次失败，重新创建 Browser/Page...")
                            
                            try:
                                page.close()
                                context.close()
                                browser.close()
                            except:
                                pass
                            
                            browser, context = create_robust_browser(p, headless=True)
                            page = context.new_page()
                            initialize_page_with_cookies(page)
                            
                            if not page:
                                print(f"   无法重新创建 Page，跳过剩余 {len(all_article_links) - i + 1} 篇文章")
                                break
                            
                            consecutive_failures = 0  # 重置計數
                            print(f"   Browser/Page 重新创建完成")
                            
                            # 可选：重新尝试当前文章
                            print(f"   重新尝试处理当前文章...")
                            article_content = get_final_content(article_info, page)
                            if article_content:
                                final_articles.append(article_content)
                                print(f"   重新尝试成功")
                            else:
                                print(f"   重新尝试仍然失败")
                    
                    # 随机延迟
                    time.sleep(random.randint(2, 4))
                    
            except KeyboardInterrupt:
                print(f"\n用户中断处理")
                
            except Exception as e:
                print(f"\n处理过程中发生严重错误: {e}")
                import traceback
                print(f"错误详情:\n{traceback.format_exc()}")
                
            finally:
                try:
                    print(f"\n清理 Playwright 资源...")
                    if page:
                        page.close()
                    if context:
                        context.close()
                    if browser:
                        browser.close()
                    print(f"   Playwright 清理完成")
                except Exception as e:
                    print(f"   Playwright 清理时出现问题: {e}")
    
    except Exception as e:
        print(f"创建 Playwright 实例时出错: {e}")
        return []
    
    print(f"\n文章内容获取完成: 成功 {len(final_articles)}/{len(all_article_links)} 篇")
    
    # 步驟4: 按故事和時間分組
    final_stories = group_articles_by_story_and_time(final_articles, time_window_days=3)
    
    return final_stories

def initialize_page_with_cookies(page):
    """初始化 Playwright Page 并加载 cookies"""
    try:
        # 先访问 Google News 主页
        page.goto("https://news.google.com/")
        time.sleep(2)
        
        # 尝试加载 cookies
        try:
            with open("cookies.json", "r", encoding="utf-8") as f:
                cookies = json.load(f)
            
            # 转换 cookies 格式为 Playwright 格式
            playwright_cookies = []
            for cookie in cookies:
                playwright_cookie = {
                    "name": cookie.get("name"),
                    "value": cookie.get("value"),
                    "domain": cookie.get("domain", ".google.com"),
                    "path": cookie.get("path", "/"),
                }
                
                # 添加可选字段
                if "expires" in cookie:
                    playwright_cookie["expires"] = cookie["expires"]
                if "httpOnly" in cookie:
                    playwright_cookie["httpOnly"] = cookie["httpOnly"]
                if "secure" in cookie:
                    playwright_cookie["secure"] = cookie["secure"]
                    
                playwright_cookies.append(playwright_cookie)
            
            # 添加 cookies 到页面上下文
            page.context.add_cookies(playwright_cookies)
            print("Cookies 加载完成")
            
        except FileNotFoundError:
            print("cookies.json 文件不存在，使用默认设置")
        except Exception as e:
            print(f"加载 cookies 时出错: {e}")
    
    except Exception as e:
        print(f"初始化 Page cookies 时出错: {e}")

def main():
    """
    主函數 - 新聞爬蟲的入口點
    """
    print("="*80)
    print("🌟 Google News 爬蟲程序啟動")
    print("="*80)

    # 配置需要處理的新聞分類
    news_categories = {
        "Politics": "https://news.google.com/topics/CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFZ4ZERBU0JYcG9MVlJYS0FBUAE?hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant",
        "Taiwan News": "https://news.google.com/topics/CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFptTXpJU0JYcG9MVlJYS0FBUAE?hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant",
        "International News": "https://news.google.com/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx1YlY4U0JYcG9MVlJYR2dKVVZ5Z0FQAQ?hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant",
        "Science & Technology": "https://news.google.com/topics/CAAqLAgKIiZDQkFTRmdvSkwyMHZNR1ptZHpWbUVnVjZhQzFVVnhvQ1ZGY29BQVAB?hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant",
        "Lifestyle & Consumer": "https://news.google.com/topics/CAAqJggKIiBDQkFTRWdvSkwyMHZNREUwWkhONEVnVjZhQzFVVnlnQVAB?hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant",
        "Sports": "https://news.google.com/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRFp1ZEdvU0JYcG9MVlJYR2dKVVZ5Z0FQAQ?hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant",
        "Entertainment": "https://news.google.com/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNREpxYW5RU0JYcG9MVlJYR2dKVVZ5Z0FQAQ?hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant",
        "Business & Finance": "https://news.google.com/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx6TVdZU0JYcG9MVlJYR2dKVVZ5Z0FQAQ?hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant",
        "Health & Wellness": "https://news.google.com/topics/CAAqJQgKIh9DQkFTRVFvSUwyMHZNR3QwTlRFU0JYcG9MVlJYS0FBUAE?hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant"
    }

    
    # 可以選擇處理特定分類或全部分類
    # selected_categories = ["Science & Technology"]#, "Business & Finance", "Health & Wellness", "Sports", "Entertainment", "Lifestyle & Consumer", ]#"Taiwan News", "International News", "Politics"]# 可以修改這裡來選擇要處理的分類
    # selected_categories = ["Sports"]
    selected_categories = list(news_categories.keys())  # 處理所有分類
    
    all_final_stories = []
    start_time = time.time()
    
    try:
        for category in selected_categories:
            if category not in news_categories:
                print(f"未知的分类: {category}")
                continue
                
            category_start_time = time.time()
            print(f"\n{'='*60}")
            print(f"开始处理分类: {category}")
            print(f"{'='*60}")
            
            # 处理该分类的新闻
            category_stories = process_news_pipeline(news_categories[category], category)
            
            if category_stories:
                all_final_stories.extend(category_stories)
                category_end_time = time.time()
                category_duration = category_end_time - category_start_time
                
                print(f"\n{category} 分类处理完成!")
                print(f"   获得 {len(category_stories)} 个故事")
                print(f"   耗时: {category_duration:.2f} 秒")
            else:
                print(f"\n{category} 分类处理失败，没有获得任何故事")
            
            # 分类之间的延迟
            if category != selected_categories[-1]:  # 不是最后一个分类
                print(f"\n等待 30 秒后处理下一个分类...")
                time.sleep(30)
        
        # 处理完成后的统计
        total_end_time = time.time()
        total_duration = total_end_time - start_time
        
        print(f"\n{'='*80}")
        print(f"所有分类处理完成!")
        print(f"{'='*80}")
        print(f"最终统计:")
        print(f"   处理分类数: {len(selected_categories)}")
        print(f"   总故事数: {len(all_final_stories)}")
        
        # 统计每个分类的故事数
        category_counts = {}
        total_articles = 0
        for story in all_final_stories:
            category = story['category']
            category_counts[category] = category_counts.get(category, 0) + 1
            total_articles += len(story['articles'])
        
        for category, count in category_counts.items():
            print(f"   {category}: {count} 个故事")
        
        print(f"   总文章数: {total_articles}")
        print(f"   总耗时: {total_duration:.2f} 秒 ({total_duration/60:.1f} 分钟)")
        
        # 保存数据
        if all_final_stories:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            all_final_stories = clean_data(all_final_stories)
            
            # 保存到数据库
            try:
                save_stories_to_supabase(all_final_stories)
                print("数据库保存完成")
            except Exception as e:
                print(f"数据库保存失败: {e}")
            
        else:
            print("没有获得任何故事数据")
    
    except KeyboardInterrupt:
        print(f"\n程序被用户中断")
        if all_final_stories:
            # 即使被中断，也保存已获取的数据
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    except Exception as e:
        print(f"\n程序执行过程中发生错误: {e}")
        import traceback
        print(f"错误详情:\n{traceback.format_exc()}")
    
    finally:
        print(f"\n{'='*80}")
        print(f"Google News 爬蟲程序结束")
        print(f"{'='*80}")

if __name__ == "__main__":
    main()