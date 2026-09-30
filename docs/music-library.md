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

**Letter.** The first character of the artist folder, uppercased, accents removed: `Ángeles Azules, Los` goes under `A`. `Ø` counts as `O` and `Ł` as `L`, like an accented letter: `Øystein Sevåg` goes under `O`. Digits, symbols and non-Latin scripts go under `#`.

**Artist folder.** The release's album artist, under the name MusicBrainz gives that artist now, not the name the release credits: `Red and Blue`, credited `Stefani`, sits under `L/Lady Gaga/`, and its tags still say `Stefani`. A name that is not in the Latin script uses the artist's English alias from MusicBrainz where there is one, in the folder and in the artist tags: `植松伸夫` goes under `N/Nobuo Uematsu`. Where there is none it stays as written: `#/Вася Обломов`. When MusicBrainz's sort name for that artist is the name with a leading article moved to the end, the folder uses the sort name: `Toten Hosen, Die`, `Strokes, The`, `Bunkers, Los`, `Rita Mitsouko, Les`, `Perfect Circle, A`. Otherwise it is the name as written, so people stay `Joaquín Sabina` and never become `Sabina, Joaquín`. An artist MusicBrainz does not know falls back to a fixed list: The, A, An, Los, Las, La, El, Die, Der, Das, Les, Le, L'. Compilations go under `V/Various Artists`. An artist folder that would start with `.` or `-` has that character replaced by `_` and is filed under `#`: `.38 Special` becomes `#/_38 Special` and `-M-` becomes `#/_M-`. The tag keeps the name as written.

**Album folder.** `(YYYY) Title`, where `YYYY` is the year of the release's `DATE` tag. The folder and the tag never disagree. A release that is not a plain album gets a prefix from its MusicBrainz release group:

| prefix | when |
|---|---|
| `[EP]` | primary type EP |
| `[Single]` | primary type Single |
| `[Mixtape]` | secondary type Mixtape/Street |
| `[Live]` | secondary type Live |

One prefix at most, in the order the table lists them. A plain album (an LP, in the old sense) has none. "LP" appears in a folder name only when it is part of the title MusicBrainz gives the release, as in `(1999) The Slim Shady LP`.

Two or more editions of one album that would share a folder each get a suffix in brackets, taken from the first of these fields that every one of them has and whose values all differ (compared without case): the MusicBrainz disambiguation comment, the country, the medium format. The country is written as its name, not its code. `(2007) Unia [Japan]` sits beside `(2007) Unia [Europe]`, and `(2008) Dear Science [CD]` beside `(2008) Dear Science [Vinyl]`. Where no field separates them, none gets a suffix and they stay held as a collision. An album alone in its folder keeps no suffix.

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

**Long names.** A folder or file name is at most 255 bytes in UTF-8, prefixes, track number and extension included. A longer one is cut at the last whole word that fits, and ` [...]` marks the cut. The tag keeps the full title.

## Tags

**Formats.** MP3 carries ID3v2.4 and no ID3v1. FLAC and Ogg carry Vorbis comments. M4A carries MP4 atoms. Field names are the ones Picard writes.

**Every track has** title, artist, album, album artist, date, track number and total, disc number and total, and the MusicBrainz release, release group, recording and artist IDs. Sort names (`ALBUMARTISTSORT`, `ARTISTSORT`) come from MusicBrainz.

Where a release's titles are not in the Latin script, the album and track titles come from MusicBrainz's English tracklist for it, else from a romanized one.

**Dates.** `DATE` is the release date of this edition. `ORIGINALDATE` is the release group's first release. There is no `YEAR` tag.

**Edition.** Where several MusicBrainz releases fit the files, the library takes an Official one over any other status, and among those the oldest. A partial date counts as the last day it could be, and an undated release comes last.

**Discs.** `DISCSUBTITLE` (`TSST` on MP3) holds a disc's own title. It never goes into the album title, and neither do `(disc 1)`, `(bonus disc)` or anything like them.

**No duplicate fields.** One album artist field (`TPE2`, `ALBUMARTIST`), never `TXXX:ALBUM ARTIST` or `ALBUM ARTIST` beside it. One total, never both inside `TRCK`/`TPOS` and in a `TXXX`.

No field credits whoever ripped, encoded or uploaded the file, or links to where it came from. `uploader`, `provider`, `website`, `wwwaudiofile` and `wwwaudiosource` are removed, with their forms in the other formats, and so is any value that is wholly a URL or a bare domain (a generic top-level label such as `.com` or `.xyz`, or a country code), in any text tag but lyrics and the fields the engine plans from MusicBrainz: title, artist, album, album artist, their sort names and composer. `will.i.am` is a name there, not a site.

**Composers.** For every release the engine makes one more MusicBrainz lookup, of its recordings with their work and artist relations, cached under its own URL. A track's composers are the artists of every `composer` relationship on each work its recording performs, in the order MusicBrainz lists them, each once. `writer`, `lyricist`, `arranger` and the other types do not count. They are written as separate values of the composer tag and, in the same order, of the composer sort tag, replacing what the file had: `TCOM` and `TSOC` on MP3, `composer` and `composersort` on FLAC and Ogg, `©wrt` and `soco` on M4A, `WM/Composer` and `WM/ComposerSortOrder` on WMA. A name not in the Latin script takes the artist's primary English alias, as artist names do, and the sort name stays as MusicBrainz gives it. A track MusicBrainz gives no composer keeps the composer tags its file carries. `batch identify --no-composer` skips the lookup for a job, and `apply` follows.

