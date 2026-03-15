from __future__ import annotations

import numpy as np
import polars as pl

from genre_families import GENRE_DEFINITIONS


def compute_genre_embeddings_polars(unique_genres: list[str]) -> pl.DataFrame:
    """Compute dense genre embeddings from sparse family definitions."""
    all_families = set()
    for families in GENRE_DEFINITIONS.values():
        all_families.update(families.keys())
    all_families = sorted(all_families)

    family_to_genres = {family: {} for family in all_families}
    for genre, families in GENRE_DEFINITIONS.items():
        for family, weight in families.items():
            family_to_genres[family][genre] = weight

    rows = []
    for genre in unique_genres:
        vec = {"genre": genre}
        for family in all_families:
            vec[f"genre_{family}"] = 0.0

        if genre in GENRE_DEFINITIONS:
            for family, weight in GENRE_DEFINITIONS[genre].items():
                vec[f"genre_{family}"] = max(vec[f"genre_{family}"], weight)

        if genre in GENRE_DEFINITIONS:
            smearing_decay = 0.5
            for shared_family, g_weight in GENRE_DEFINITIONS[genre].items():
                for neighbor, n_weight in family_to_genres[shared_family].items():
                    if neighbor == genre:
                        continue
                    connection_strength = g_weight * n_weight
                    if neighbor in GENRE_DEFINITIONS:
                        for target_family, neighbor_target_weight in GENRE_DEFINITIONS[neighbor].items():
                            score = connection_strength * neighbor_target_weight * smearing_decay
                            col = f"genre_{target_family}"
                            vec[col] = max(vec[col], score)

        rows.append(vec)

    emb_df = pl.from_dicts(rows)
    genre_cols = [col for col in emb_df.columns if col.startswith("genre_")]
    emb_matrix = emb_df.select(genre_cols).to_numpy()
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    emb_matrix = emb_matrix / norms

    emb_df = emb_df.select("genre").hstack(pl.from_numpy(emb_matrix, schema=genre_cols))
    return emb_df


def apply_inter_artist_smearing(
    df: pl.DataFrame,
    embedding_df: pl.DataFrame,
    genre_cols: list[str],
    smear_strength: float,
    *,
    verbose: bool = False,
) -> pl.DataFrame:
    """Blend track genre vectors with artist-level genre identity, then renormalize."""
    if smear_strength <= 0:
        return df

    if verbose:
        print(f"Applying inter-artist smearing (strength={smear_strength})...")

    ag_counts = (
        df
        .group_by(["artist_name", "genre"])
        .len()
        .filter(pl.col("len") >= 1)
    )

    ag_with_vectors = ag_counts.join(embedding_df, on="genre", how="left")
    artist_identities = ag_with_vectors.group_by("artist_name").agg([pl.col(c).mean() for c in genre_cols])

    profile_cols = [f"_profile_{c}" for c in genre_cols]
    artist_identities = artist_identities.rename({c: f"_profile_{c}" for c in genre_cols})

    df = df.join(artist_identities, on="artist_name", how="left")

    for profile_col, genre_col in zip(profile_cols, genre_cols):
        df = df.with_columns(
            pl.when(pl.col(profile_col).is_null())
            .then(pl.col(genre_col))
            .otherwise(pl.col(profile_col))
            .alias(profile_col)
        )

    blend_exprs = []
    for genre_col, profile_col in zip(genre_cols, profile_cols):
        blended = (
            (1.0 - smear_strength) * pl.col(genre_col)
            + smear_strength * pl.col(profile_col)
        ).alias(genre_col)
        blend_exprs.append(blended)

    df = df.with_columns(blend_exprs).drop(profile_cols)

    genre_matrix = df.select(genre_cols).to_numpy()
    norms = np.linalg.norm(genre_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    genre_matrix = genre_matrix / norms

    df = df.drop(genre_cols).hstack(pl.from_numpy(genre_matrix, schema=genre_cols))
    df = df.with_columns([pl.col(c).cast(pl.Float32) for c in genre_cols])
    return df
