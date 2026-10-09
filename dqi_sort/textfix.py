"""Minimal text repair for intake.

Only two things are changed; everything else (HTML tags, entities, LaTeX) is left as submitted:

- encoding damage (mojibake), e.g. "√É‚Ä∞cole" -> "École", "Many‚ÄëBody" -> "Many-Body" (non-breaking hyphen)
- HTML comments, which are invisible on the APS site anyway: editor tags such as <!-- notionvc: ... --> in
  titles, and Microsoft Office conditional comments (<!--[if gte msEquation 12]> ... <![endif]-->), which
  can hold tens of kilobytes of equation markup; the readable fallback text that follows them is kept
"""
import re
import ftfy

_FTFY = ftfy.TextFixerConfig(unescape_html=False, uncurl_quotes=False, fix_latin_ligatures=False,
                             fix_character_width=False, fix_line_breaks=False, normalization=None, explain=False)

# UTF-8 three-byte sequences read as Mac Roman, which ftfy misses when they sit alone
# (e.g. U+2011 non-breaking hyphen -> "‚Äë"). A lead byte E0-EF is one of the first set,
# a continuation byte 80-BF one of the second.
_MR_LEAD = '‡·‚„‰ÂÊÁËÈÍÎÏÌÓÔ'
_MR_CONT = 'ÄÅÇÉÑÖÜáàâäãåçéèêëíìîïñóòôöõúùûü†°¢£§•¶ß®©™´¨≠ÆØ∞±≤≥¥µ∂∑∏π∫ªºΩæø'
_MR3 = re.compile(f'[{_MR_LEAD}][{_MR_CONT}]{{2}}')
# two-byte case, only for accented Latin letters inside a word ("Hyypp√§" -> "Hyyppä"), so that real
# math such as "√π" is left alone
_MR2 = re.compile(f'(?<=[A-Za-z])√[{_MR_CONT}]|√[{_MR_CONT}](?=[A-Za-z])')

# signatures that suggest damage is still present after repair
_SUSPECT = re.compile(r'Ã[\u0080-¿]|â€|‚Ä|√[©®†°§¨≠]|�')

_COMMENT = re.compile(r'<!--\[if [^\]]*\]>.*?<!\[endif\]-->|<!--.*?-->', re.S)
_OFFICE_MARKER = re.compile(r'<!\[if [^\]]*\]>|<!\[endif\]>')


def _fix_mr3(m):
    try:
        return m.group(0).encode('mac_roman').decode('utf-8')
    except UnicodeError:
        return m.group(0)


def _fix_mr2(m):
    try:
        c = m.group(0).encode('mac_roman').decode('utf-8')
    except UnicodeError:
        return m.group(0)
    return c if c.isalpha() and '\u00c0' <= c <= '\u00ff' else m.group(0)


def repair_encoding(s):
    """Return the text with mojibake repaired (unchanged if none found)."""
    if not s or s.isascii():
        return s
    s = _MR3.sub(_fix_mr3, ftfy.fix_text(s, _FTFY))
    return _MR2.sub(_fix_mr2, s)


def strip_comments(s):
    if not s or '<!' not in s:
        return s
    return _OFFICE_MARKER.sub('', _COMMENT.sub('', s))


def suspect(s):
    """True if the text still looks garbled."""
    return bool(s and _SUSPECT.search(s))


def clean(s):
    """Return (text, fixes): the repaired text and a list of what was changed."""
    s = s or ''
    fixes = []
    t = strip_comments(s)
    if t != s:
        fixes.append('removed hidden HTML comments')
    u = repair_encoding(t)
    if u != t:
        fixes.append('repaired encoding damage')
    return u.strip(), fixes
