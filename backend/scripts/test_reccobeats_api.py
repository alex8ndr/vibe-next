#!/usr/bin/env python3
"""
Test ReccoBeats API search functionality.

Usage:
    # Run full test suite
    python test_reccobeats_api.py
    
    # Quick search test for specific artist(s)
    python test_reccobeats_api.py "Radiohead"
    python test_reccobeats_api.py "Far Caspian, Japanese Breakfast"
    
    # Adjust search limit (default: 20)
    python test_reccobeats_api.py "Radiohead" --limit 50
    
    # Run full pipeline test for an artist
    python test_reccobeats_api.py "Radiohead" --pipeline
    
    # Quiet mode (less output)
    python test_reccobeats_api.py "Radiohead" -q
"""
import sys
import time
import json
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import requests
from track_dedup import normalize_artist_name

# API endpoint
RECCOBEATS_URL = "https://api.reccobeats.com/v1"
TIMEOUT = 20

# Test cases - various artist types
TEST_ARTISTS = [
    # Well-known artists (should definitely exist)
    ("Radiohead", "well-known"),
    ("The Beatles", "well-known"),
    ("Kendrick Lamar", "well-known"),
    
    # Mid-tier indie artists
    ("Far Caspian", "indie"),
    ("Pinegrove", "indie"),
    ("Japanese Breakfast", "indie"),
    
    # Niche/obscure artists (may or may not exist)
    ("The Oogum Boogum Song", "obscure"),
    ("Ghost Orchard", "obscure"),
    
    # Non-ASCII names
    ("Beyoncé", "special-chars"),
    ("Sigur Rós", "special-chars"),
    ("Motörhead", "special-chars"),
    
    # Edge cases
    ("", "edge-case"),  # Empty string
    ("a", "edge-case"),  # Single character
    ("Artist That Does Not Exist 12345", "edge-case"),  # Non-existent
]


def test_search_endpoint(name: str, category: str) -> dict:
    """Test the /artist/search endpoint."""
    print(f"\n  [SEARCH] '{name}' ({category})")
    
    try:
        url = f"{RECCOBEATS_URL}/artist/search"
        params = {"searchText": name, "size": 5}
        
        start_time = time.time()
        r = requests.get(url, params=params, timeout=TIMEOUT)
        elapsed = time.time() - start_time
        
        print(f"    Status: {r.status_code} ({elapsed:.2f}s)")
        
        if r.status_code == 429:
            print(f"    [RATE LIMITED]")
            return {"success": False, "error": "rate_limited", "time": elapsed}
        
        if r.status_code != 200:
            print(f"    [ERROR] HTTP {r.status_code}: {r.text[:200]}")
            return {"success": False, "error": f"http_{r.status_code}", "time": elapsed}
        
        data = r.json()
        results = data.get("content", [])
        
        print(f"    Found: {len(results)} results")
        
        # Check for exact match
        target_norm = normalize_artist_name(name) if name else ""
        exact_match = None
        
        for i, artist in enumerate(results):
            artist_name = artist.get("name", "")
            artist_id = artist.get("id", "")
            is_exact = normalize_artist_name(artist_name) == target_norm and name
            
            marker = "[EXACT]" if is_exact else ""
            print(f"      {i+1}. {artist_name} (ID: {artist_id}) {marker}")
            
            if is_exact:
                exact_match = artist
        
        return {
            "success": True,
            "results_count": len(results),
            "exact_match": exact_match,
            "first_result": results[0] if results else None,
            "all_results": results,
            "time": elapsed,
        }
        
    except requests.exceptions.Timeout:
        print(f"    [ERROR] Timeout after {TIMEOUT}s")
        return {"success": False, "error": "timeout"}
    except requests.exceptions.RequestException as e:
        print(f"    [ERROR] Request failed: {e}")
        return {"success": False, "error": str(e)}
    except json.JSONDecodeError as e:
        print(f"    [ERROR] Invalid JSON: {e}")
        return {"success": False, "error": "invalid_json"}
    except Exception as e:
        print(f"    [ERROR] Unexpected: {e}")
        return {"success": False, "error": str(e)}


