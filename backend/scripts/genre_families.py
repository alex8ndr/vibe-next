"""
Genre Definitions for Vibe Recommendation System.

Strategy: "Sparse Definitions + Smearing"
- We define ~25 core "Family Dimensions" (Axes).
- Each genre is assigned 1-4 families explicitly.
- "Smearing" (neighbor propagation) in process_data.py creates the organic gradients.
  (e.g. Rock <-> Alt-Rock <-> Indie)
- Inline comments indicate results of dataset genre analysis.
- Some genres have lower weights to minimize smearing between unrelated genres.
- ARCHITECTURAL NOTE ON MAGNITUDES:
  1. RATIO (e.g. 0.8:0.4) determines the DIRECTION of the vibe in latent space (post-L2).
  2. MAGNITUDE acts as a "SMEARING VALVE" during the pre-normalization graph phase:
     - High Magnitude (0.8+): Acts as a "Super-Connector." These genres aggressively
       propagate their traits to neighbors and absorb traits from them.
     - Low Magnitude (0.3-0.5): Acts as "Insulation." These are niche/hybrid buffers
       that minimize leakage between unrelated families (e.g. Industrial vs Metal).
     - Single-Dimension Genres: Magnitude here only affects how strongly they anchor
       their neighbors, not their own final strength (due to L2 normalization).

The Dimensions (Output Columns):
1.  rock                (Classic, Mainstream Rock)
2.  alternative         (Indie, Alt, Psych, Shoegaze)
3.  metal               (Heavy, Modern, Nu)
4.  extreme_metal       (Death, Black, Grind)
5.  punk                (Punk, Hardcore)
6.  emo_pop_punk        (Emo, Pop-Punk, Power-Pop)
7.  pop                 (Mainstream, Dance-Pop)
8.  k_pop               (K-Pop, Asian Pop specific ecosystem)
9.  hip_hop             (Rap, Trap, Urban)
10. rnb_soul            (Soul, Funk, R&B, Groove)
11. electronic_house    (House, Disco, Club, EDM)
12. electronic_techno   (Techno, Trance, Industrial, Dark)
13. bass_music          (Dubstep, DnB, Breakbeat)
14. chill_ambient       (Ambient, Chill, New-Age, Sleep, Trippy)
15. acoustic_folk       (Acoustic, Folk, Songwriter, Country)
16. jazz_blues          (Jazz, Blues)
17. latin_tropical      (Salsa, Samba, Afrobeat)
18. latin_regional      (Forro, Sertanejo, Tango)
19. reggae_dub          (Dub, Dancehall, Ska)
20. classical_cinematic (Classical, Opera, Pop-Film, Piano, Show-Tunes)
21. world_regional      (Specific cultural scenes: Indian, European Pop)
22. christian           (CCM, Worship, Christian Rock/Metal)
23. japanese            (J-Pop, J-Rock, Anime)
24. french              (French Pop, Chanson, French Hip-Hop)
25. german              (German Pop, Schlager, German Hip-Hop)
26. progressive         (Prog-Rock, Prog-Metal, Math-Rock, Technical)
"""

