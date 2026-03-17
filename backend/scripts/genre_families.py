"""
Genre Definitions for Vibe Recommendation System.

Strategy: "Sparse Definitions + Smearing"
- We define ~24 core "Family Dimensions" (Axes).
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
8.  hip_hop             (Rap, Trap, Urban)
9.  rnb_soul            (Soul, Funk, R&B, Groove)
10. electronic_house    (House, Disco, Club, EDM)
11. electronic_techno   (Techno, Trance, Industrial, Dark)
12. bass_music          (Dubstep, DnB, Breakbeat)
13. chill_ambient       (Ambient, Chill, New-Age, Sleep, Trippy)
14. acoustic_folk       (Acoustic, Folk, Songwriter, Country)
15. jazz_blues          (Jazz, Blues)
16. latin_tropical      (Salsa, Samba, Afrobeat)
17. latin_regional      (Forro, Sertanejo, Tango)
18. reggae_dub          (Dub, Dancehall, Ska)
19. classical_cinematic (Classical, Opera, Pop-Film, Piano, Show-Tunes)
20. world_regional      (Regional/cultural scenes where language alone is insufficient)
21. christian           (CCM, Worship, Christian Rock/Metal)
22. progressive         (Prog-Rock, Prog-Metal, Math-Rock, Technical)
"""

