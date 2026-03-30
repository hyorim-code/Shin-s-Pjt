"""
메가밥스 구내식당 메뉴 슬랙 알림 봇
- 매일 아침 오늘의 점심 메뉴를 슬랙 채널에 전송
"""

import json
import os
import re
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup

MENU_URL = "https://www.megabobs.com/"
WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")  # 쉼표로 구분해서 여러 채널 가능

CATEGORY_LABELS = {
    "COURSE_1": "코스 1",
    "COURSE_2": "코스 2",
    "TAKE_OUT": "테이크아웃",
}


def fetch_menu_data():
    """사이트 HTML에서 메뉴 데이터를 추출 (Next.js App Router __next_f 방식)"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(MENU_URL, headers=headers, timeout=10)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for script in soup.find_all("script"):
        content = script.string or ""
        if "menus" not in content:
            continue

        # self.__next_f.push([1, "...이스케이프된 JSON..."]) 에서 문자열 추출
        match = re.search(r'self\.__next_f\.push\(\[1,"(.*)"\]\)', content, re.DOTALL)
        if not match:
            continue

        # \\" → " 언이스케이프
        inner = match.group(1).replace('\\"', '"')

        # "menus":[...] 부분 추출
        menu_match = re.search(r'"menus":\[', inner)
        if not menu_match:
            continue

        start = menu_match.start() + len('"menus":')
        raw = inner[start:]

        # 배열의 끝 괄호 위치 탐색
        depth, end_idx = 0, 0
        for i, ch in enumerate(raw):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break

        if not end_idx:
            continue

        try:
            return json.loads(raw[:end_idx])
        except json.JSONDecodeError:
            continue

    raise ValueError("메뉴 데이터를 찾을 수 없습니다. 사이트 구조가 변경되었을 수 있습니다.")


def get_todays_menu(menus):
    """오늘 날짜의 점심 메뉴만 필터링"""
    today = datetime.now().strftime("%Y-%m-%d")
    return [m for m in menus if m.get("date") == today and m.get("meal") == "LUNCH"]


CATEGORY_ICONS = {
    "COURSE_1": "🥘",
    "COURSE_2": "🍜",
    "TAKE_OUT": "🥡",
}


def format_slack_message(todays_menus):
    """슬랙 Block Kit 메시지 포맷 생성"""
    today = datetime.now()
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = weekdays[today.weekday()]
    date_str = today.strftime(f"%m월 %d일 ({weekday})")

    if not todays_menus:
        return {
            "text": f"🍱 {date_str} 오늘의 점심 메뉴\n\n메뉴 정보가 없습니다."
        }

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🍱  {date_str}  오늘의 점심 메뉴",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🔔 *맛있는 점심 시간이 다가왔어요!*  오늘의 메뉴를 확인하세요 😋",
            },
        },
        {"type": "divider"},
    ]

    category_order = ["COURSE_1", "COURSE_2", "TAKE_OUT"]
    sorted_menus = sorted(
        todays_menus,
        key=lambda m: category_order.index(m["category"])
        if m["category"] in category_order
        else 99,
    )

    for menu in sorted_menus:
        category = CATEGORY_LABELS.get(menu["category"], menu["category"])
        icon = CATEGORY_ICONS.get(menu["category"], "🍽️")
        items = menu.get("items", [])
        if not items:
            continue

        menu_lines = []
        for item in items:
            name = item.get("name", "")
            kcal = item.get("kcal")
            if kcal:
                menu_lines.append(f"　▸ {name}　*{kcal} kcal*")
            else:
                menu_lines.append(f"　▸ {name}")

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{icon}  *{category}*\n" + "\n".join(menu_lines),
                },
            }
        )
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"📍 <{MENU_URL}|메가밥스 구내식당>　|　⏰ 매일 오전 11시 자동 발송",
                }
            ],
        }
    )

    return {"blocks": blocks, "text": f"🍱 {date_str} 오늘의 점심 메뉴"}


def send_to_slack(message):
    """슬랙 웹훅으로 메시지 전송 (쉼표로 구분된 여러 채널 지원)"""
    if not WEBHOOK_URL:
        raise ValueError(
            "SLACK_WEBHOOK_URL 환경변수가 설정되지 않았습니다.\n"
            "export SLACK_WEBHOOK_URL='url1,url2'"
        )
    urls = [u.strip() for u in WEBHOOK_URL.replace("\n", ",").split(",") if u.strip()]
    for url in urls:
        response = requests.post(url, json=message, timeout=10)
        response.raise_for_status()
        print(f"슬랙 전송 완료! ({url[:50]}...)")


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 메뉴 봇 실행 시작")

    try:
        print("메뉴 데이터 수집 중...")
        menus = fetch_menu_data()
        print(f"전체 메뉴 {len(menus)}개 항목 수집 완료")

        todays_menus = get_todays_menu(menus)
        print(f"오늘 메뉴: {len(todays_menus)}개 카테고리")

        message = format_slack_message(todays_menus)

        if not todays_menus:
            print("오늘 메뉴가 없습니다. (주말이거나 메뉴 미등록)")

        send_to_slack(message)

    except Exception as e:
        print(f"오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
