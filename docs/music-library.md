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

**Artist folder.** The release's album artist, under the name the release credits, which is the name the album artist tag holds, not the name MusicBrainz gives that artist now: `Red and Blue`, credited `Stefani`, sits under `S/Stefani/`, though the artist is `Lady Gaga` today. The folder and the album artist tag are built from the same name. Where the library already holds that artist under another spelling of the folder (`B/Babasonicos` where MusicBrainz says `Babasónicos`), the review warns before Approve and the owner may choose the library's spelling, which sets the album artist tag and the folder to that name. An album artist typed on the review page does the same: the folder follows it. A name that is not in the Latin script uses the artist's English alias from MusicBrainz where there is one, in the folder and in the artist tags: `植松伸夫` goes under `N/Nobuo Uematsu`. Where there is none it stays as written: `#/Вася Обломов`. When MusicBrainz's sort name for that artist is the credited name with a leading article moved to the end, the folder uses the sort name: `Toten Hosen, Die`, `Strokes, The`, `Bunkers, Los`, `Rita Mitsouko, Les`, `Perfect Circle, A`. Otherwise it is the name as written, so people stay `Joaquín Sabina` and never become `Sabina, Joaquín`. An artist MusicBrainz does not know falls back to a fixed list: The, A, An, Los, Las, La, El, Die, Der, Das, Les, Le, L'. Compilations go under `V/Various Artists`. An artist folder that would start with `.` or `-` has that character replaced by `_` and is filed under `#`: `.38 Special` becomes `#/_38 Special` and `-M-` becomes `#/_M-`. The tag keeps the name as written.

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

**Each artist of a credit.** A credit such as `Future & Marshmello` does not say whether it names one act or two. Where it names several, `ARTISTS` holds each artist as a value of its own, and `ALBUMARTISTS` does the same for the album artist: `TXXX:ARTISTS` and `TXXX:ALBUMARTISTS` on MP3, `artists` and `albumartists` on FLAC and Ogg. A player reads them to list the track under each artist. The import does not write them: MusicBrainz's artist IDs already say who a release credits, and these tags are for the artist it does not credit, a remixer for one. The owner fills them on the review page or the album page, under Artists and Album artists, where typing a name searches MusicBrainz for it. Only the names are written, and the MusicBrainz IDs stay as the release gives them.

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

The cover is the first of these that exists: the owner's upload, the Cover Art Archive's front, the front picture embedded in the files, the first local cover. With none of them the album is held with a `no cover` problem that says to upload one, or to identify again when the archive failed. The archive's front is the release's, or the release group's when the release answered with no front. The embedded front is the front picture of the first track that carries any picture, else that track's first picture. A folder `cover.jpg` that is the same picture as the embedded front and at least as large stays the cover, so an album already in the library keeps its full-size file. Any other folder cover, or a smaller `cover.jpg`, loses to the embedded front.

An image passes as a cover when it is square enough (width over height between 0.9 and 1.1) and its shorter side is at least 500 px. The archive's front is the cover when it passes. Failing that, the first local cover that passes is. A front the archive types as anything but Front, Booklet or Sticker never passes, whatever its size. Where both an archive front and a local cover exist and neither passes, the one that fails fewer of those tests (shape, size and, for the archive's front, its type) wins, then the one with the longer shorter side, then the archive's, and the album is held with both sizes named. Where only one of them exists, it is the cover whether or not it passes, and nothing is held. A release front that fails never sends the album to the release group's front. An embedded front, or a local cover chosen because the archive has no front, is the cover whether or not it passes, and the page shows the warning.

A local `front.*` is never deleted, moved or renamed: it is usually a scan of the booklet's front, and it is often not square. A stray kept as `front.*` (see *What an album folder may contain*) counts as a local `front.*`. Where it is the cover, its image is copied into `cover.jpg` and `front.*` stays. Where the cover is a local `folder`, `album` or `art` image, it becomes `cover.jpg` and the original is removed. A local cover that is not the cover stays under its own name, except a local `cover.jpg`, which the planned one replaces.

Everything else the Cover Art Archive has for the release is kept beside it: `back.jpg`, `booklet-01.jpg`, `medium.jpg` (`medium-1.jpg`, `medium-2.jpg` when there are several), `tray.jpg`, `spine.jpg`, `obi.jpg`, and so on. A second image of the same type is numbered. An image whose bytes, as they would be written, equal a file the album folder already has, or one saved before it from the archive, is not saved again, PDFs included.

A PDF from the Cover Art Archive is kept in the album folder as `booklet.pdf` (`booklet-1.pdf`, `booklet-2.pdf` when there are several) and is never embedded.