**Raw edits.** In the import review, an accept's edits may name a tag key of the file's own format, with a list of values or `null` to remove it. MusicBrainz IDs, ratings, binary frames and keys the format cannot hold are refused. Raw edits are remembered per release, like the other edits.

**Genres.** Only names on MusicBrainz's official genre list, spelled the way MusicBrainz spells them (lowercase, `post-rock`, `hip hop`), stored as separate values rather than one delimited string. Two custom genres exist because MusicBrainz models soundtracks as a release type rather than a genre: `soundtrack` and `video game music`. An album MusicBrainz types as a soundtrack is held until one of these settles it: a game tag on the release group, `video game music` on the files, an incoming game genre, or the owner's choice in the import review of `video game music`, `soundtrack` or neither. `soundtrack` on the files does not settle it. The choice is remembered for that release. Of a release's MusicBrainz genres, only those whose vote count is at least a quarter of the top genre's are kept, ties included. A release with no MusicBrainz genres keeps the genres its files carry that are on the list, lowercased. Every track has at least one genre, and a track with none is an error.

**Ratings.** Whole stars, 1 to 5. MP3 holds one `POPM` frame with the email `Windows Media Player 9 Series` on the WMP byte scale (1, 64, 128, 196, 255), which is what foobar2000 writes. FLAC and Ogg hold `RATING` as a plain number. An unrated track has no rating tag at all, never `0` or `-1`. The import never writes a rating: ratings come from listening, in foobar2000 or Jean.

**Added.** An import writes `ADDED` on every track, the time its upload started in the box's local time, to the minute (`2026-09-30T11:02`), and a library job leaves the `ADDED` a file has as it is.

**Whitespace.** No leading or trailing spaces, no doubled spaces, in any single-line text field. Lyrics, play history and machine-written values are kept as they are.

## Images

`cover.jpg` is the front cover and every album has one. The same image is embedded in every track as the front cover picture, resized to at most 1200 px on the long side so a big scan doesn't get copied into every file. `cover.jpg` stays at full size.

An image passes as a cover when it is square enough (width over height between 0.9 and 1.1) and its shorter side is at least 500 px. The Cover Art Archive's front is the cover when it passes. Failing that, the first local cover that passes is. A front the archive types as anything but Front, Booklet or Sticker never passes, whatever its size. Where both an archive front and a local cover exist and neither passes, the one that fails fewer of those tests (shape, size and, for the archive's front, its type) wins, then the one with the longer shorter side, then the archive's, and the album is held with both sizes named. Where only one of them exists, it is the cover whether or not it passes, and nothing is held. A release front that fails never sends the album to the release group's front.

A local `front.*` is never deleted, moved or renamed: it is usually a scan of the booklet's front, and it is often not square. Where it is the cover, its image is copied into `cover.jpg` and `front.*` stays. Where the cover is a local `folder`, `album` or `art` image, it becomes `cover.jpg` and the original is removed.

Everything else the Cover Art Archive has for the release is kept beside it: `back.jpg`, `booklet-01.jpg`, `medium.jpg` (`medium-1.jpg`, `medium-2.jpg` when there are several), `tray.jpg`, `spine.jpg`, `obi.jpg`, and so on. A second image of the same type is numbered. An image whose bytes, as they would be written, equal a file the album folder already has, or one saved before it from the archive, is not saved again, PDFs included.

A PDF from the Cover Art Archive is kept in the album folder as `booklet.pdf` (`booklet-1.pdf`, `booklet-2.pdf` when there are several) and is never embedded.

The owner can supply the cover. An accept in `decisions.json` may name an image inside the job. That image becomes `cover.jpg`, converted to JPEG where it is not one, and the embedded picture, whatever the Cover Art Archive has and whether or not it passes the cover test. The archive's other images are still saved. A local `cover`, `folder`, `album` or `art` image it replaces is removed, and `front.*` stays. `apply` refuses the album as changed if that image changed or is gone.

## What an album folder may contain

Audio, images, PDF booklets, `.log` files (a rip log proves how the audio was made) and `.txt` notes. All of them sit in the album folder itself, never in a subfolder other than a `CDn`.

Removed: OS junk (`.DS_Store`, `._*`, `__MACOSX/`, `Thumbs.db`, `desktop.ini`, `.directory`, `Icon\r`, Windows Media Player's `AlbumArtSmall.jpg` and `AlbumArt_*.jpg`), and rip lists that name the old filenames and go stale the moment files are renamed (`.cue`, `.m3u`, `.m3u8`, `.sfv`, `.accurip`, `.ffp`, `.md5`), plus `.lrc`, `.nfo`, `.url`, `.ini` and `.ico`. An album coming in also loses any file of a type this section does not name, such as a `.torrent`.

Videos, disc images and CD-ROM software are kept, but outside the library, in `/srv/music/extras` under the same `Letter/Artist/Album` path. foobar2000 does not watch that folder.

## How new music gets in

Through one funnel, `/srv/music/inbox`, and never by copying straight into the library. Every album is identified against MusicBrainz, tagged, named and checked against this file, and shown for review before anything moves. Nothing lands without a person saying yes.

The funnel is agitha, at `agitha.lan` (also `import.music.lan`). Albums are dropped on the page, one drop at a time, and each is reviewed there and approved or left. Its folders and unit are in [hyrule-castle.md](hyrule-castle.md).
