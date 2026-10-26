"""Conservative bilingual contract-expiry counts over governed upload tables."""
from __future__ import annotations

from datetime import date, datetime, timezone
import re
import unicodedata

import pandas as pd

from backend.core.local_question_engine import LocalTableAnswer


def _normalize(value) -> str:
    text = unicodedata.normalize("NFKC", str(value)).lower()
    text = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", text)
    return text.translate(str.maketrans("أإآىة٠١٢٣٤٥٦٧٨٩", "ااايه0123456789")).strip()


def _key(value) -> str:
    return re.sub(r"[^a-z0-9\u0621-\u064a]", "", _normalize(value))


def _words(value) -> set[str]:
    return {
        word[2:] if word.startswith("ال") and len(word) > 3 else word
        for word in re.findall(r"[a-z]+|[\u0621-\u064a]+", _normalize(value))
    }


_STATUS = {"contractstatus", "حالهالعقد", "حالهعقد"}
_DATES = {"contractenddate", "contractexpirydate", "contractexpirationdate", "contractexpiry",
          "تاريخانتهاءالعقد", "تاريخنهايهالعقد"}
_IDS = {"contractid", "contractnumber", "contractno", "رقمالعقد", "معرفالعقد"}
_EXPIRED = {_key(value) for value in ("expired", "منتهي", "منتهية", "منتهى", "منتهي الصلاحية", "منتهي المفعول")}
_KNOWN_STATUSES = _EXPIRED | {_key(value) for value in (
    "active", "valid", "renewed", "pending", "draft", "cancelled", "canceled",
    "terminated", "suspended", "expiring soon", "ساري", "سارية", "ساري المفعول",
    "سارية المفعول", "نشط", "نشطة", "فعال", "فعالة", "ملغي", "ملغى",
    "معلق", "قيد التجديد", "مجدد", "تم التجديد", "موقوف", "قريب الانتهاء",
)}
_ALLOWED = _words(
    "كم عدد عقد عقود منتهي منتهية المنتهية انتهاء انتهت عندي لدينا لدي عندنا يوجد هناك "
    "الان حاليا اليوم في الملف ملف المرفوع بيانات هذه هذا من فضلك رجاء سجلات سجل بتاريخ حتى "
    "how many count number total expired contract contracts are there the of in this uploaded file "
    "data please show me records record today now currently as"
)