def test_artist_endpoint(artist_uuid: str, artist_name: str) -> dict:
    """Test the /artist/{uuid} endpoint."""
    print(f"\n  [ARTIST] Getting details for {artist_name}")
    print(f"    UUID: {artist_uuid}")
    
    try:
        url = f"{RECCOBEATS_URL}/artist/{artist_uuid}"
        
        start_time = time.time()
        r = requests.get(url, timeout=TIMEOUT)
        elapsed = time.time() - start_time
        
        print(f"    Status: {r.status_code} ({elapsed:.2f}s)")
        
        if r.status_code != 200:
            print(f"    [ERROR] HTTP {r.status_code}")
            return {"success": False, "error": f"http_{r.status_code}", "time": elapsed}
        
        data = r.json()
        name = data.get("name", "N/A")
        popularity = data.get("popularity", "N/A")
        
        print(f"    Name: {name}")
        print(f"    Popularity: {popularity}")
        
        return {
            "success": True,
            "name": name,
            "popularity": popularity,
            "time": elapsed,
        }
        
    except Exception as e:
        print(f"    [ERROR] {e}")
        return {"success": False, "error": str(e)}


def test_artist_tracks_endpoint(artist_uuid: str, artist_name: str, limit: int = 10) -> dict:
    """Test the /artist/{uuid}/track endpoint."""
    print(f"\n  [TRACKS] Getting top {limit} tracks for {artist_name}")
    
    try:
        url = f"{RECCOBEATS_URL}/artist/{artist_uuid}/track"
        params = {"page": 0, "size": limit}
        
        start_time = time.time()
        r = requests.get(url, params=params, timeout=TIMEOUT)
        elapsed = time.time() - start_time
        
        print(f"    Status: {r.status_code} ({elapsed:.2f}s)")
        
        if r.status_code != 200:
            print(f"    [ERROR] HTTP {r.status_code}")
            return {"success": False, "error": f"http_{r.status_code}", "time": elapsed}
        
        data = r.json()
        tracks = data.get("content", [])
        
        print(f"    Found: {len(tracks)} tracks")
        
        for i, track in enumerate(tracks[:5]):
            title = track.get("trackTitle", "N/A")
            pop = track.get("popularity", "N/A")
            href = track.get("href", "")
            spotify_id = href.split("/")[-1] if href else "N/A"
            print(f"      {i+1}. {title} (pop: {pop}, id: {spotify_id})")
        
        if len(tracks) > 5:
            print(f"      ... and {len(tracks) - 5} more")
        
        # Collect Spotify IDs for audio features test
        spotify_ids = []
        for track in tracks:
            href = track.get("href", "")
            if href:
                sid = href.split("/")[-1]
                if sid:
                    spotify_ids.append(sid)
        
        return {
            "success": True,
            "tracks_count": len(tracks),
            "spotify_ids": spotify_ids[:5],
            "time": elapsed,
        }
        
    except Exception as e:
        print(f"    [ERROR] {e}")
        return {"success": False, "error": str(e)}


def test_audio_features(spotify_ids: list) -> dict:
    """Test the /audio-features endpoint."""
    if not spotify_ids:
        print(f"\n  [AUDIO-FEATURES] Skipped (no track IDs)")
        return {"success": False, "error": "no_ids"}
    
    print(f"\n  [AUDIO-FEATURES] Getting features for {len(spotify_ids)} tracks")
    
    try:
        # Test batching - API limits to 40 per request
        test_ids = spotify_ids[:3]  # Just test with 3
        url = f"{RECCOBEATS_URL}/audio-features"
        params = {"ids": ",".join(test_ids)}
        
        start_time = time.time()
        r = requests.get(url, params=params, timeout=TIMEOUT)
        elapsed = time.time() - start_time
        
        print(f"    Status: {r.status_code} ({elapsed:.2f}s)")
        
        if r.status_code != 200:
            print(f"    [ERROR] HTTP {r.status_code}")
            return {"success": False, "error": f"http_{r.status_code}", "time": elapsed}
        
        data = r.json()
        features = data.get("content", [])
        
        print(f"    Found: {len(features)} feature sets")
        
        for feat in features[:2]:
            sid = feat.get("id", "N/A")
            danceability = feat.get("danceability", "N/A")
            energy = feat.get("energy", "N/A")
            print(f"      - {sid}: danceability={danceability}, energy={energy}")
        
        return {
            "success": True,
            "features_count": len(features),
            "time": elapsed,
        }
        
    except Exception as e:
        print(f"    [ERROR] {e}")
        return {"success": False, "error": str(e)}


