import { DEFAULT_SETTINGS } from "$lib/stores";

type LandingExampleSettingKey =
    | "variety"
    | "genreWeight"
    | "maxResults"
    | "tracksPerArtist"
    | "targetLanguage"
    | "targetGenre"
    | "vibeMood"
    | "vibeSound"
    | "popularity";

export type LandingExampleSettings = Partial<
    Pick<typeof DEFAULT_SETTINGS, LandingExampleSettingKey>
>;

export interface LandingExample {
    id: string;
    artists: string[];
    lane: string;
    songs?: Record<string, string[]>;
    settings?: LandingExampleSettings;
}

export interface LandingExampleSearchRequest {
    artists: string[];
    fineTune: Record<string, string[]>;
    settings?: LandingExampleSettings;
}

export const LANDING_EXAMPLE_DEFAULTS: LandingExampleSettings = {
    variety: 0,
    genreWeight: 2,
    maxResults: 9,
    tracksPerArtist: 3,
    targetLanguage: "match",
    targetGenre: "match",
    vibeMood: 0,
    vibeSound: 0,
    popularity: 0,
};

export const LANDING_EXAMPLES: LandingExample[] = [
    {
        id: "foster-the-people",
        artists: ["Foster The People"],
        lane: "Bright indie-pop",
    },
    {
        id: "anitta",
        artists: ["Anitta"],
        lane: "Brazilian funk-pop",
    },
    {
        id: "paramore",
        artists: ["Paramore"],
        lane: "Emo / pop-punk",
    },
    {
        id: "lana-del-rey",
        artists: ["Lana Del Rey"],
        lane: "Alt-pop",
    },
    {
        id: "bad-bunny-feid",
        artists: ["Bad Bunny", "Feid"],
        lane: "Latin urbano",
    },
    {
        id: "arctic-monkeys-strokes",
        artists: ["Arctic Monkeys", "The Strokes"],
        lane: "Indie / garage rock",
    },
    {
        id: "parcels-roosevelt",
        artists: ["Parcels", "Roosevelt"],
        lane: "Nu-disco / synth-pop",
    },
    {
        id: "marias-men-i-trust",
        artists: ["The Marías", "Men I Trust"],
        lane: "Dreamy indie-pop",
    },
    {
        id: "newjeans-lesserafim-aespa",
        artists: ["NewJeans", "LE SSERAFIM", "aespa"],
        lane: "K-pop",
    },
    {
        id: "yoasobi-aimer-hikaru-utada",
        artists: ["YOASOBI", "Aimer", "Hikaru Utada"],
        lane: "J-pop",
    },
    {
        id: "phoebe-mitski-clairo",
        artists: ["Phoebe Bridgers", "Mitski", "Clairo"],
        lane: "Confessional indie-pop",
    },
    {
        id: "peso-pluma-fuerza-regida-chino-pacas",
        artists: ["Peso Pluma", "Fuerza Regida", "Chino Pacas"],
        lane: "Corridos",
    },
];
