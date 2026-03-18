"""Locale/language policy config for genre tag mapping.

Design goals:
- Locale tokens provide language hints.
- Genre should primarily come from the non-locale remainder of the tag.
- Only keep explicit exception maps for non-compositional phrases.
"""

from __future__ import annotations

LOCALE_TO_LANG: dict[str, str | None] = {
    # European — Romance
    "french": "fr", "francais": "fr", "français": "fr",
    "francaise": "fr", "française": "fr",
    "spanish": "es", "espanol": "es", "español": "es",
    "italian": "it", "italiano": "it", "italiana": "it",
    "portuguese": "pt",
    "catalan": "ca", "basque": "eu", "galician": "gl",
    "romanian": "ro",

    # European — Germanic
    "german": "de", "deutsch": "de", "deutscher": "de",
    "swedish": "sv", "norwegian": "no", "danish": "da",
    "icelandic": "is",
    "dutch": "nl", "flemish": "nl",
    "austrian": "de", "swiss": "de",
    "mundart": "de",

    # European — Finno-Ugric / Baltic
    "finnish": "fi", "estonian": "et",
    "latvian": "lv", "lithuanian": "lt",
    "hungarian": "hu",

    # European — Slavic
    "czech": "cs", "slovak": "sk", "polish": "pl",
    "serbian": "sr", "croatian": "hr", "bosnian": "bs",
    "slovenian": "sl", "bulgarian": "bg", "yugoslav": "sh",
    "ukrainian": "uk", "belarusian": "be", "russian": "ru",

    # European — Other
    "greek": "el", "albanian": "sq",
    "turkish": "tr", "georgian": "ka", "armenian": "hy",
    "belgian": "fr",
    "afrikaans": "af",

    # Asian — East
    "chinese": "zh", "taiwanese": "zh", "taiwan": "zh",
    "mandarin": "zh", "cantonese": "zh", "c-": "zh",
    "korean": "ko", "k-": "ko",
    "japanese": "ja", "j-": "ja",

    # Asian — Southeast
    "indonesian": "id", "thai": "th", "vietnamese": "vi",
    "filipino": "tl", "pinoy": "tl",
    "malaysian": "ms", "malay": "ms", "singaporean": None,

    # Asian — South
    "indian": "hi", "desi": "hi",
    "tamil": "ta", "telugu": "te", "punjabi": "pa",
    "bengali": "bn", "hindi": "hi", "malayalam": "ml",
    "pakistani": "ur", "nepali": "ne", "sri lankan": "si",

    # Middle East
    "persian": "fa", "arab": "ar", "arabic": "ar",
    "lebanese": "ar", "palestinian": "ar", "syrian": "ar",
    "arabesk": "tr",
    "israeli": "he", "egyptian": "ar", "moroccan": "ar",

    # Latin American
    "latin": "es", "latino": "es", "latina": "es",
    "mexican": "es", "colombian": "es",
    "argentine": "es", "argentino": "es",
    "argentina": "es", "argentinian": "es",
    "peruvian": "es", "chilean": "es",
    "venezuelan": "es", "ecuadorian": "es",
    "bolivian": "es", "uruguayan": "es",
    "paraguayan": "es", "cuban": "es",
    "puerto rican": "es", "dominican": "es",
    "panamanian": "es", "costa rican": "es",

    # Brazilian
    "brazilian": "pt",

    # Caribbean
    "jamaican": "en", "caribbean": "en",
    "trinidadian": "en", "haitian": "fr",

    # African
    "nigerian": "en", "african": None, "afro": None,
    "south african": None, "ghanaian": "en",
    "kenyan": "sw", "tanzanian": "sw",
    "ethiopian": "am", "congolese": "fr",
    "senegalese": "fr",
}

# Non-compositional locale phrases that cannot be reliably interpreted via
# locale stripping + standard genre mapping.
LOCALE_PHRASE_RULES: dict[str, tuple[str | None, str | None]] = {
    "pop urbaine": ("hip-hop", "fr"),
    "pop electronico": ("latin-urban", "es"),
    "pop electrónico": ("latin-urban", "es"),
    "rock nacional": ("rock", None),
    "pop nacional": ("pop", None),
    "deutschrap": ("hip-hop", "de"),
    "neue deutsche welle": ("synthpop", "de"),
    "mpb": ("samba", "pt"),
    "funk carioca": ("funk", "pt"),
    "electro latino": ("latin-urban", "es"),
    "latin jazz": ("salsa", None),
    "latin soul": ("soul", None),
    "taiwanese indigenous": ("folk", "zh"),
    # CJK genre aliases that aren't prefix-strippable
    "jpop": ("pop", "ja"),
    "kpop": ("pop", "ko"),
    "cantopop": ("pop", "zh"),
    "mandopop": ("pop", "zh"),
    "anime": ("pop", "ja"),
    "anime score": ("pop", "ja"),
    "otacore": ("pop", "ja"),
    "vocaloid": ("pop", "ja"),
    "utaite": ("pop", "ja"),
    "visual kei": ("rock", "ja"),
    "j-division": ("pop", "ja"),
}

# Tokens removed after locale stripping (e.g. "rock en espanol" -> "rock").
LOCALE_CONNECTOR_TOKENS: tuple[str, ...] = (
    "en", "de", "da", "do", "del", "la", "el", "y", "the",
)

# Targeted scene remaps after locale stripping resolves a broad base genre.
LOCALE_SCENE_REMAPS: dict[str, dict[str, str]] = {}
