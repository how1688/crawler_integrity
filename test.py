from pygooglenews import GoogleNews

# 建立 GoogleNews 實例
gn = GoogleNews(lang='ch', country='TW')

# 取得頭條新聞
top_stories = gn.top_news()
print("Top Stories:")
for entry in top_stories['entries']:
    print("-", entry['title'])

# 按主題取得新聞（例如：商業）
business_news = gn.topic_headlines('business')
print("\nBusiness Headlines:")
for entry in business_news['entries']:
    print("-", entry['title'])

# 根據地點取得新聞（例如：New York）
local_news = gn.geo_headlines('New York')
print("\nLocal News in New York:")
for entry in local_news['entries']:
    print("-", entry['title'])