The owner can supply the cover. An accept in `decisions.json` may name an image inside the job. That image becomes `cover.jpg`, converted to JPEG where it is not one, and the embedded picture, whatever the Cover Art Archive has or fails to give and whether or not it passes the cover test. The archive's other images are still saved. A local `cover`, `folder`, `album` or `art` image it replaces is removed, and `front.*` stays. `apply` refuses the album as changed if that image changed or is gone.

On an album already in the library, the owner's upload on its page does the same to the album as it stands: the image becomes `cover.jpg`, converted to JPEG where it is not one and kept at full size, and every track's embedded pictures are replaced by one front cover of at most 1200 px on the long side. No other image in the folder changes: `front.*`, `back.jpg` and the booklets stay. A `cover.jpg` that is a link is replaced by a real file, and nothing is written through the link. An image that fails the cover test is accepted, with its warning shown before Save.

When a request to the archive fails (any answer other than 200 or 404, no answer, a timeout, a dropped connection, or an image that downloads but is not an image), the album is still planned and only what failed is left out. A failed listing of the release means no archive image at all, and the release group is not asked in its place. A failed image is left out and the others are saved under the names they would take without it. The plan carries a note that does not block approval, naming each failed request and what the cover is instead. Failures are never cached, so Identify again asks the archive anew, and a front that now answers replaces an embedded or folder cover, never the owner's upload. `apply` refuses an album whose archive answers changed since identify.

## What an album folder may contain

Audio, images, PDF booklets, `.log` files (a rip log proves how the audio was made) and `.txt` notes. All of them sit in the album folder itself, never in a subfolder other than a `CDn`.

Artwork outside that rule (in a subfolder, in a disc folder, or at the root under an odd name) is renamed to the library's names from the words in its file name, or in its folder's where the file's say nothing, and numbered like the archive's images (`front.jpg`, `back.jpg`, `medium-2.jpg`, `booklet-04.jpg`) over the files that are kept: a copy takes no number. A copy of the cover, of an archive image, of a file already in the folder or of another stray is deleted. Against an archive image or a file already in the folder under the same name, the one with at least 10 % more pixels is kept; where neither has, the folder's file is kept, else the archive's. A file that cannot be named waits for the owner on the album page, and so do strays that would share a name with none clearly larger: one in a subfolder holds the album, one at the root keeps its own name.