def answer_contract_count(
    question: str,
    files: dict[str, pd.DataFrame] | None,
    pii_columns: dict[str, set[str]] | None = None,
) -> LocalTableAnswer | None:
    words = _words(question)
    if not files or not (
        words & {"كم", "عدد", "count", "many", "number"}
        and words & {"عقد", "عقود", "contract", "contracts"}
        and words & {"منتهي", "منتهيه", "انتهت", "expired"}
    ):
        return None
    arabic = bool(re.search(r"[\u0600-\u06ff]", question))
    def choose(en, ar):
        return ar if arabic else en
    def clarify(en, ar, filename="", rows=0):
        return LocalTableAnswer(choose(en, ar), "", "clarify", filename, rows, [], [], priority=True)

    # Never bypass the mixed-PDF/OCR trust boundary through a new intent.
    if any(frame.attrs.get("pdf_extraction", {}).get("requires_numeric_review") for frame in files.values()):
        return clarify(
            "Scanned figures require explicit table review before contract counts. Review the rows or upload a verified table.",
            "تتطلب الأرقام الممسوحة مراجعة الجدول صراحةً قبل عدّ العقود. راجع الصفوف أو ارفع جدولاً موثوقاً.",
        )
    dates = re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", _normalize(question))
    if len(dates) > 1:
        return clarify("Specify one ISO reference date.", "حدد تاريخاً مرجعياً واحداً بصيغة YYYY-MM-DD.")
    # Match contract_expiry_engine's UTC calendar-date convention so the
    # dashboard and local chat do not disagree around midnight.
    reference = datetime.now(timezone.utc).date()
    if dates:
        try:
            reference = date.fromisoformat(dates[0])
        except ValueError:
            return clarify("The reference date is invalid.", "التاريخ المرجعي غير صالح.")
    stripped = re.sub(r"\d{4}-\d{2}-\d{2}", "", _normalize(question))
    for filename in files:
        stripped = stripped.replace(_normalize(filename), "")
    if _words(stripped) - _ALLOWED:
        return clarify(
            "This contract count needs clarification: additional filters or negation must be specified explicitly. I will not substitute an unfiltered count.",
            "يحتاج طلب عدّ العقود إلى توضيح: حدد الشروط الإضافية أو النفي صراحةً. لن أستبدله بعدد غير مُرشَّح.",
        )

    candidates = []
    for filename, frame in files.items():
        excluded = (pii_columns or {}).get(filename, set())
        columns = [c for c in frame.columns if str(c) not in excluded]
        keys = {_key(c) for c in columns}
        contract_context = any("contract" in key or "عقد" in key for key in keys) or bool(
            _words(filename) & {"contract", "contracts", "عقد", "عقود"}
        )
        score = (3 if keys & (_STATUS | _DATES) else 1 if contract_context else 0)
        if _normalize(filename) in _normalize(question):
            score += 10
        if score:
            candidates.append((score, filename, frame, columns))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    if not candidates:
        return clarify(
            "No governed contract-status or contract-end-date column was found. Use ContractStatus or ContractEndDate (ISO dates).",
            "لم أجد عموداً متاحاً لحالة العقد أو تاريخ انتهائه. استخدم ContractStatus أو ContractEndDate بتواريخ YYYY-MM-DD.",
        )
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return clarify("Mention the file/sheet to count; multiple sources match.", "اذكر الملف أو الورقة المطلوب عدّها؛ توجد مصادر متعددة متطابقة.")
    _, filename, frame, columns = candidates[0]
    status_columns = [c for c in columns if _key(c) in _STATUS]
    date_columns = [c for c in columns if _key(c) in _DATES]
    if not status_columns and not date_columns:
        status_columns = [c for c in columns if _key(c) in {"status", "الحاله", "حاله"}]
        date_columns = [c for c in columns if _key(c) in {"enddate", "expirydate", "expirationdate", "تاريخالانتهاء"}]
    selected = date_columns if dates else status_columns or date_columns
    if len(selected) != 1:
        return clarify("Specify one contract-status/end-date column.", "حدد عموداً واحداً لحالة العقد أو تاريخ انتهائه.", filename, len(frame))
    column = selected[0]
    warnings = []
    if column in status_columns and not dates:
        values = frame[column].map(_key)
        if values.isin({"", "nan", "none", "nat", "na"}).any():
            return clarify("Some contract statuses are missing. Correct them before counting.", "بعض حالات العقود مفقودة. صحّحها قبل العدّ.", filename, len(frame))
        if not values.isin(_KNOWN_STATUSES).all():
            return clarify(
                "Some status labels are unrecognized. Specify which labels mean expired before counting.",
                "بعض تسميات الحالة غير معروفة. حدد أي التسميات تعني «منتهي» قبل العدّ.",
                filename, len(frame),
            )
        expired = values.isin(_EXPIRED)
        criterion = choose(f'{column}: explicitly marked expired', f'{column}: الحالة المسجلة «منتهي»')
        warnings.append(choose("Count uses recorded status labels, not an inferred end-date rule.", "يعتمد العدّ على الحالة المسجلة، وليس على استنتاج من تاريخ الانتهاء."))
    else:
        def parse(value):
            if not isinstance(value, (str, date, datetime, pd.Timestamp)) or value is pd.NaT:
                return None
            if isinstance(value, (datetime, pd.Timestamp)):
                return value.date()
            if isinstance(value, date):
                return value
            value = _normalize(value)
            if not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[t ])", value):
                return None
            try:
                return datetime.fromisoformat(value).date()
            except ValueError:
                return None
        parsed = frame[column].map(parse)
        if parsed.isna().any():
            return clarify(
                "Some contract end dates are missing, invalid or ambiguous. Supply ISO YYYY-MM-DD dates; no partial count was calculated.",
                "بعض تواريخ انتهاء العقود مفقودة أو غير صالحة أو ملتبسة. استخدم YYYY-MM-DD؛ لم يُحسب عدد جزئي.",
                filename, len(frame),
            )
        expired = parsed.map(lambda value: value < reference)
        criterion = choose(f"{column} < {reference.isoformat()} (UTC)", f"{column} قبل {reference.isoformat()} (UTC)")
        warnings.append(choose("A contract ending on the reference date is not counted as expired until that day ends.", "العقد الذي ينتهي في التاريخ المرجعي لا يُعد منتهياً قبل نهاية ذلك اليوم."))
    identifiers = [c for c in columns if _key(c) in _IDS]
    if len(identifiers) > 1:
        return clarify("Multiple contract identifiers were found; specify which one defines a contract.", "وُجدت عدة معرّفات للعقد؛ حدد المعرّف الذي يعرّف العقد.", filename, len(frame))
    if identifiers:
        identifier = identifiers[0]
        ids = frame[identifier].astype("string").str.strip()
        if ids.isna().any() or ids.eq("").any():
            return clarify("Some contract identifiers are missing; correct them before a distinct count.", "بعض معرّفات العقود مفقودة؛ صحّحها قبل حساب العدد الفريد.", filename, len(frame))
        classifications = pd.DataFrame({"id": ids, "expired": expired})
        if classifications.groupby("id")["expired"].nunique().gt(1).any():
            return clarify("A contract has conflicting expiry classifications across rows. Correct duplicates first.", "توجد حالات انتهاء متعارضة للعقد نفسه عبر الصفوف. صحّح التكرارات أولاً.", filename, len(frame))
        count = int(ids[expired].nunique())
        label = choose("Expired contracts", "عدد العقود المنتهية")
        used = [str(column), str(identifier)]
    else:
        count = int(expired.sum())
        label = choose("Expired contract records", "عدد سجلات العقود المنتهية")
        used = [str(column)]
        warnings.append(choose("No contract identifier was available; this is a row count, assuming one contract per row.", "لا يتوفر معرّف للعقد؛ هذا عدد الصفوف بافتراض عقد واحد لكل صف."))
    return LocalTableAnswer(
        f"{label}: {count:,}.", f"{count:,}\n{criterion}",
        "contract_expired_count", filename, len(frame), used, warnings, priority=True,
    )