def test_track_endpoint(spotify_id: str) -> dict:
    """Test the /track endpoint with a Spotify ID."""
    print(f"\n  [TRACK] Getting track by Spotify ID: {spotify_id}")
    
    try:
        url = f"{RECCOBEATS_URL}/track"
        params = {"ids": spotify_id}
        
        start_time = time.time()
        r = requests.get(url, params=params, timeout=TIMEOUT)
        elapsed = time.time() - start_time
        
        print(f"    Status: {r.status_code} ({elapsed:.2f}s)")
        
        if r.status_code != 200:
            print(f"    [ERROR] HTTP {r.status_code}")
            return {"success": False, "error": f"http_{r.status_code}", "time": elapsed}
        
        data = r.json()
        tracks = data.get("content", [])
        
        print(f"    Found: {len(tracks)} tracks")
        
        if tracks:
            track = tracks[0]
            title = track.get("trackTitle", "N/A")
            artists = track.get("artists", [])
            artist_name = artists[0].get("name", "N/A") if artists else "N/A"
            print(f"    Track: {title} by {artist_name}")
        
        return {
            "success": True,
            "found": len(tracks) > 0,
            "time": elapsed,
        }
        
    except Exception as e:
        print(f"    [ERROR] {e}")
        return {"success": False, "error": str(e)}


def run_full_pipeline_test(artist_name: str) -> dict:
    """Run the full discovery pipeline for an artist."""
    print(f"\n{'='*60}")
    print(f"FULL PIPELINE TEST: {artist_name}")
    print(f"{'='*60}")
    
    results = {
        "artist": artist_name,
        "search": None,
        "artist_details": None,
        "tracks": None,
        "audio_features": None,
        "track_lookup": None,
    }
    
    # Step 1: Search
    search_result = test_search_endpoint(artist_name, "pipeline-test")
    results["search"] = search_result
    
    if not search_result.get("success") or not search_result.get("exact_match"):
        print(f"\n  [PIPELINE] Stopped - search failed or no exact match")
        return results
    
    artist_uuid = search_result["exact_match"].get("id")
    confirmed_name = search_result["exact_match"].get("name")
    
    # Step 2: Get artist details
    time.sleep(0.2)
    artist_details = test_artist_endpoint(artist_uuid, confirmed_name)
    results["artist_details"] = artist_details
    
    if not artist_details.get("success"):
        print(f"\n  [PIPELINE] Stopped - couldn't get artist details")
        return results
    
    # Step 3: Get tracks
    time.sleep(0.2)
    tracks_result = test_artist_tracks_endpoint(artist_uuid, confirmed_name, limit=15)
    results["tracks"] = tracks_result
    
    if not tracks_result.get("success"):
        print(f"\n  [PIPELINE] Stopped - couldn't get tracks")
        return results
    
    # Step 4: Get audio features
    if tracks_result.get("spotify_ids"):
        time.sleep(0.2)
        features_result = test_audio_features(tracks_result["spotify_ids"])
        results["audio_features"] = features_result
    
    # Step 5: Test track lookup via /track endpoint
    if tracks_result.get("spotify_ids"):
        time.sleep(0.2)
        track_result = test_track_endpoint(tracks_result["spotify_ids"][0])
        results["track_lookup"] = track_result
    
    print(f"\n  [PIPELINE] ✓ All steps completed successfully")
    return results


def quick_search(artists: list, limit: int = 20, pipeline: bool = False, quiet: bool = False):
    """Quick search test for specific artists."""
    for artist_name in artists:
        artist_name = artist_name.strip()
        if not artist_name:
            continue
        
        if pipeline:
            run_full_pipeline_test(artist_name)
        else:
            print(f"\n{'='*60}")
            print(f"SEARCH: {artist_name} (limit={limit})")
            print(f"{'='*60}")
            
            try:
                url = f"{RECCOBEATS_URL}/artist/search"
                params = {"searchText": artist_name, "size": limit}
                
                start = time.time()
                r = requests.get(url, params=params, timeout=TIMEOUT)
                elapsed = time.time() - start
                
                print(f"Status: {r.status_code} ({elapsed:.2f}s)")
                
                if r.status_code != 200:
                    print(f"Error: {r.text[:200]}")
                    continue
                
                results = r.json().get("content", [])
                print(f"Found: {len(results)} results")
                
                target_norm = normalize_artist_name(artist_name)
                exact_found = False
                
                for i, a in enumerate(results):
                    name = a.get("name", "")
                    aid = a.get("id", "")
                    is_exact = normalize_artist_name(name) == target_norm
                    marker = " [EXACT MATCH]" if is_exact else ""
                    if is_exact:
                        exact_found = True
                    
                    if not quiet or is_exact or i < 5:
                        print(f"  {i+1}. {name} (id: {aid}){marker}")
                
                if not exact_found:
                    print(f"\n  WARNING: No exact match for '{artist_name}'")
                    
            except Exception as e:
                print(f"Error: {e}")
        
        time.sleep(0.2)


