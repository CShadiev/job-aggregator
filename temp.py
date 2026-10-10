import asyncio
from urllib.request import Request, urlopen


async def download_index():
    URL = (
        "https://hh.ru/search/vacancy?"
        "text=python+%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA"
        "&salary=&ored_clusters=true&order_by=publication_time&label=accept_labor_contract"
        "&experience=between3And6&experience=moreThan6&search_period=7&accept_temporary=false"
        "&employment_form=FULL&area=1&hhtmFrom=vacancy_search_list&hhtmFromLabel=vacancy_search_line"
    )
    # URL = "https://hh.ru/vacancy/136496402"
    req = Request(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        },
    )
    with urlopen(req, timeout=30) as resp:
        body = resp.read()
        with open("index.html", "w", encoding="utf-8") as file:
            file.write(body.decode("utf-8"))


async def extract_job_ids():
    import re

    import bs4

    """
    <div id="138202123" class="vacancy-card--n77Dj8TY8VIUF0yM font-inter">
    """

    with open("index.html", encoding="utf-8") as file:
        soup = bs4.BeautifulSoup(file, "html.parser")
        # Find all tags with a class starting with 'vacancy-card--'
        elements = soup.find_all(class_=re.compile(r"^vacancy-card--"))

        # Extract the id attributes (using get() to handle missing ids safely)
        vacancy_ids = [el["id"] for el in elements if "id" in el.attrs]

        print(f"total number: {len(vacancy_ids)}")
        for vacancy_id in vacancy_ids:
            print(vacancy_id)


async def download_job_details(job_id):
    URL = f"https://hh.ru/vacancy/{job_id}"
    req = Request(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        },
    )
    with urlopen(req, timeout=30) as resp:
        body = resp.read()
        with open("job_details.html", "w", encoding="utf-8") as file:
            file.write(body.decode("utf-8"))


async def extract_job_details():
    import bs4

    with open("job_details.html", encoding="utf-8") as file:
        soup = bs4.BeautifulSoup(file, "html.parser")

        title = soup.find("div", class_="vacancy-title")
        if not title:
            return
        title = title.find("h1")
        if not title:
            return
        title = title.get_text(separator=" ", strip=True)

        print(f"title: {title}")

        company = soup.find("span", class_="vacancy-company-name")
        if not company:
            return
        company = company.get_text(separator=" ", strip=True)
        print(f"company: {company}")

        job_details = soup.find("div", class_="vacancy-description")
        if not job_details:
            return

        with open("job_details.txt", "w", encoding="utf-8") as file:
            file.write(job_details.get_text(separator="\n", strip=True))


if __name__ == "__main__":
    asyncio.run(extract_job_details())
