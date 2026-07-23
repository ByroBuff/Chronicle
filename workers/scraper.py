import trafilatura

def fetch_article_body(url):
    try:
        downloaded = trafilatura.fetch_url(url)

        if downloaded:
            return trafilatura.extract(downloaded)

    except Exception as e:
        print(f"Error scraping {url}: {e}")

    return None