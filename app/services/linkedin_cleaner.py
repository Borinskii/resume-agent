from __future__ import annotations

import re
from dataclasses import dataclass


NOISE_EXACT = {
    # Russian UI
    "0 уведомлений",
    "поиск",
    "главная",
    "сеть",
    "вакансии",
    "сообщения",
    "уведомления",
    "профиль",
    "для бизнеса",
    "ресурсы",
    "улучшить профиль",
    "добавить раздел",
    "интересует",
    "контактные сведения",
    "аналитика",
    "действия",
    "создать публикацию",
    "показать все",
    "просмотреть",
    "установить контакт",
    "отслеживать",
    "начать",
    "добавить услуги",
    "язык профиля",
    "english",
    "русский",
    "выбрать язык",
    "написать сообщение",
    # English UI
    "home",
    "search",
    "my network",
    "jobs",
    "messaging",
    "notifications",
    "me",
    "work",
    "for business",
    "resources",
    "improve profile",
    "add section",
    "open to",
    "contact info",
    "analytics",
    "activity",
    "create post",
    "show all",
    "see all",
    "view all",
    "view profile",
    "connect",
    "follow",
    "following",
    "follower",
    "followers",
    "more",
    "message",
    "send message",
    "skip",
    "save",
    "saved",
    "edit",
    "share profile",
    "ad",
    "promoted",
    "sponsored",
    "post",
    "comment",
    "like",
    "repost",
    "send",
    "see translation",
    "see less",
    "see more",
    "show more",
    "show less",
    "log in",
    "join now",
    "sign in",
    "sign up",
    "language",
    "english (us)",
    "english (uk)",
    "deutsch",
    "français",
    "español",
    "italiano",
    "português",
    # Other common UI tokens
    "loading",
    "no posts to show",
}

NOISE_CONTAINS = (
    # Russian
    "linkedin corporation",
    "попробовать premium",
    "доступно только вам",
    "узнайте",
    "здесь будут отображаться",
    "чьи профили также просматривали",
    "люди, которых вы можете знать",
    "вам может понравиться",
    "страницы для вас",
    "о компании",
    "специальные возможности",
    "решения для найма",
    "условия",
    "рекламные предпочтения",
    "центр безопасности",
    "возникли вопросы",
    "посетите справочный центр",
    "управление настройками",
    "прозрачность рекомендаций",
    "вы на экране",
    "статус: в сети",
    # English
    "linkedin corporation",
    "try premium",
    "premium for free",
    "available to you only",
    "viewers in the past",
    "people you may know",
    "people also viewed",
    "you may like",
    "pages for you",
    "promoted by",
    "about company",
    "accessibility",
    "talent solutions",
    "ad choices",
    "advertising",
    "user agreement",
    "privacy policy",
    "cookie policy",
    "copyright policy",
    "brand policy",
    "guest controls",
    "community guidelines",
    "help center",
    "recommendation transparency",
    "you're on the screen",
    "status is online",
    "status is reachable",
    "see this in",
    "translate",
    "what's on your mind",
    "your dashboard",
    "private to you",
    "all-star",
    "skill assessments",
    "open to work",
    "anyone on or off linkedin",
    "members can see",
    "promoted post",
    "© 20",
)

STOP_SECTIONS = (
    # Russian
    "чьи профили также просматривали",
    "люди, которых вы можете знать",
    "вам может понравиться",
    "страницы для вас",
    "о компании",
    # English — sections after which we drop noise
    "people you may know",
    "people also viewed",
    "you may like",
    "pages for you",
    "others named",
    "more profiles for you",
    "explore content",
    "messaging is now in your inbox",
)


COUNTER_SUFFIXES = (
    # Russian
    " отслеживающих",
    " контактов",
    " подписчиков",
    # English
    " followers",
    " following",
    " connections",
    " mutual connections",
    " connection",
    " contacts",
)


_TIME_AGO_RE = re.compile(
    r"^\d+\s*(mo|w|d|h|m|y|min|mins|sec|hour|hours|day|days|week|weeks|month|months|year|years|г|нед|дн|ч|мес)\.?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CleanedLinkedInText:
    text: str
    removed_lines: int
    truncated: bool

    @property
    def status_detail(self) -> str:
        if not self.text:
            return "Manual LinkedIn text did not contain usable profile evidence after cleaning."
        detail = f"Manual LinkedIn text cleaned; removed {self.removed_lines} UI/noise lines."
        if self.truncated:
            detail += " Long paste was truncated for analysis."
        return detail


def clean_linkedin_profile_text(value: str, max_lines: int = 120, max_chars: int = 6000) -> CleanedLinkedInText:
    if not value.strip():
        return CleanedLinkedInText(text="", removed_lines=0, truncated=False)

    kept: list[str] = []
    removed = 0
    truncated = False

    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = " ".join(raw_line.strip().split())
        if not line:
            continue

        lower = line.lower()
        if any(marker in lower for marker in STOP_SECTIONS):
            removed += 1
            break
        if is_noise_line(line):
            removed += 1
            continue

        kept.append(line)
        if len(kept) >= max_lines:
            truncated = True
            break

    text = "\n".join(kept)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0]
        truncated = True

    return CleanedLinkedInText(text=text.strip(), removed_lines=removed, truncated=truncated)


def is_noise_line(line: str) -> bool:
    lower = line.lower()
    if lower in NOISE_EXACT:
        return True
    if any(fragment in lower for fragment in NOISE_CONTAINS):
        return True
    if any(lower.endswith(suffix) for suffix in COUNTER_SUFFIXES):
        return True
    if _TIME_AGO_RE.match(lower):
        return True
    if len(line) <= 2:
        return True
    return False
