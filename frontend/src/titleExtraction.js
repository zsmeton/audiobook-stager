export const TITLE_STEPS = [
  {
    id: "edition",
    label: "Edition",
    tip: "Strip unabridged/abridged and bracketed edition tags, e.g. “(Unabridged)” or “[Audiobook]”.",
    example: "Dune (Unabridged) → Dune",
  },
  {
    id: "part_prefix",
    label: "Part markers",
    tip: "Remove leading track/part prefixes and trailing “Part 01” / “Pt 2” tails.",
    example: "Dark Age - Part 01 → Dark Age",
  },
  {
    id: "format_noise",
    label: "Format noise",
    tip: "Drop bitrate, codec, and bare-year release noise from the title string.",
    example: "Project Hail Mary 128k M4B → Project Hail Mary",
  },
  {
    id: "leading_index",
    label: "Leading index",
    tip: "Remove conservative leading indices such as “01 - ” or “1. ”.",
    example: "01 - Red Rising → Red Rising",
  },
  {
    id: "index_trailing",
    label: "Trailing index",
    tip: "Remove zero-padded trailing disc/track numbers like “Title 01”. More aggressive — off by default.",
    example: "The Heroes 01 → The Heroes",
  },
  {
    id: "colon_split",
    label: "Colon split",
    tip: "Keep the main title before a colon subtitle, e.g. “Athens: The Rivalry” → “Athens”.",
    example: "Athens: The Rivalry → Athens",
  },
  {
    id: "series_name",
    label: "Series name",
    tip: "Strip embedded series folder/tag names when they are not the book title.",
    example: "Mistborn The Final Empire → The Final Empire",
  },
  {
    id: "author",
    label: "Strip author",
    tip: "Remove known author prefix/suffix from the title when artist/album tags identify the author.",
    example: "Andy Weir - Artemis → Artemis",
  },
  {
    id: "junk_tail",
    label: "Junk tail",
    tip: "Remove junk subtitle tails like “ - A Novel” or “ - Unabridged”.",
    example: "Neuromancer - A Novel → Neuromancer",
  },
  {
    id: "multipart",
    label: "Multipart",
    tip: "Remove multi-file markers such as “(2 of 5)”.",
    example: "The Hobbit (2 of 5) → The Hobbit",
  },
  {
    id: "series_markers",
    label: "Series markers",
    tip: "Strip inline series markers like “Book 3”, “Vol. 2”, or “#1”.",
    example: "Morning Star Book 3 → Morning Star",
  },
  {
    id: "trim_edges",
    label: "Trim edges",
    tip: "Strip dangling spaces and separator punctuation left at the start or end after other cleanup.",
    example: "— Dark Age ~ → Dark Age",
  },
];

export const TITLE_MODE_TIPS = {
  conservative: "Album tag first, then title tag, then filename, then folder.",
  balanced: "Finds the best shared title across tags and paths. Good default.",
  advanced: "Like Balanced, with optional extra cleanup you control.",
};

export const ADVANCED_DEFAULT_PRE = [
  "edition",
  "part_prefix",
  "format_noise",
  "leading_index",
  "colon_split",
  "series_name",
];

export const ADVANCED_DEFAULT_POST = ["colon_split", "trim_edges"];
