import {
	Check,
	ChevronDown,
	Disc3,
	ExternalLink,
	Link as LinkIcon,
	Search,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { formatLength } from "@/domain/album/format";
import {
	byLevel,
	failingNumber,
	type Level,
	levelOf,
	releaseUrl,
	trackTotal,
} from "@/domain/album/match";
import type { AlbumView, Candidate } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { failingWords } from "./failingWords";
import styles from "./MatchPicker.module.css";
import type { Pending } from "./pending";

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
// A bare MBID, or the URL of one release. A release group's URL names no one release.
const BARE = new RegExp(`^${UUID}$`, "i");
const RELEASE_URL = new RegExp(
	`^https?://(www\\.|beta\\.)?musicbrainz\\.org/release/${UUID}([/?#].*)?$`,
	"i",
);

type Translate = ReturnType<typeof useTranslate>["t"];

function searchTerm(view: AlbumView) {
	const tags = view.preview?.files[0]?.before ?? view.uploaded?.[0]?.tags ?? {};
	const album = ["TALB", "album", "©alb", "WM/AlbumTitle"]
		.map((key) => tags[key]?.[0])
		.find(Boolean);
	const raw = album ?? view.name.replace(/[_]+/g, " ");
	return raw.replace(/\s*[([]?\s*(disc|cd)\s*\d+.*$/i, "").trim();
}

const searchUrl = (term: string) =>
	`https://musicbrainz.org/search?type=release&method=indexed&query=${encodeURIComponent(term)}`;

function Thumb({ candidate }: { candidate: Candidate }) {
	const [failed, setFailed] = useState(false);
	return failed ? (
		<span className={styles.thumb} aria-hidden="true">
			<Disc3 size={20} />
		</span>
	) : (
		<img
			className={styles.thumb}
			src={candidate.thumbnail}
			alt=""
			width={48}
			height={48}
			loading="lazy"
			onError={() => setFailed(true)}
		/>
	);
}

function Badge({ level }: { level: Level }) {
	const { t } = useTranslate();
	return (
		<span className={styles.badge} data-level={level}>
			{t(`match.${level}`)}
		</span>
	);
}

function reasonsOf(candidate: Candidate, folder: number, t: Translate) {
	if (levelOf(candidate) === "unchecked") return [t("match.why.unchecked")];
	const reasons: string[] = [];
	const total = trackTotal(candidate);
	if (total === null) reasons.push(t("match.why.tracksUnknown"));
	else if (candidate.matches_counts)
		reasons.push(t("match.why.tracksMatch", { n: total }));
	else reasons.push(t("match.why.tracksDiffer", { n: total, folder }));
	if (candidate.duration_diff !== null) {
		const off = Math.abs(candidate.duration_diff);
		reasons.push(
			off < 1
				? t("match.why.sameLength")
				: t("match.why.lengthOff", {
						by: off < 60 ? `${Math.round(off)} s` : formatLength(off),
					}),
		);
	}
	if (candidate.failing_tracks)
		reasons.push(t("match.why.failing", { n: candidate.failing_tracks }));
	if (candidate.matches_counts && candidate.artist_agrees !== undefined)
		reasons.push(
			t(candidate.artist_agrees ? "match.why.artist" : "match.why.noArtist"),
		);
	if (candidate.status && candidate.status !== "Official")
		reasons.push(candidate.status);
	return reasons;
}

function Facts({ candidate }: { candidate: Candidate }) {
	const { t } = useTranslate();
	const total = trackTotal(candidate);
	const facts = [
		candidate.date,
		candidate.country,
		candidate.format,
		total === null ? null : t("match.tracks", { n: total }),
	].filter(Boolean);
	return <span className={styles.facts}>{facts.join(" · ")}</span>;
}

export function MatchPicker({
	view,
	pending,
}: {
	view: AlbumView;
	pending: Pending;
}) {
	const { t } = useTranslate();
	const [open, setOpen] = useState(false);
	const [pasted, setPasted] = useState("");
	const [refused, setRefused] = useState(false);
	const root = useRef<HTMLDivElement>(null);
	const panelId = useId();
	const pasteId = useId();

	const candidates = view.preview?.candidates ?? [];
	const folder = view.preview?.files.length ?? 0;
	const multiDisc =
		new Set(view.preview?.files.map((file) => file.position.split("-")[0]))
			.size > 1;
	const draft = pending.draft;
	const chosenId = draft.action === "accept" ? draft.release_id : null;
	const chosen = candidates.find((each) => each.release_id === chosenId);
	const sorted = byLevel(candidates);
	const checked = sorted.filter((each) => levelOf(each) !== "unchecked");
	const unchecked = sorted.filter((each) => levelOf(each) === "unchecked");

	useEffect(() => {
		if (!open) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") setOpen(false);
		};
		const onClick = (event: MouseEvent) => {
			if (!root.current?.contains(event.target as Node)) setOpen(false);
		};
		document.addEventListener("keydown", onKey);
		document.addEventListener("mousedown", onClick);
		return () => {
			document.removeEventListener("keydown", onKey);
			document.removeEventListener("mousedown", onClick);
		};
	}, [open]);

	function choose(releaseId: string) {
		pending.setCandidate(releaseId);
		setOpen(false);
	}

	function use() {
		const release = pasted.trim();
		const id = new RegExp(UUID, "i").exec(release)?.[0]?.toLowerCase();
		if (id && (BARE.test(release) || RELEASE_URL.test(release))) {
			setRefused(false);
			pending.setCandidate(id);
			setPasted("");
			setOpen(false);
		} else {
			setRefused(true);
		}
	}

	const row = (candidate: Candidate) => {
		const isChosen = candidate.release_id === chosenId;
		const level = levelOf(candidate);
		return (
			<li
				key={candidate.release_id}
				className={styles.option}
				aria-current={isChosen ? "true" : undefined}
			>
				<button
					type="button"
					className={styles.choose}
					onClick={() => choose(candidate.release_id)}
				>
					<Thumb candidate={candidate} />
					<span className={styles.text}>
						<span className={styles.name}>
							{candidate.title ?? t("match.untitled")}
							{candidate.artist && (
								<span className={styles.artist}> · {candidate.artist}</span>
							)}
						</span>
						<Facts candidate={candidate} />
						<span className={styles.reasons}>
							{reasonsOf(candidate, folder, t).join(" · ")}
						</span>
					</span>
					<Badge level={level} />
					<span className={styles.check}>
						{isChosen && (
							<Check size={16} aria-label={t("candidates.chosen")} />
						)}
					</span>
				</button>
				<a
					className={styles.external}
					href={releaseUrl(candidate.release_id)}
					target="_blank"
					rel="noreferrer"
					aria-label={t("match.open", {
						title: candidate.title ?? candidate.release_id,
					})}
				>
					<ExternalLink size={14} aria-hidden="true" />
				</a>
			</li>
		);
	};

	return (
		<section className={styles.picker} aria-labelledby={`${panelId}-title`}>
			<h3 id={`${panelId}-title`} className={styles.label}>
				<a
					className={styles.search}
					href={searchUrl(searchTerm(view))}
					target="_blank"
					rel="noreferrer"
					title={t("match.search")}
				>
					{t("match.title")}
					<Search size={12} aria-hidden="true" />
				</a>
			</h3>
			<div ref={root} className={styles.anchor}>
				<div className={styles.current}>
					<button
						type="button"
						className={styles.trigger}
						aria-expanded={open}
						aria-controls={panelId}
						onClick={() => setOpen(!open)}
					>
						{draft.action === "repoint" ? (
							<>
								<span className={styles.thumb} aria-hidden="true">
									<LinkIcon size={20} />
								</span>
								<span className={styles.text}>
									<span className={styles.name}>{t("match.repoint")}</span>
									<span className={styles.facts}>{draft.release}</span>
								</span>
							</>
						) : chosen ? (
							<>
								<Thumb candidate={chosen} />
								<span className={styles.text}>
									<span className={styles.name}>
										{chosen.title ?? t("match.untitled")}
										{chosen.artist && (
											<span className={styles.artist}> · {chosen.artist}</span>
										)}
									</span>
									<Facts candidate={chosen} />
									<span className={styles.reasons}>
										{reasonsOf(chosen, folder, t).join(" · ")}
									</span>
								</span>
								<Badge level={levelOf(chosen)} />
							</>
						) : chosenId ? (
							<>
								<span className={styles.thumb} aria-hidden="true">
									<LinkIcon size={20} />
								</span>
								<span className={styles.text}>
									<span className={styles.name}>{t("match.pasted")}</span>
									<span className={styles.facts}>{chosenId}</span>
									<span className={styles.reasons}>
										{t("match.pastedNext")}
									</span>
								</span>
							</>
						) : (
							<span className={styles.text}>
								<span className={styles.name}>{t("match.none")}</span>
							</span>
						)}
						<span className={styles.more}>
							{t("match.others", { n: candidates.length })}
							<ChevronDown size={16} aria-hidden="true" />
						</span>
					</button>
					{chosenId && draft.action === "accept" && (
						<a
							className={styles.external}
							href={releaseUrl(chosenId)}
							target="_blank"
							rel="noreferrer"
							aria-label={t("match.open", {
								title: chosen?.title ?? chosenId,
							})}
						>
							<ExternalLink size={16} aria-hidden="true" />
						</a>
					)}
				</div>

				{draft.action === "accept" && (chosen?.failing?.length ?? 0) > 0 && (
					<ul className={styles.failing} aria-label={t("match.failing.list")}>
						{chosen?.failing?.map((track) => (
							<li key={track.position}>
								{t("match.failing.track", {
									n: failingNumber(track.position, multiDisc),
									title: track.title,
									why: failingWords(track, t),
								})}
							</li>
						))}
					</ul>
				)}

				{open && (
					<div id={panelId} className={styles.panel}>
						<ul className={styles.list} aria-label={t("match.title")}>
							{checked.map(row)}
						</ul>
						{unchecked.length > 0 && (
							<details className={styles.unchecked}>
								<summary>
									{t("match.uncheckedCount", { n: unchecked.length })}
								</summary>
								<ul className={styles.list}>{unchecked.map(row)}</ul>
							</details>
						)}
						<div className={styles.paste}>
							<label htmlFor={pasteId}>{t("candidates.paste")}</label>
							<div className={styles.pasteRow}>
								<input
									id={pasteId}
									type="text"
									placeholder="https://musicbrainz.org/release/…"
									value={pasted}
									onChange={(event) => setPasted(event.target.value)}
									onKeyDown={(event) => {
										if (event.key === "Enter") use();
									}}
								/>
								<button type="button" className={styles.button} onClick={use}>
									{t("candidates.use")}
								</button>
							</div>
							{refused && <p role="alert">{t("candidates.notRelease")}</p>}
						</div>
					</div>
				)}
			</div>
		</section>
	);
}
