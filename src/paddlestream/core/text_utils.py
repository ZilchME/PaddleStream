import re


def normalize_text(text: str) -> str:
    """规范化文本：移除特殊字符、处理正斜杠、规范化大数字中的逗号。"""
    if not text:
        return ""

    pattern = re.compile(r'[a-zA-Z_"\'`<>《》【】\[\]{}@#$^&*]+')
    text = pattern.sub("", text).strip()

    if "/" in text:
        text = text.replace("/", " ")

    text = re.sub(
        r"(?<!\d)(\d{1,3}(?:,\d{3})+)(?![,\d])",
        lambda m: m.group(1).replace(",", ""),
        text,
    )
    return text