GENRE_DEFINITIONS = {
    # =========================================================================
    # ROCK & ALTERNATIVE
    # =========================================================================
    'rock':             {'rock': 1.0},
    'hard-rock':        {'rock': 1.0, 'metal': 0.4}, # Heavy Radio Rock
    'grunge':           {'rock': 0.5, 'alternative': 0.5, 'metal': 0.2}, # 90s Heavy
    'rock-n-roll':      {'rock': 0.5, 'jazz_blues': 0.4, 'pop': 0.2, 'acoustic_folk': 0.2},  # Oldies
    'garage':           {'alternative': 0.3, 'rock': 0.3, 'punk': 0.3, 'acoustic_folk': 0.3}, # Indie/acoustic rock
    
    'alt-rock':         {'alternative': 0.8, 'rock': 0.5}, 
    'indie-pop':        {'alternative': 0.7, 'pop': 0.5, 'electronic_house': 0.2},
    'psych-rock':       {'alternative': 0.4, 'rock': 0.4, 'chill_ambient': 0.2, 'progressive': 0.2},  # Trippy!
    'post-rock':        {'alternative': 0.5, 'chill_ambient': 0.5, 'rock': 0.3, 'progressive': 0.2},  # Atmospheric/cinematic (Mogwai, EITS)
    
    # =========================================================================
    # METAL & PUNK
    # =========================================================================
    'metal':            {'metal': 0.8, 'rock': 0.6, 'punk': 0.3}, # Nu-metal
    'heavy-metal':      {'metal': 1.0, 'rock': 0.4, 'world_regional': 0.2}, # Power/international metal
    'metalcore':        {'metal': 0.8, 'punk': 0.5, 'emo_pop_punk': 0.3},
    
    'death-metal':      {'extreme_metal': 1.0, 'metal': 0.6},
    'black-metal':      {'extreme_metal': 1.0, 'metal': 0.4},
    'grindcore':        {'extreme_metal': 1.0, 'punk': 0.6},
    
    'punk':             {'punk': 0.8, 'emo_pop_punk': 0.5, 'rock': 0.3}, # Pop-punk
    'punk-rock':        {'punk': 0.5, 'rock': 0.5, 'alternative': 0.2}, # Post-punk
    
    'prog-metal':       {'progressive': 0.8, 'metal': 0.5, 'rock': 0.3},
    'math-rock':        {'progressive': 0.7, 'alternative': 0.3, 'metal': 0.3, 'jazz_blues': 0.2},
    'progressive-rock': {'progressive': 0.7, 'rock': 0.5, 'classical_cinematic': 0.2},  # Classic prog (Yes, Porcupine Tree)
    'experimental':     {'alternative': 0.3, 'progressive': 0.3, 'electronic_techno': 0.3, 'chill_ambient': 0.3},  # Avant-garde/experimental (broad connector)
    
    'emo':              {'emo_pop_punk': 0.8, 'punk': 0.3},
    'power-pop':        {'emo_pop_punk': 0.5, 'pop': 0.5, 'rock': 0.3},
    'emo-pop-punk':     {'emo_pop_punk': 0.8, 'punk': 0.4, 'pop': 0.3},
    
    # =========================================================================
    # POP & K-POP
    # =========================================================================
    'pop':              {'pop': 1.0},
    'dance':            {'pop': 0.6, 'electronic_house': 0.6, 'hip_hop': 0.2},
    'synthpop':         {'pop': 0.5, 'electronic_house': 0.5, 'alternative': 0.5},  # Depeche Mode, Pet Shop Boys
    'hyperpop':         {'pop': 0.3, 'electronic_techno': 0.3, 'alternative': 0.3, 'progressive': 0.3},  # 100 gecs, SOPHIE
    'schlager':         {'german': 0.5, 'pop': 0.3, 'world_regional': 0.2}, # German Schlager
    
    'k-pop':            {'k_pop': 1.0, 'pop': 0.4, 'hip_hop': 0.2},
    'cantopop':         {'k_pop': 0.3, 'pop': 0.3, 'world_regional': 0.3},
    
    # =========================================================================
    # HIP-HOP & R&B
    # =========================================================================
    'hip-hop':          {'hip_hop': 1.0},
    'trip-hop':         {'chill_ambient': 0.5, 'electronic_house': 0.5, 'hip_hop': 0.4}, # Downtempo
    'soul':             {'rnb_soul': 1.0, 'jazz_blues': 0.4, 'pop': 0.2},
    'drill':            {'hip_hop': 0.8, 'bass_music': 0.3, 'electronic_techno': 0.2},
    'grime':            {'hip_hop': 0.5, 'bass_music': 0.5, 'electronic_techno': 0.3},
    # =========================================================================
    # ELECTRONIC (House, Techno, Bass)
    # =========================================================================
    'electronic':       {'electronic_house': 0.5, 'electronic_techno': 0.4, 'bass_music': 0.3, 'chill_ambient': 0.2},
    
    'house':            {'electronic_house': 0.9, 'electronic_techno': 0.2, 'rnb_soul': 0.1}, # Keep house anchored to dancefloor electronic
    
    'deep-house':       {'electronic_house': 0.9, 'chill_ambient': 0.4, 'rnb_soul': 0.2},
    'chicago-house':    {'electronic_house': 1.0, 'rnb_soul': 0.4},
    'progressive-house': {'electronic_house': 0.8, 'electronic_techno': 0.4}, # EDM
    'disco':            {'electronic_house': 0.7, 'rnb_soul': 0.6, 'pop': 0.3},
    'club':             {'electronic_house': 0.5, 'pop': 0.3}, # Mixed
    'edm':              {'electronic_house': 0.8, 'pop': 0.3}, # Mainstream/Festival House
    
    'techno':           {'electronic_techno': 1.0},
    'minimal-techno':   {'electronic_techno': 0.9, 'chill_ambient': 0.4},
    'detroit-techno':   {'electronic_techno': 0.9, 'rnb_soul': 0.3},
    'trance':           {'electronic_techno': 0.8, 'electronic_house': 0.4},
    'hardstyle':        {'electronic_techno': 0.8, 'extreme_metal': 0.3},
    
    'industrial':       {'electronic_techno': 0.6, 'alternative': 0.2}, # More technical/electronic
    'industrial-metal': {'metal': 0.4, 'electronic_techno': 0.3}, # Riff-heavy mechanical
    
    'dubstep':          {'bass_music': 1.0, 'electronic_house': 0.3},
    'drum-and-bass':    {'bass_music': 1.0, 'electronic_techno': 0.3},
    'breakbeat':        {'bass_music': 0.8, 'electronic_house': 0.4},
    'synthwave':        {'electronic_techno': 0.5, 'electronic_house': 0.4, 'chill_ambient': 0.3},

    # =========================================================================
    # CHILL & AMBIENT
    # =========================================================================
    'ambient':          {'chill_ambient': 0.8, 'classical_cinematic': 0.4}, # Classical crossover
    'chill':            {'chill_ambient': 0.8, 'hip_hop': 0.3, 'pop': 0.3, 'electronic_house': 0.2},
    'new-age':          {'chill_ambient': 0.9, 'world_regional': 0.3, 'classical_cinematic': 0.2},
    'sleep':            {'chill_ambient': 1.0},
    
    # =========================================================================
    # ACOUSTIC, FOLK, COUNTRY
    # =========================================================================
    'acoustic':         {'acoustic_folk': 1.0},
    'folk':             {'acoustic_folk': 0.8, 'alternative': 0.2},
    'singer-songwriter': {'acoustic_folk': 0.8, 'pop': 0.3},
    'songwriter':       {'acoustic_folk': 0.9, 'pop': 0.1, 'rock': 0.1},  # Small genre
    'country':          {'acoustic_folk': 0.5, 'jazz_blues': 0.2, 'pop': 0.1, 'rock': 0.1},
    'guitar':           {'acoustic_folk': 0.5, 'rock': 0.5, 'jazz_blues': 0.2},
    
    # =========================================================================
    # JAZZ & BLUES
    # =========================================================================
    'jazz':             {'jazz_blues': 1.0},
    'jazz-fusion':      {'jazz_blues': 0.7, 'rock': 0.4, 'electronic_house': 0.3},
    'blues':            {'jazz_blues': 0.5, 'rock': 0.5}, # Blues-rock
    
    # =========================================================================
    # LATIN
    # =========================================================================
    'salsa':            {'latin_tropical': 1.0, 'jazz_blues': 0.3},
    'samba':            {'latin_tropical': 1.0, 'jazz_blues': 0.2},
    'afrobeat':         {'latin_tropical': 0.8, 'rnb_soul': 0.4, 'electronic_house': 0.2}, # Afrobeats tends to sit closer to R&B/dance than indie-alt
    
    'forro':            {'latin_regional': 1.0, 'acoustic_folk': 0.4, 'jazz_blues': 0.2},
    'sertanejo':        {'latin_regional': 0.9, 'acoustic_folk': 0.5, 'pop': 0.3},
    'tango':            {'latin_regional': 1.0, 'classical_cinematic': 0.4},

    # =========================================================================
    # REGGAE & DUB
    # =========================================================================
    'dancehall':        {'reggae_dub': 0.8, 'hip_hop': 0.5},
    'ska':              {'reggae_dub': 0.4, 'latin_tropical': 0.4, 'punk': 0.4}, # Latin ska
    
    # =========================================================================
    # CLASSICAL & CINEMATIC
    # =========================================================================
    'classical':        {'classical_cinematic': 1.0},
    'opera':            {'classical_cinematic': 1.0, 'world_regional': 0.2},
    'piano':            {'classical_cinematic': 0.8, 'acoustic_folk': 0.4, 'chill_ambient': 0.3},
    'show-tunes':       {'classical_cinematic': 0.8, 'pop': 0.4},
    
    # =========================================================================
    # WORLD / REGIONAL (lower weights for less smearing)
    # =========================================================================
    'world':            {'world_regional': 0.8, 'acoustic_folk': 0.3},  # Generic world music catch-all
    'indian':           {'world_regional': 0.7, 'classical_cinematic': 0.4, 'pop': 0.4}, # Indian pop and Bollywood/film scenes
    'german':           {'world_regional': 0.3, 'german': 0.7, 'classical_cinematic': 0.3, 'metal': 0.2, 'electronic_techno': 0.2},
    'french':           {'world_regional': 0.3, 'french': 0.7, 'hip_hop': 0.2, 'electronic_house': 0.2, 'classical_cinematic': 0.1},
    'spanish':          {'world_regional': 0.3, 'latin_tropical': 0.2, 'rock': 0.1, 'pop': 0.1}, # Spanish pop rock
    'swedish':          {'world_regional': 0.3, 'pop': 0.1, 'rock': 0.1}, # Pop and Rock
    'romance':          {'world_regional': 0.3, 'classical_cinematic': 0.2, 'acoustic_folk': 0.2}, # Russian Romance
    'flamenco':         {'acoustic_folk': 0.6, 'world_regional': 0.5, 'classical_cinematic': 0.3},

    # =========================================================================
    # CHRISTIAN 
    # =========================================================================
    'gospel':           {'christian': 0.8, 'rnb_soul': 0.3, 'acoustic_folk': 0.2},
    'ccm':              {'christian': 0.8, 'pop': 0.5, 'acoustic_folk': 0.2},
    'christian-rock':   {'christian': 0.8, 'rock': 0.5, 'emo_pop_punk': 0.2},
    'christian-metal':  {'christian': 0.8, 'metal': 0.6, 'punk': 0.2},

    # =========================================================================
    # DATASET FINDINGS
    # =========================================================================

    # Mostly Dubstep, a bit of Reggae Dub
    'dub':              {'bass_music': 0.8, 'electronic_house': 0.2, 'reggae_dub': 0.2},
    
    # Mostly Electronic Alterative
    'electro':          {'electronic_house': 0.6, 'electronic_techno': 0.4, 'alternative': 0.2},  # Actual electro (Kraftwerk, Justice)

    # Mostly Brazilian Funk (Funk Carioca) & Party
    'funk':             {'latin_regional': 0.7, 'hip_hop': 0.5},

    # Added Genre
    'reggae':           {'reggae_dub': 1.0, 'rock': 0.2},

    # Groove Metal with some electronic house
    'groove':           {'metal': 0.8, 'rock': 0.4},

    # Darkwave
    'goth':             {'alternative': 0.5, 'electronic_techno': 0.4, 'chill_ambient': 0.2, 'rock': 0.2, 'metal': 0.2},

    # Indian Playback + All soundtracks
    'pop-film':         {'world_regional': 0.4, 'classical_cinematic': 0.4, 'pop': 0.2},

    # Sad Sierreño
    'sad':              {'latin_regional': 1.0, 'latin_tropical': 0.3, 'acoustic_folk': 0.2},

    # =========================================================================
    # NEW LANGUAGE/STYLE SPLITS
    # =========================================================================
    'french-hip-hop':   {'hip_hop': 0.7, 'french': 0.6, 'pop': 0.2},
    'german-hip-hop':   {'hip_hop': 0.7, 'german': 0.6, 'electronic_techno': 0.1},
    'latin-urban':      {'hip_hop': 0.7, 'latin_tropical': 0.6, 'pop': 0.4}, # Reggaeton/Trap
    
    'j-pop':            {'japanese': 0.8, 'pop': 0.5},
    'j-rock':           {'japanese': 0.8, 'rock': 0.5, 'alternative': 0.2},

    'hardcore-hip-hop': {'hip_hop': 0.6, 'rnb_soul': 0.3}, # Aggressive Rap (Wu-Tang, DMX)
    'hardcore-punk':    {'punk': 0.6, 'metal': 0.2},
    'post-hardcore':    {'punk': 0.5, 'rock': 0.4, 'emo_pop_punk': 0.4, 'metal': 0.2}, 
    
    # Generic 'hardcore' pointing to punk to catch stragglers
    'hardcore':         {'punk': 0.6, 'metal': 0.3}, 
}