Removed: OS junk (`.DS_Store`, `._*`, `__MACOSX/`, `Thumbs.db`, `desktop.ini`, `.directory`, `Icon\r`, Windows Media Player's `AlbumArtSmall.jpg` and `AlbumArt_*.jpg`), and rip lists that name the old filenames and go stale the moment files are renamed (`.cue`, `.m3u`, `.m3u8`, `.sfv`, `.accurip`, `.ffp`, `.md5`), plus `.lrc`, `.nfo`, `.url`, `.ini` and `.ico`. An album coming in also loses any file of a type this section does not name, such as a `.torrent`.

Videos, disc images and CD-ROM software are kept, but outside the library, in `/srv/music/extras` under the same `Letter/Artist/Album` path. foobar2000 does not watch that folder.

## How new music gets in

Through one funnel, `/srv/music/inbox`, and never by copying straight into the library. Every album is identified against MusicBrainz, tagged, named and checked against this file, and shown for review before anything moves. Nothing lands without a person saying yes.

The funnel is agitha, at `agitha.lan` (also `import.music.lan`). Albums are dropped on the page, one drop at a time, and each is reviewed there and approved or left. Its folders and unit are in [hyrule-castle.md](hyrule-castle.md).

The review page also says what the library already holds for the artist. It reads the albums under the planned letter whose artist folder carries exactly the plan's album artist ids, or has the planned folder's name with case and accents folded and no album with other ids. The album a match replaces is left out, and albums are counted, not tracks. A genre that every track of at least half of those albums carries, and the plan lacks, is offered with Add, unless it is not on MusicBrainz's list of genres. Where the plan holds one of `soundtrack` and `video game music`, the other is offered with Choose when at least half of those albums carry it. Where the plan waits for the soundtrack choice, either is offered on the same terms. A folder under another spelling brings the warning described under *Artist folder*. A suggestion can be dismissed, never blocks Approve, and is applied only by a click.

## Changing an album in the library

An album in the library is changed only through agitha's Library pages, never by editing its files in place. There are two ways: by hand, and by a match.

**By hand.** The album page edits any tag of the tracks selected, replaces the cover and swaps the places of two tracks. The artist page runs the same tag edit over the tracks or albums selected. Nothing is written until Save. Save copies the album, writes the copy, reads every file back and swaps the copy in for the library's folder. A step that fails leaves the album as it was. So does a file of the library's copy that changes while Save runs, a rating written by a player for one: the save fails and puts the album back.

**What a hand edit keeps.** It changes what was edited and nothing else. Every other tag, the rating, `ADDED`, the embedded picture (unless the cover was replaced) and the audio come out as they went in. Save asks MusicBrainz nothing and works on an album with no release id. It refuses where the album changed since the page loaded, where the draft would break a rule of this file that the album does not already break (a track left with no genre, a doubled space, two tracks with one number on a disc), and where the new folder or a new file name belongs to another file. A rule the album already breaks does not stop a save that leaves it alone. An album with a file the page cannot read can still be edited, and that file is kept as it is. A file that is a link is not a track here: the Library pages do not list it, Save copies it as the link it is, and nothing is written through it.

**What cannot be edited.** MusicBrainz IDs, ratings, pictures and other binary frames, keys the format cannot hold, and `ADDED`: the refusals of *Raw edits*, with the added time. A raw key with no readable name cannot be edited over tracks of more than one format at once. A genre has to be on the list *Genres* describes, `soundtrack` and `video game music` included.

**Paths follow tags.** Each part of a path is rebuilt, by *Layout*, from the tag that names it, and only where that tag changed:

| tag | part of the path |
|---|---|
| album artist | letter and artist folder |
| album | the title in the album folder |
| the year of the date | `(YYYY)` |
| disc number | `CDn` |
| track number, title | file name |

A part whose tag did not change stays as it is. The artist folder is built from the name as written, with the fixed list of leading articles, as for an artist MusicBrainz does not know: a hand edit never looks the name up. The folder's type prefix (`[EP]`, `[Single]`, `[Mixtape]`, `[Live]`) and its edition suffix are MusicBrainz's. A hand edit keeps them as found, and a wrong release is fixed by a match. Artist and letter folders that a move leaves empty are removed, and the album's extras move to the new path.

**Delete album.** The album page deletes the album for good, after asking: its folder, every file in it and its extras. Nothing is set aside, so there is no undo. The artist and letter folders it leaves empty go too. An album being saved or open in review cannot be deleted. `memory.json` is left as it was.

**Empty folders.** The Library tree removes an artist or album folder only where it holds nothing at all, hidden files included. The letter folder goes with its last artist. A folder that holds anything is refused with `not empty: <path>`.

**Not remembered.** `memory.json` belongs to the review alone. A hand edit, a batch, a cover or a swap leaves it as it was, so a later match plans from MusicBrainz and from what earlier reviews remembered, and shows a hand-edited value as a change like any other.

**Swap.** Two selected tracks trade places, on one disc or across discs, in one format or two. Each file takes the other's track number and disc number (keeping its own totals), title, artist and artist sort name, composer and composer sort name, lyrics, disc subtitle, MusicBrainz recording, track and artist IDs, and file name. The audio stays in its file with its extension, its rating, ReplayGain values and play history. So does every tag not listed: genre, date, album, album artist, comment, picture and `ADDED`.

Where the album has a release id and its files fit that release's track list, the page flags two tracks of a disc that each run more than 3 s from their own position's length in MusicBrainz and within 3 s of the other's, and offers that swap. It never swaps by itself. The lookup comes after the page shows, and MusicBrainz's answer is cached.

**Batch on an artist.** What the artist page sends is a batch, whatever the number of albums. The tags that name a track or an album, or move a file, are refused there: title, artist, album artist, their sort names, album, date, original date, track number, disc number and disc subtitle. Paths do not change. The preview lists each album's changed tracks, and each album is saved on its own. An album with nothing to change, one open in review, one that changed since the page loaded and one the edit would push into breaking a rule (the only genre of a track removed) are skipped with the reason. One that fails is left as it was, and the others go on.

**By a match.** Match to MusicBrainz copies the album into the inbox as a drop of one album and opens its review. It goes through the same identify, decisions and memory as an upload, so everything identify plans lands on Approve and the edits earlier reviews remembered for that release are laid again. Approve replaces the album the match started from: in place where the planned folder is the same one, else in the planned folder, with the old one removed once the new one verifies. Each track keeps the `ADDED` the library's copy has. Approve refuses where the planned folder is another album's or where a file of the library's copy changed after the copy was taken, or while Approve ran, and the library is as it was. The match is then started over. Match is refused for an album that holds a link, which the copy cannot follow. Discard deletes the copy and leaves the library as it was. While a match is open the album cannot be edited by hand. Where identify finds no release, the review offers Discard only.

What foobar2000 does with a folder replaced at the same path is in [hyrule-castle.md](hyrule-castle.md).