def run_full_suite():
    """Run the comprehensive test suite."""
    print("="*70)
    print("RECCOBEATS API COMPREHENSIVE TEST SUITE")
    print("="*70)
    print(f"API Base URL: {RECCOBEATS_URL}")
    print(f"Test started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    all_results = []
    
    # Test 1: Search endpoint with various artists
    print("\n" + "="*70)
    print("TEST SUITE 1: Artist Search Endpoint")
    print("="*70)
    
    search_results = []
    for artist_name, category in TEST_ARTISTS:
        if not artist_name:
            continue
        result = test_search_endpoint(artist_name, category)
        search_results.append({
            "name": artist_name,
            "category": category,
            **result
        })
        time.sleep(0.2)
    
    all_results.append({"test": "search", "results": search_results})
    
    # Test 2: Full pipeline with select artists
    print("\n" + "="*70)
    print("TEST SUITE 2: Full Discovery Pipeline")
    print("="*70)
    
    pipeline_artists = ["Radiohead", "Far Caspian", "Japanese Breakfast"]
    pipeline_results = []
    for artist in pipeline_artists:
        result = run_full_pipeline_test(artist)
        pipeline_results.append(result)
        time.sleep(0.5)
    
    all_results.append({"test": "pipeline", "results": pipeline_results})
    
    # Test 3: Edge cases
    print("\n" + "="*70)
    print("TEST SUITE 3: Edge Cases")
    print("="*70)
    
    edge_cases = []
    
    print("\n  Testing empty search...")
    edge_cases.append({"case": "empty_string", **test_search_endpoint("", "edge-case")})
    time.sleep(0.2)
    
    print("\n  Testing long string...")
    edge_cases.append({"case": "long_string", **test_search_endpoint("A" * 500, "edge-case")})
    time.sleep(0.2)
    
    print("\n  Testing invalid UUID...")
    edge_cases.append({"case": "invalid_uuid", "artist": test_artist_endpoint("not-a-valid-uuid", "Invalid")})
    
    all_results.append({"test": "edge_cases", "results": edge_cases})
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    search_exact = sum(1 for r in search_results if r.get("exact_match"))
    print(f"\nSearch: {search_exact}/{len(search_results)} exact matches")
    
    for r in search_results:
        status = "+" if r.get("exact_match") else ("-" if r.get("success") else "x")
        print(f"  {status} {r['name']} ({r['category']})")
    
    print(f"\nPipeline:")
    for r in pipeline_results:
        ok = all([
            r["search"] and r["search"].get("success"),
            r["artist_details"] and r["artist_details"].get("success"),
            r["tracks"] and r["tracks"].get("success"),
        ])
        print(f"  {'+ ' if ok else 'x '}{r['artist']}")
    
    output_file = Path(__file__).parent / "test_reccobeats_results.json"
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Test ReccoBeats API search")
    parser.add_argument("artists", nargs="?", help="Artist name(s), comma-separated")
    parser.add_argument("--limit", type=int, default=20, help="Search result limit (default: 20)")
    parser.add_argument("--pipeline", action="store_true", help="Run full pipeline test")
    parser.add_argument("-q", "--quiet", action="store_true", help="Less output")
    parser.add_argument("--full", action="store_true", help="Run full test suite")
    args = parser.parse_args()
    
    if args.artists:
        artists = [a.strip() for a in args.artists.split(",")]
        quick_search(artists, limit=args.limit, pipeline=args.pipeline, quiet=args.quiet)
    else:
        run_full_suite()


if __name__ == "__main__":
    main()
