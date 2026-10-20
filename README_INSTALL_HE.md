# כיצד למסור את החבילה ל־Codex

## צור פרויקט עצמאי בשם `sharons`

צור תיקייה או repository חדש בשם `sharons`, מחוץ ל־Compass ומחוץ ל־Mental Trainer. חלץ לתוכו את תוכן החבילה. בשלב הראשון התיקייה תכיל הוראות ומסמכי תכנון בלבד; Codex יציע את שלד Django לאחר Phase 0.

## לפני העתקה

1. ודא שהתיקייה החדשה אינה נמצאת בתוך repository אחר.
2. חלץ את החבילה כך ש־`AGENTS.md` יהיה בשורש `sharons`.
3. אל תעתיק לתוכה קוד מ־Compass, מ־Mental Trainer או מפרויקט מחקר ישן.
4. שמור repositories קיימים כפרויקטים חיצוניים; בעתיד הם יירשמו ב־Project Registry.

## פריסה לוגית

```text
<sharons-repository>/
├── AGENTS.md
├── agents/
│   └── research/
│       └── AGENTS.md
└── docs/
    ├── chief_of_staff/
    │   ├── SPEC_HE.md
    │   └── ENGINEERING_PLAN_HE.md
    └── research/
        └── RESEARCH_MANAGER_SPEC.md
```

התיקייה `agents/research/` מכילה בשלב זה הוראות בלבד. Codex יציע את קוד המחקר לאחר אישור המבנה.

## הפרומפט הראשון ל־Codex

```text
קרא את AGENTS.md בשורש ואת כל קובצי AGENTS.md החלים על הקבצים שתבדוק.
קרא את מסמכי docs/chief_of_staff ואת docs/research/RESEARCH_MANAGER_SPEC.md.

בצע Phase 0 בלבד:
1. ודא שזה repository עצמאי וחדש ואינו מקונן בתוך מוצר אחר.
2. בדוק את קובצי ההוראות והתכנון ללא יצירת קוד.
3. הצע שלד Django מינימלי עם apps: core, portfolio, governance, operations ו-agents.
4. הגדר Project Registry שמחבר repositories חיצוניים בלי להעתיק אותם.
5. הכן תוכנית הקמה ל-PostgreSQL ושני ADRs: גבולות repositories וחוזי project adapters.
6. הצע vertical slice ראשון: רישום Project → קליטת בקשה ב-CoS → Task DRAFT → AuditEvent.
7. אל תבצע scaffolding, חיבור DB או התקנת תשתית לפני אישורי.

חזור אליי עם הממצאים, הקבצים שיושפעו, הסיכונים והחלטות שנדרשות ממני.
אל תחבר Gmail, אל תתקין broker, אל תשנה authentication, אל תחבר ספק סליקה
ואל תפרוס דבר לפני אישור מפורש.
```

## מדוע הפיצול הזה נחוץ

- קובץ השורש מגדיר ממשל, הרשאות וארכיטקטורה לכל Sharons.
- הקובץ התחומי מגדיר התנהגות מחקר רק במקום שבו היא רלוונטית.
- המפרט הארוך נשמר כמסמך ייחוס במקום להעמיס על הוראות Codex בכל משימה.
- Chief of Staff ו־Research Manager אינם מתחרים: הראשון מנהל את החברה; השני מנהל workflow מחקר שקיבל משימה מאושרת.

## Pre-mortem

| כשל | מניעה |
|---|---|
| Sharons נוצר בתוך repository אחר | יצירה בתיקייה עצמאית ובדיקת Git root |
| קובץ מחקר משפיע על כל repository | שמירתו כתיעוד והוראות תחומיות בתת־עץ |
| קוד מוצר מועתק לתוך Sharons | Project Registry ו־adapters בלבד |
| CoS ו־Research Manager שניהם מחלקים משאבים | CoS מנהל חברה; Research Manager מנהל scope מחקרי מאושר |
| Codex מתחיל לבנות הכול | Phase 0 בלבד בפרומפט הראשון |
