"""
Artist genre reassignments for correcting mislabeled artists in Spotify data.

Maps genre -> list of artists who should be assigned that genre.
Applied in filter_data.py (removes from exclusion) and process_data.py (applies genre).

Format: {"target_genre": ["Artist1", "Artist2", ...]}
"""

GENRE_REASSIGNMENTS: dict[str, list[str]] = {
    # ===========================================================================
    # CHRISTIAN MUSIC (from alt-rock, rock, pop)
    # ===========================================================================
    "ccm": [
        "I AM THEY", "We Are Messengers", "for KING & COUNTRY",
        "Bethel Music", "Casting Crowns", "Chris Tomlin", "MercyMe",
        "Newsboys", "Third Day", "TobyMac", "Jeremy Camp",
        "Sidewalk Prophets", "Matthew West", "Michael W. Smith",
        "Steven Curtis Chapman", "Natalie Grant", "Phil Wickham",
        "Matt Redman", "Kari Jobe", "Passion", "Crowder", "Lecrae",
        "Building 429", "DC Talk", "Audio Adrenaline",
    ],
    "christian-rock": [
        "Skillet", "Switchfoot", "Relient K", "Thousand Foot Krutch",
        "Kutless", "Disciple", "Flyleaf", "Fireflight", "Demon Hunter",
        "Red", "P.O.D.", "Pillar", "Anberlin", "The Classic Crime",
        "Lacey Sturm", "Stryper", "Petra", "Hawk Nelson",
        "Family Force 5", "The Almost", "House of Heroes",
    ],
    "christian-metal": [
        "Underoath", "August Burns Red", "The Devil Wears Prada",
        "As I Lay Dying", "Silent Planet", "Living Sacrifice", "Emery",
    ],

    # ===========================================================================
    # METAL (from groove, goth, alt-rock genres)
    # ===========================================================================
    "heavy-metal": [
        "Pantera", "Lamb of God", "Five Finger Death Punch", "Mastodon",
        "Soulfly", "Crowbar", "Chimaira", "Ektomorf", "Black Label Society",
        "Sepultura", "Prong", "Fear Factory", "Machine Head", "Six Feet Under",
        "Exodus", "Testament", "Overkill", "Sodom", "Kreator", "Slayer",
        "Korn", "Deftones",
    ],
    "metal": [
        # Symphonic/Orchestral metal (from goth genre)
        "Nightwish", "Within Temptation", "Epica", "Delain", "Kamelot",
        "Lacuna Coil", "Katatonia", "Sirenia", "Anathema", "The Crxshadows",
        "Amaranthe", "HammerFall", "Lord Of The Lost", "Tarja",
        "Lacrimas Profundere", "The 69 Eyes",
    ],

    # ===========================================================================
    # REGGAE/DUB (from dub genre - split between actual reggae vs electronic)
    # ===========================================================================
    "dancehall": [
        "Midnite", "Gregory Isaacs", "Burning Spear", "Lee 'Scratch' Perry",
        "King Tubby", "Barrington Levy", "Scientist", "10 Ft. Ganja Plant",
        "The Bush Chemists", "Jah Wobble", "Culture", "Vibronics",
        "Peter Tosh", "Freddie McGregor", "Sly & Robbie", "John Holt",
    ],
    "dubstep": [
        # Electronic producers misclassified in dub
        "Tritonal", "Zeds Dead", "Seven Lions", "Kayzo", "Borgore",
        "Virtual Riot", "ILLENIUM", "Flux Pavilion", "Barely Alive",
    ],

    # ===========================================================================
    # ELECTRONIC/DANCE (from electro genre - split by actual style)
    # ===========================================================================
    "electronic": [
        "CHVRCHES", "Metric", "Janelle Monáe", "Alan Walker", "Melanie Martinez",
        "VNV Nation", "Daft Punk", "Thievery Corporation",
        # Synthpop/electronic pop artists misclassified elsewhere
        "Little Dragon", "The Knife", "Metronomy",
    ],
    "chill": [
        "Bonobo", "Moby", "Massive Attack", "DJ Shadow", "RJD2", 
        "Groove Armada", "Emancipator",
    ],
    "edm": [
        # Major progressive house/trance producers
        "Armin van Buuren", "Tiësto", "Kaskade", "David Guetta",
    ],

    # ===========================================================================
    # R&B/SOUL/HIP-HOP (from funk genre - split by actual style)
    # ===========================================================================
    "soul": [
        "Stevie Wonder", "Jill Scott", "Luther Vandross", "Marvin Gaye",
        "Raheem DeVaughn", "Gerald Levert", "The Wood Brothers",
    ],
    "hip-hop": [
        "Snoop Dogg", "2Pac", "Lil Rob", "Ice Cube", "Suga Free", "Mr. Capone-E",
    ],
    "rock": [
        "Red Hot Chili Peppers", "Incubus", "Clutch", "311", "Limp Bizkit",
        "zebrahead",
    ],
    "jazz": [
        "Cory Wong", "Vulfpeck", "Snarky Puppy", "Lettuce", "Galactic",
    ],

    # ===========================================================================
    # INDIE/ALTERNATIVE (from garage genre)
    # ===========================================================================
    "alt-rock": [
        "Arctic Monkeys", "The Growlers", "Wavves", "Inner Wave",
        "Deerhoof", "Electric Six",
    ],

    # ===========================================================================
    # WORLD MUSIC (from pop-film and sad genres)
    # ===========================================================================
    "indian": [
        "Sonu Nigam", "Madhu Balakrishnan", "Karthik", "Udit Narayan",
        "Unnikrishnan", "Unni Menon", "Lata Mangeshkar", "Sujatha",
        "Shreya Ghoshal", "Arijit Singh", "Kishore Kumar", "Vijay Yesudas",
        "Saindhavi", "D. Imman", "G. V. Prakash", "Tippu", "Harris Jayaraj",
        "Haricharan", "Kumar Sanu", "Anuradha Paudwal", "Deva",
        "Anuradha Sriram", "Rahat Fateh Ali Khan", "KK",
    ],
    "sertanejo": [
        "Alameos de la Sierra", "Julin lvarez y su Norteo Banda", "Carin Leon",
        "Hijos De Barron", "Lenin Ramrez", "Fuerza Regida", "Alta Consigna",
        "La Energia Nortena", "Edwin Luna y La Trakalosa de Monterrey",
        "Perdidos De Sinaloa", "Luis R Conriquez", "La Fiera de Ojinaga",
        "LEGADO 7", "Junior H", "Gerardo Coronel", "Grupo Marca Registrada",
        "T3R Elemento", "Alfredo Olivas", "Grupo Arriesgado", "Adriel Favela",
        "Natanael Cano", "Virlan Garcia", "La Santa Grifa", "Eslabon Armado",
    ],
}


def get_reassigned_artists() -> set[str]:
    """Return set of all artists that have genre reassignments."""
    artists = set()
    for artist_list in GENRE_REASSIGNMENTS.values():
        artists.update(artist_list)
    return artists


def get_artist_genre(artist_name: str) -> str | None:
    """Get reassigned genre for an artist, or None if not reassigned."""
    for genre, artists in GENRE_REASSIGNMENTS.items():
        if artist_name in artists:
            return genre
    return None
