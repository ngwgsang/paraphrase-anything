---
name: simplify
description: Plain language with short sentences and common words for a broad audience.
relax: [length, overlap]
---

# Simplify

## Purpose
Make text understandable to non-experts, second-language readers, or a quick skim.

## Voice rules
- One idea per sentence; mostly under 20 words.
- Common words; active voice; concrete subjects.
- Keep technical terms the reader needs. Explain them only if the original does.

## Do / Don't
- Do split compound sentences and unpack nominalisations.
- Do keep every number, unit, and condition ("only if", "unless").
- Don't drop caveats to make it shorter; that is a meaning change.
- Don't add explanations or examples the original lacks.

## Language notes
- **ja:** prefer common kanji and short です/ます sentences; avoid stacked 〜であるため.
- **vi:** avoid Sino-Vietnamese abstractions when a plain word exists; keep sentences short.

## Examples

### en 1
**Input:** Notwithstanding the aforementioned limitations, the proposed methodology demonstrates a 15% improvement in throughput.
**Output:** The method has some limits. Even so, it makes throughput 15% better.

### en 2
**Input:** Individuals who have not completed the registration process prior to 1 June will be ineligible to participate.
**Output:** You must register before 1 June. If you do not, you cannot take part.

### vi 1
**Input:** Việc triển khai hệ thống đòi hỏi phải hoàn tất giai đoạn kiểm thử trước ngày 20/08.
**Output:** Bạn cần kiểm thử xong hệ thống trước ngày 20/08. Sau đó mới triển khai được.

### ja 1
**Input:** 当該手続きは、申請書の提出をもって完了するものとする。
**Output:** 申請書を出すと、手続きは終わります。
