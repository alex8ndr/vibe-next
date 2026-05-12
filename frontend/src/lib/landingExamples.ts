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
    hidden?: boolean;
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
        id: "lana-del-rey",
        artists: ["Lana Del Rey"],
        lane: "Alt-pop",
    },
    {
        id: "frank-ocean",
        artists: ["Frank Ocean"],
        lane: "Alt-R&B",
    },
    {
        id: "paramore",
        artists: ["Paramore"],
        lane: "Emo / pop-punk",
    },
    {
        id: "anitta",
        artists: ["Anitta"],
        lane: "Brazilian pop",
    },
    {
        id: "billie-eilish-ilomilo",
        artists: ["Billie Eilish"],
        lane: "Bedroom pop",
        songs: { "Billie Eilish": ["ilomilo"] },
    },
    {
        id: "newjeans-omg",
        artists: ["NewJeans"],
        lane: "K-pop",
        songs: { NewJeans: ["OMG"] },
    },
    {
        id: "kavinsky-the-midnight",
        artists: ["Kavinsky", "The Midnight"],
        lane: "Synthwave",
    },
    {
        id: "bad-bunny-feid",
        artists: ["Bad Bunny", "Feid"],
        lane: "Latin urbano",
    },
    {
        id: "marias-men-i-trust",
        artists: ["The Marías", "Men I Trust"],
        lane: "Dreamy indie-pop",
    },
    {
        id: "parcels-roosevelt",
        artists: ["Parcels", "Roosevelt"],
        lane: "Nu-disco",
    },
    {
        id: "tyler-childers-zach-bryan",
        artists: ["Tyler Childers", "Zach Bryan"],
        lane: "Americana",
    },
    {
        id: "orelsan-pnl",
        artists: ["Orelsan", "PNL"],
        lane: "French rap",
    },

    // Bench
    {
        id: "arctic-monkeys-strokes",
        artists: ["Arctic Monkeys", "The Strokes"],
        lane: "Indie rock",
        hidden: true,
    },
    {
        id: "yoasobi-aimer-hikaru-utada",
        artists: ["YOASOBI", "Aimer", "Hikaru Utada"],
        lane: "J-pop",
        hidden: true,
    },
    {
        id: "phoebe-mitski-clairo",
        artists: ["Phoebe Bridgers", "Mitski", "Clairo"],
        lane: "Confessional indie-pop",
        hidden: true,
    },
    {
        id: "burna-boy-wizkid",
        artists: ["Burna Boy", "Wizkid"],
        lane: "Afrobeats",
        hidden: true,
    },
    {
        id: "spiritbox",
        artists: ["Spiritbox"],
        lane: "Metalcore",
        hidden: true,
    },
    {
        id: "polo-and-pan",
        artists: ["Polo & Pan"],
        lane: "French electro-pop",
        hidden: true,
    },
    {
        id: "clara-luciani-pomme",
        artists: ["Clara Luciani", "Pomme"],
        lane: "French pop",
        hidden: true,
    },
];

export const LANDING_VISIBLE_EXAMPLES = LANDING_EXAMPLES.filter(
    (example) => !example.hidden,
);
