"""
Genre Definitions for Vibe Recommendation System.

Strategy: "Sparse Definitions + Smearing"
- We define ~22 core "Family Dimensions" (Axes).
- Each genre is assigned 1-2 families explicitly.
- "Smearing" (neighbor propagation) in process_data.py creates the organic gradients.
  (e.g. Rock <-> Alt-Rock <-> Indie)
- Inline comments indicate results of dataset genre analysis.
- Some genres have lower weights to miminize smearing between unrelated genres.

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
22. comedy_spoken       (Comedy, Spoken Word)
"""

GENRE_DEFINITIONS = {
    # =========================================================================
    # ROCK & ALTERNATIVE
    # =========================================================================
    'rock':             {'rock': 0.8, 'alternative': 0.5},
    'hard-rock':        {'rock': 0.8, 'metal': 0.5},
    'rock-n-roll':      {'rock': 0.5, 'jazz_blues': 0.4, 'pop': 0.2, 'acoustic_folk': 0.2},  # Oldies
    'garage':           {'alternative': 0.5, 'rock': 0.4, 'punk': 0.3, 'acoustic_folk': 0.3}, # Indie/acoustic rock
    
    'alt-rock':         {'alternative': 0.6, 'rock': 0.5, 'metal': 0.2}, # Heavy alt-rock
    'psych-rock':       {'alternative': 0.5, 'rock': 0.5, 'chill_ambient': 0.3},  # Trippy!
    'indie-pop':        {'alternative': 1.0, 'pop': 0.5},
    
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
    'hardcore':         {'punk': 0.3, 'hip_hop': 0.3, 'metal': 0.1}, # Hardcore hip hop and punk
    'punk-rock':        {'punk': 0.5, 'rock': 0.5, 'alternative': 0.5}, # Post-punk
    
    'emo':              {'emo_pop_punk': 0.8, 'hip_hop': 0.4, 'punk': 0.3}, # Emo rap
    'power-pop':        {'emo_pop_punk': 0.7, 'rock': 0.5, 'pop': 0.4},
    
    # =========================================================================
    # POP & K-POP
    # =========================================================================
    'pop':              {'pop': 1.0},
    'dance':            {'pop': 0.6, 'electronic_house': 0.6},
    'party':            {'pop': 0.2, 'electronic_house': 0.2, 'world_regional': 0.2}, # German Schlager
    
    'k-pop':            {'k_pop': 1.0, 'pop': 0.4, 'hip_hop': 0.2},
    'cantopop':         {'k_pop': 0.5, 'pop': 0.2, 'world_regional': 0.3},
    
    # =========================================================================
    # HIP-HOP & R&B
    # =========================================================================
    'hip-hop':          {'hip_hop': 1.0},
    'trip-hop':         {'chill_ambient': 0.6, 'electronic_house': 0.5, 'hip_hop': 0.2}, # Downtempo
    
    'soul':             {'rnb_soul': 1.0, 'jazz_blues': 0.4, 'pop': 0.2},
    'gospel':           {'rnb_soul': 0.6, 'acoustic_folk': 0.4, 'classical_cinematic': 0.2, 'world_regional': 0.2},
    
    # =========================================================================
    # ELECTRONIC (House, Techno, Bass)
    # =========================================================================
    'electronic':       {'electronic_house': 0.5, 'electronic_techno': 0.4, 'bass_music': 0.3, 'chill_ambient': 0.2},
    
    'house':            {'electronic_house': 0.4, 'hip_hop': 0.2, 'pop': 0.2}, # Mixed genre (lower weights)
    
    'deep-house':       {'electronic_house': 0.9, 'chill_ambient': 0.4, 'rnb_soul': 0.2},
    'chicago-house':    {'electronic_house': 1.0, 'rnb_soul': 0.4},
    'progressive-house': {'electronic_house': 0.8, 'electronic_techno': 0.4}, # EDM
    'disco':            {'electronic_house': 0.7, 'rnb_soul': 0.6, 'pop': 0.3},
    'club':             {'electronic_house': 0.5, 'pop': 0.3}, # Mixed
    'edm':              {'electronic_house': 0.7, 'pop': 0.4, 'bass_music': 0.4, 'alternative': 0.2},
    
    'techno':           {'electronic_techno': 1.0},
    'minimal-techno':   {'electronic_techno': 0.9, 'chill_ambient': 0.4},
    'detroit-techno':   {'electronic_techno': 0.9, 'rnb_soul': 0.3},
    'trance':           {'electronic_techno': 0.8, 'electronic_house': 0.4},
    'hardstyle':        {'electronic_techno': 0.8, 'extreme_metal': 0.3},
    
    'industrial':       {'electronic_techno': 0.8, 'metal': 0.5},
    
    'dubstep':          {'bass_music': 1.0, 'electronic_house': 0.3},
    'drum-and-bass':    {'bass_music': 1.0, 'electronic_techno': 0.3},
    'breakbeat':        {'bass_music': 0.8, 'electronic_house': 0.4},

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
    'folk':             {'acoustic_folk': 1.0, 'rock': 0.3},
    'singer-songwriter': {'acoustic_folk': 0.9, 'pop': 0.3},
    'songwriter':       {'acoustic_folk': 0.9, 'pop': 0.3, 'rock': 0.2},  # Small genre
    'country':          {'acoustic_folk': 0.8, 'rock': 0.3, 'pop': 0.2},
    'guitar':           {'acoustic_folk': 0.5, 'rock': 0.5, 'jazz_blues': 0.2},
    
    # =========================================================================
    # JAZZ & BLUES
    # =========================================================================
    'jazz':             {'jazz_blues': 1.0},
    'blues':            {'jazz_blues': 0.5, 'rock': 0.5}, # Blues-rock
    
    # =========================================================================
    # LATIN
    # =========================================================================
    'salsa':            {'latin_tropical': 1.0, 'jazz_blues': 0.3},
    'samba':            {'latin_tropical': 1.0, 'jazz_blues': 0.2},
    'afrobeat':         {'latin_tropical': 0.8, 'alternative': 0.4, 'rnb_soul': 0.2}, # Latin alternative
    
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
    'show-tunes':       {'classical_cinematic': 0.6, 'pop': 0.6},
    
    # =========================================================================
    # WORLD / REGIONAL (lower weights for less smearing)
    # =========================================================================
    'indian':           {'world_regional': 0.3, 'classical_cinematic': 0.1, 'pop': 0.1}, # Indian pop and Bollywood
    'german':           {'world_regional': 0.3, 'classical_cinematic': 0.3, 'metal': 0.2, 'electronic_techno': 0.2}, # Score and Metal
    'french':           {'world_regional': 0.3, 'hip_hop': 0.2, 'electronic_house': 0.2, 'classical_cinematic': 0.1},
    'spanish':          {'world_regional': 0.3, 'latin_tropical': 0.2, 'rock': 0.1, 'pop': 0.1}, # Spanish pop rock
    'swedish':          {'world_regional': 0.2, 'pop': 0.1, 'rock': 0.1}, # Pop and Rock
    'romance':          {'world_regional': 0.3, 'classical_cinematic': 0.2, 'acoustic_folk': 0.2}, # Russian Romance

    # =========================================================================
    # OTHER
    # =========================================================================
    'comedy':           {'comedy_spoken': 1.0},


    # =========================================================================
    # DATASET FINDINGS
    # =========================================================================

    # Mostly Dubstep, a bit of Reggae Dub
    'dub':              {'bass_music': 0.8, 'electronic_house': 0.2, 'reggae_dub': 0.2},
    
    # Mostly Electronic Alterative
    'electro':          {'pop': 0.6, 'electronic_house': 0.5, 'alternative': 0.4},

    # Mostly G-Funk
    'funk':             {'hip_hop': 0.6, 'rnb_soul': 0.5, 'latin_tropical': 0.2},

    # Groove Metal with some electronic house
    'groove':           {'metal': 0.8, 'electronic_house': 0.4},

    # Symphonic and Gothic Metal
    'goth':             {'metal': 0.7, 'classical_cinematic': 0.4, 'alternative': 0.3},

    # Indian Playback
    'pop-film':         {'world_regional': 1.0, 'classical_cinematic': 0.4, 'pop': 0.3},

    # Sad Sierreño
    'sad':              {'latin_regional': 1.0, 'latin_tropical': 0.3, 'acoustic_folk': 0.2},
}