GENRE_DEFINITIONS = {
    # =========================================================================
    # ROCK & ALTERNATIVE
    # =========================================================================
    'rock':             {'rock': 1.0},
    'hard-rock':        {'rock': 1.0, 'metal': 0.4},
    'grunge':           {'rock': 0.5, 'alternative': 0.5, 'metal': 0.2},
    'rock-n-roll':      {'rock': 0.5, 'jazz_blues': 0.4, 'pop': 0.2, 'acoustic_folk': 0.2},
    'garage':           {'alternative': 0.3, 'rock': 0.3, 'punk': 0.3, 'acoustic_folk': 0.3},
    
    'alt-rock':         {'alternative': 0.8, 'rock': 0.5}, 
    'indie-pop':        {'alternative': 0.7, 'pop': 0.5, 'electronic_house': 0.2},
    'shoegaze':         {'alternative': 0.7, 'chill_ambient': 0.5, 'rock': 0.3, 'pop': 0.3},
    'psych-rock':       {'alternative': 0.4, 'progressive': 0.4, 'rock': 0.4, 'chill_ambient': 0.2},
    'post-rock':        {'alternative': 0.5, 'chill_ambient': 0.5, 'rock': 0.3, 'progressive': 0.2},
    
    # =========================================================================
    # METAL & PUNK
    # =========================================================================
    'metal':            {'metal': 0.8, 'rock': 0.6, 'punk': 0.3},
    'heavy-metal':      {'metal': 1.0, 'rock': 0.4, 'extreme_metal': 0.2},
    'metalcore':        {'metal': 0.8, 'punk': 0.5, 'emo_pop_punk': 0.3},
    
    'death-metal':      {'extreme_metal': 1.0, 'metal': 0.6},
    'black-metal':      {'extreme_metal': 1.0, 'metal': 0.4},
    'grindcore':        {'extreme_metal': 1.0, 'punk': 0.6},
    
    'punk':             {'punk': 0.8, 'emo_pop_punk': 0.5, 'rock': 0.3}, 
    'punk-rock':        {'punk': 0.5, 'rock': 0.5, 'alternative': 0.2}, 
    
    'prog-metal':       {'progressive': 0.8, 'metal': 0.5, 'rock': 0.3},
    'math-rock':        {'progressive': 0.7, 'alternative': 0.3, 'metal': 0.3, 'jazz_blues': 0.2},
    'progressive-rock': {'progressive': 0.7, 'rock': 0.5, 'classical_cinematic': 0.2}, 
    'experimental':     {'alternative': 0.3, 'progressive': 0.3, 'electronic_techno': 0.3, 'chill_ambient': 0.3}, 
    
    'emo':              {'emo_pop_punk': 0.8, 'punk': 0.3},
    'power-pop':        {'emo_pop_punk': 0.5, 'pop': 0.5, 'rock': 0.3},
    
    # =========================================================================
    # POP & K-POP
    # =========================================================================
    'pop':              {'pop': 1.0},
    'dance':            {'pop': 0.6, 'electronic_house': 0.6, 'hip_hop': 0.2},
    'synthpop':         {'pop': 0.5, 'electronic_house': 0.5, 'alternative': 0.5},  # Depeche Mode, Pet Shop Boys
    'hyperpop':         {'pop': 0.3, 'electronic_techno': 0.3, 'alternative': 0.3, 'progressive': 0.3},  # 100 gecs, SOPHIE
    'schlager':         {'pop': 0.6, 'acoustic_folk': 0.3, 'classical_cinematic': 0.1}, # German Schlager
    
    'k-pop':            {'pop': 0.5, 'hip_hop': 0.3, 'electronic_house': 0.2, 'rnb_soul': 0.2},
    'cantopop':         {'pop': 0.6, 'rnb_soul': 0.3, 'electronic_house': 0.2},
    
    # =========================================================================
    # HIP-HOP & R&B
    # =========================================================================
    'hip-hop':          {'hip_hop': 1.0},
    'trip-hop':         {'chill_ambient': 0.5, 'electronic_house': 0.5, 'hip_hop': 0.4},
    'soul':             {'rnb_soul': 1.0, 'jazz_blues': 0.4, 'pop': 0.2},
    'drill':            {'hip_hop': 0.8, 'bass_music': 0.3, 'electronic_techno': 0.2},
    'grime':            {'hip_hop': 0.5, 'bass_music': 0.5, 'electronic_techno': 0.3},
    # =========================================================================
    # ELECTRONIC (House, Techno, Bass)
    # =========================================================================
    'electronic':       {'electronic_house': 0.5, 'electronic_techno': 0.4, 'bass_music': 0.3, 'chill_ambient': 0.2},
    
    'house':            {'electronic_house': 0.85, 'electronic_techno': 0.15, 'rnb_soul': 0.2},
    
    'deep-house':       {'electronic_house': 0.82, 'chill_ambient': 0.5, 'rnb_soul': 0.2},
    'progressive-house': {'electronic_house': 0.68, 'electronic_techno': 0.38, 'progressive': 0.35},
    'disco':            {'electronic_house': 0.7, 'rnb_soul': 0.6, 'pop': 0.3},
    'edm':              {'electronic_house': 0.6, 'pop': 0.35, 'electronic_techno': 0.2},
    
    'techno':           {'electronic_techno': 0.95},
    'minimal-techno':   {'electronic_techno': 0.82, 'chill_ambient': 0.5},
    'trance':           {'electronic_techno': 0.72, 'electronic_house': 0.35, 'chill_ambient': 0.25},
    'hardstyle':        {'electronic_techno': 0.6, 'extreme_metal': 0.35, 'bass_music': 0.25},
    
    'industrial':       {'electronic_techno': 0.45, 'alternative': 0.4, 'metal': 0.2},
    'industrial-metal': {'metal': 0.4, 'electronic_techno': 0.3},
    
    'dubstep':          {'bass_music': 0.9, 'electronic_house': 0.25, 'electronic_techno': 0.05},
    'drum-and-bass':    {'bass_music': 0.75, 'electronic_techno': 0.45, 'electronic_house': 0.15},
    'breakbeat':        {'bass_music': 0.7, 'electronic_house': 0.45, 'hip_hop': 0.2},
    'synthwave':        {'electronic_techno': 0.35, 'electronic_house': 0.35, 'chill_ambient': 0.45, 'alternative': 0.2},

    # =========================================================================
    # CHILL & AMBIENT
    # =========================================================================
    'ambient':          {'chill_ambient': 0.8, 'classical_cinematic': 0.4},
    'chill':            {'chill_ambient': 0.8, 'hip_hop': 0.3, 'pop': 0.3, 'electronic_house': 0.2},
    'new-age':          {'chill_ambient': 0.9, 'classical_cinematic': 0.2},
    'sleep':            {'chill_ambient': 1.0},
    
    # =========================================================================
    # ACOUSTIC, FOLK, COUNTRY
    # =========================================================================
    'acoustic':         {'acoustic_folk': 0.95, 'chill_ambient': 0.15},
    'folk':             {'acoustic_folk': 0.8, 'alternative': 0.3},
    'singer-songwriter': {'acoustic_folk': 0.7, 'pop': 0.4, 'alternative': 0.2},
    'country':          {'acoustic_folk': 0.5, 'jazz_blues': 0.3, 'rock': 0.3, 'pop': 0.2},
    'guitar':           {'acoustic_folk': 0.5, 'rock': 0.5, 'jazz_blues': 0.2},
    
    # =========================================================================
    # JAZZ & BLUES
    # =========================================================================
    'jazz':             {'jazz_blues': 1.0},
    'jazz-fusion':      {'jazz_blues': 0.7, 'rock': 0.4, 'electronic_house': 0.3},
    'blues':            {'jazz_blues': 0.5, 'rock': 0.5},
    
    # =========================================================================
    # LATIN
    # =========================================================================
    'salsa':            {'latin_tropical': 0.85, 'jazz_blues': 0.35, 'pop': 0.1},
    'samba':            {'latin_tropical': 0.72, 'jazz_blues': 0.15, 'latin_regional': 0.32, 'acoustic_folk': 0.1},
    'afrobeat':         {'latin_tropical': 0.8, 'rnb_soul': 0.4, 'electronic_house': 0.2},
    
    'forro':            {'latin_regional': 0.75, 'acoustic_folk': 0.45, 'jazz_blues': 0.2},
    'sertanejo':        {'latin_regional': 0.65, 'acoustic_folk': 0.55, 'pop': 0.35},
    'tango':            {'latin_regional': 1.0, 'classical_cinematic': 0.4},

    # =========================================================================
    # REGGAE & DUB
    # =========================================================================
    'dancehall':        {'reggae_dub': 0.8, 'hip_hop': 0.5},
    'ska':              {'reggae_dub': 0.4, 'latin_tropical': 0.4, 'punk': 0.4},
    
    # =========================================================================
    # CLASSICAL & CINEMATIC
    # =========================================================================
    'classical':        {'classical_cinematic': 1.0},
    'opera':            {'classical_cinematic': 0.8, 'acoustic_folk': 0.2},
    'piano':            {'classical_cinematic': 0.8, 'acoustic_folk': 0.4, 'chill_ambient': 0.3},
    'show-tunes':       {'classical_cinematic': 0.8, 'pop': 0.4},
    
    # =========================================================================
    # WORLD / REGIONAL (lower weights for less smearing)
    # =========================================================================
    'indian':           {'world_regional': 0.65, 'classical_cinematic': 0.35, 'pop': 0.25},
    'flamenco':         {'acoustic_folk': 0.55, 'world_regional': 0.25, 'classical_cinematic': 0.2, 'latin_tropical': 0.35},

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

    # Dub should anchor reggae_dub first, then bass overlap.
    'dub':              {'reggae_dub': 0.8, 'bass_music': 0.4, 'electronic_techno': 0.2},
    
    # Classic electro / electroclash (not just house adjacency).
    'electro':          {'electronic_techno': 0.4, 'electronic_house': 0.4, 'hip_hop': 0.3, 'rnb_soul': 0.3},

    # Keep funk tied to rnb_soul, with regional spillover for baile/funk contexts.
    'funk':             {'rnb_soul': 0.8, 'hip_hop': 0.3, 'latin_regional': 0.2},

    # Added Genre
    'reggae':           {'reggae_dub': 1.0, 'rock': 0.2},

    # Keep groove distinct from pure heavy-metal by adding progressive/rhythm character.
    'groove':           {'metal': 0.5, 'rock': 0.3, 'progressive': 0.4, 'rnb_soul': 0.2},

    # Split old broad goth bucket with better separation from alt-rock and industrial.
    'goth-rock':        {'alternative': 0.4, 'rock': 0.3, 'electronic_techno': 0.4, 'chill_ambient': 0.3},
    'darkwave':         {'electronic_techno': 0.5, 'chill_ambient': 0.5, 'alternative': 0.3, 'pop': 0.2},

    # Film / soundtrack anchor with reduced coupling to regional pop clusters.
    'pop-film':         {'classical_cinematic': 0.6, 'pop': 0.3, 'chill_ambient': 0.2},

    # Mexican Regional (Corrido, Sierreño, Banda, Norteño, Ranchera)
    'corrido':          {'latin_regional': 0.6, 'acoustic_folk': 0.5, 'hip_hop': 0.3, 'latin_tropical': 0.1},

    # =========================================================================
    # NEW STYLE SPLITS
    # =========================================================================
    'latin-urban':      {'hip_hop': 0.7, 'latin_tropical': 0.6, 'pop': 0.4}, # Reggaeton/Trap
    
    'j-pop':            {'pop': 0.6, 'electronic_house': 0.2, 'alternative': 0.2},
    'j-rock':           {'rock': 0.6, 'alternative': 0.3, 'pop': 0.2},

    'hardcore-hip-hop': {'hip_hop': 0.6, 'rnb_soul': 0.3}, # Aggressive Rap (Wu-Tang, DMX)
    'hardcore-punk':    {'punk': 0.6, 'metal': 0.2},
    'post-hardcore':    {'punk': 0.5, 'rock': 0.4, 'emo_pop_punk': 0.4, 'metal': 0.2}, 
    
    # Generic 'hardcore' pointing to punk to catch stragglers
    'hardcore':         {'punk': 0.6, 'metal': 0.3}, 
}
