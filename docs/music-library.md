# The music library

The rules every album in `/srv/music/library` on hyrule-castle follows. New music is checked against this file before it lands, and the existing library is brought into line with it. Where the two disagree, this file wins and the library gets fixed.

MusicBrainz is the reference for every fact about a release. The one exception is the fingerprint fallback (AcoustID, also MetaBrainz), used only to find which MusicBrainz release a file belongs to.

## Layout

```
/srv/music/library/
└── T/
    └── Toten Hosen, Die/
        └── (2002) Reich & Sexy II - Die fetten Jahre/
            ├── cover.jpg
            ├── back.jpg
            ├── CD1/
            │   ├── 01. Hier kommt Alex.flac
            │   └── ...
            └── CD2/
                └── ...
```

**Letter.** The first character of the artist folder, uppercased, accents removed: `Ángeles Azules, Los` goes under `A`. Digits, symbols and non-Latin scripts go under `#`.

**Artist folder.** The release's album artist. When MusicBrainz's sort name for that artist is the name with a leading article moved to the end, the folder uses the sort name: `Toten Hosen, Die`, `Strokes, The`, `Bunkers, Los`, `Rita Mitsouko, Les`, `Perfect Circle, A`. Otherwise it is the name as written, so people stay `Joaquín Sabina` and never become `Sabina, Joaquín`. An artist MusicBrainz does not know falls back to a fixed list: The, A, An, Los, Las, La, El, Die, Der, Das, Les, Le, L'. Compilations go under `V/Various Artists`.

**Album folder.** `(YYYY) Title`, where `YYYY` is the year of the release's `DATE` tag. The folder and the tag never disagree. A release that is not a plain album gets a prefix from its MusicBrainz release group:

| prefix | when |
|---|---|
| `[EP]` | primary type EP |
| `[Single]` | primary type Single |
| `[Mixtape]` | secondary type Mixtape/Street |
| `[Live]` | secondary type Live |
| `[LP]` | **open: MusicBrainz has no LP type. Needs a definition before it can be applied** |

One prefix at most, in the order the table lists them.

**Discs.** A release with more than one medium puts each in `CD1`, `CD2` and so on, whatever the medium actually is. A single-medium release has no disc folder. Covers and every other image sit in the album folder, never inside a `CDn`.

**Files.** `NN. Title.ext`: the track number, two digits (three on a medium with a hundred tracks or more), a full stop, a space, the title. Numbering restarts in each `CDn`.

**Characters Windows cannot hold.** Folder and file names have to survive foobar2000 under Wine and any FAT32 drive the library gets copied to.

| in the tag | in the name |
|---|---|
| `: ` | ` - ` |
| `:` anywhere else | `-` |
| `/`, `\` | `-` |
| `?`, `*`, `<`, `>`, `\|` | removed |
| `"` | `''` |
| trailing `.` or space | removed |

## Tags

**Formats.** MP3 carries ID3v2.4 and no ID3v1. FLAC and Ogg carry Vorbis comments. M4A carries MP4 atoms. Field names are the ones Picard writes.

**Every track has** title, artist, album, album artist, date, track number and total, disc number and total, and the MusicBrainz release, release group, recording and artist IDs. Sort names (`ALBUMARTISTSORT`, `ARTISTSORT`) come from MusicBrainz.

**Dates.** `DATE` is the release date of this edition. `ORIGINALDATE` is the release group's first release. There is no `YEAR` tag.

**Discs.** `DISCSUBTITLE` (`TSST` on MP3) holds a disc's own title. It never goes into the album title, and neither do `(disc 1)`, `(bonus disc)` or anything like them.

**No duplicate fields.** One album artist field (`TPE2`, `ALBUMARTIST`), never `TXXX:ALBUM ARTIST` or `ALBUM ARTIST` beside it. One total, never both inside `TRCK`/`TPOS` and in a `TXXX`.

**Genres.** Only names on MusicBrainz's official genre list, spelled the way MusicBrainz spells them (lowercase, `post-rock`, `hip hop`), stored as separate values rather than one delimited string. Two custom genres exist because MusicBrainz models soundtracks as a release type rather than a genre: `soundtrack` and `video game music`. A release MusicBrainz marks as a soundtrack gets `soundtrack` by default. The import review can switch it to `video game music`, and that choice is remembered per composer. A release with no MusicBrainz genres and no soundtrack type has no genre rather than an invented one.

**Ratings.** Whole stars, 1 to 5. MP3 holds one `POPM` frame with the email `Windows Media Player 9 Series` on the WMP byte scale (1, 64, 128, 196, 255), which is what foobar2000 writes. FLAC and Ogg hold `RATING` as a plain number. An unrated track has no rating tag at all, never `0` or `-1`. The import never writes a rating: ratings come from listening, in foobar2000 or Jean.

**Whitespace.** No leading or trailing spaces, no doubled spaces, in any field.

## Images

`cover.jpg` is the front cover and every album has one. The same image is embedded in every track as the front cover picture, resized to at most 1200 px on the long side so a big scan doesn't get copied into every file. `cover.jpg` stays at full size.

Everything else the Cover Art Archive has for the release is kept beside it: `back.jpg`, `booklet-01.jpg`, `medium.jpg` (`medium-1.jpg`, `medium-2.jpg` when there are several), `tray.jpg`, `spine.jpg`, `obi.jpg`, and so on. A second image of the same type is numbered.

## What an album folder may contain

Audio, images, and `.log` files (a rip log proves how the audio was made).

Nothing else. Removed on import: `.DS_Store`, `._*`, `__MACOSX/`, `Thumbs.db`, `desktop.ini`, `.directory`, `Icon\r`, and `.cue`, `.m3u`, `.m3u8`, `.nfo`, `.sfv`, `.txt`. A cue sheet or playlist names the old filenames, so it is wrong the moment files are renamed.

## How new music gets in

Through one funnel, `/srv/music/inbox`, and never by copying straight into the library. Every album is identified against MusicBrainz, tagged, named and checked against this file, and shown for review before anything moves. Nothing lands without a person saying yes.
