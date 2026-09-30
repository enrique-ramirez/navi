import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ThumbsUp } from "lucide-react";

import { albumQuery } from "@/domain/album/albumQuery";
import {
	formatKbps,
	formatKilohertz,
	formatSize,
	formatTotalLength,
} from "@/domain/album/format";
import type { AlbumView, Comparison, Copy, CopySide } from "@/shared/api/types";
import type { Phrase } from "@/shared/i18n/en";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Alert } from "@/shared/ui/Alert";
import { approveReason } from "./approveReason";
import styles from "./Duplicate.module.css";
import { Outcome } from "./Outcome";
import type { Pending } from "./pending";
import { useDecision } from "./useDecision";

// Criterion 48's rules, by the code the server sends.
const RULES: Record<Comparison["rule_code"], Phrase> = {
	"more-files": "rule.moreFiles",
	lossless: "rule.lossless",
	"bit-depth": "rule.bitDepth",
	"sample-rate": "rule.sampleRate",
	bitrate: "rule.bitrate",
	library: "rule.library",
};

export function Duplicate({
	view,
	pending,
}: {
	view: AlbumView;
	pending: Pending;
}) {
	const { t } = useTranslate();
	const navigate = useNavigate();
	// The same query as the album page, so this panel keeps polling where it is shown alone.
	const { data: current } = useQuery({
		...albumQuery(view.drop, view.n),
		initialData: view,
	});
	const { refusal, changed, awaiting, busy, send, approve } = useDecision(
		current,
		pending,
	);
	const { duplicate } = current;

	// Keeping the library's copy discards the upload and needs no accepted preview. Keeping the
	// new one approves it, so a preview not accepted yet is accepted first, as Approve does.
	async function keep(side: CopySide) {
		if (side === "library") {
			if (await approve("library")) await navigate({ to: "/" });
		} else if (current.approvable.code === "not-accepted") {
			await send({ kind: "approve", keep: "new" });
		} else {
			await approve("new");
		}
	}

	// What stops the buttons: a running process, an unsent change, or, for the new copy, a hold.
	const stopped = current.busy
		? t("duplicate.running")
		: pending.dirty
			? t("actions.updateFirst")
			: null;
	const why: Record<CopySide, string | null> = {
		library: stopped,
		new:
			stopped ??
			(current.approvable.code === "not-accepted"
				? null
				: approveReason(current, t)),
	};
	const label = (side: CopySide) => {
		const phrase =
			side === "new" ? "duplicate.keepNew" : "duplicate.keepLibrary";
		if (awaiting?.then.kind === "approve" && side === "new")
			return t("review.approving");
		const reason = why[side];
		return reason === null
			? t(phrase)
			: t("duplicate.keepWhy", { action: t(phrase), why: reason });
	};

	const kbpsRange = (copy: Copy) =>
		copy.bitrate_min === copy.bitrate_max
			? formatKbps(copy.bitrate)
			: `${formatKbps(copy.bitrate)} (${formatKbps(copy.bitrate_min)} – ${formatKbps(copy.bitrate_max)})`;
	const release = (copy: Copy) =>
		[copy.album, copy.date, copy.country, copy.label, copy.catalog]
			.filter(Boolean)
			.join(" · ") || "—";

	// Each fact of a copy, as text so the two sides can be compared.
	const facts: [string, (copy: Copy) => string][] = [
		[t("duplicate.release"), release],
		[
			t("duplicate.mbRelease"),
			(copy) => copy.release_id ?? t("duplicate.none"),
		],
		[t("file.format"), (copy) => copy.format],
		[
			t("duplicate.lossless"),
			(copy) => t(copy.lossless ? "file.lossless" : "file.lossy"),
		],
		// A FLAC re-tagged by Mutagen reports the tagger as its vendor, which says nothing of the encoder.
		[
			t("duplicate.encoder"),
			(copy) =>
				copy.encoder && !/^mutagen\b/i.test(copy.encoder)
					? copy.encoder
					: t("duplicate.none"),
		],
		[
			t("duplicate.bitDepth"),
			(copy) =>
				copy.bit_depth === null
					? t("duplicate.none")
					: t("file.bitDepth", { n: copy.bit_depth }),
		],
		[t("duplicate.sampleRate"), (copy) => formatKilohertz(copy.sample_rate)],
		[t("duplicate.bitrate"), kbpsRange],
		[
			t("duplicate.files"),
			(copy) =>
				copy.discs > 1
					? t("summary.tracksOnDiscs", { n: copy.files, discs: copy.discs })
					: String(copy.files),
		],
		[t("duplicate.length"), (copy) => formatTotalLength(copy.length)],
		[t("duplicate.size"), (copy) => formatSize(copy.size)],
		[t("duplicate.tags"), (copy) => String(Math.round(copy.tag_count))],
		[t("duplicate.folder"), (copy) => copy.folder],
	];

	const sides = ["new", "library"] as const;
	const copyOf = (side: CopySide) =>
		side === "new" ? duplicate?.new : duplicate?.library;
	const tracks = duplicate?.tracks;

	return (
		<section className={styles.duplicate} aria-labelledby="duplicate-title">
			<header className={styles.header}>
				<h2 id="duplicate-title">{t("duplicate.title")}</h2>
				<p className={styles.lede}>{t("duplicate.lede")}</p>
			</header>
			{duplicate && (
				<>
					<p role="status" className={styles.recommendation}>
						<ThumbsUp size={18} aria-hidden="true" />
						<span>
							{t("duplicate.recommended", {
								which: t(
									duplicate.recommended === "new"
										? "duplicate.theNew"
										: "duplicate.theLibrary",
								),
								rule: t(RULES[duplicate.rule_code]),
							})}
						</span>
					</p>

					<table
						className={styles.table}
						aria-label={t("duplicate.comparison")}
					>
						<colgroup>
							<col className={styles.factCol} />
							{sides.map((side) => (
								<col
									key={side}
									data-recommended={duplicate.recommended === side || undefined}
								/>
							))}
						</colgroup>
						<thead>
							<tr>
								<th scope="col">
									<span className="visually-hidden">{t("duplicate.fact")}</span>
								</th>
								{sides.map((side) => {
									const copy = copyOf(side);
									return (
										<th
											key={side}
											scope="col"
											data-recommended={
												duplicate.recommended === side || undefined
											}
										>
											<div className={styles.copyHead}>
												<span className={styles.copyName}>
													{t(
														side === "new"
															? "duplicate.new"
															: "duplicate.libraryCopy",
													)}
													{duplicate.recommended === side && " "}
													{duplicate.recommended === side && (
														<span className={styles.badge}>
															{t("duplicate.recommendedMark")}
														</span>
													)}
												</span>{" "}
												{copy?.cover ? (
													<img
														src={copy.cover.url}
														alt={t("duplicate.coverAlt", {
															side: t(
																side === "new"
																	? "duplicate.new"
																	: "duplicate.library",
															),
															w: copy.cover.width,
															h: copy.cover.height,
														})}
														className={styles.cover}
													/>
												) : (
													<span className={styles.noCover}>
														{t("duplicate.noCover")}
													</span>
												)}{" "}
												{copy?.cover && (
													<span className={styles.coverSize}>
														{t("duplicate.by", {
															w: copy.cover.width,
															h: copy.cover.height,
														})}
													</span>
												)}
											</div>
										</th>
									);
								})}
							</tr>
						</thead>
						<tbody>
							{facts.map(([name, show]) => {
								const values = sides.map((side) => {
									const copy = copyOf(side);
									return copy ? show(copy) : "";
								});
								const differs = values[0] !== values[1];
								return (
									<tr key={name} data-differs={differs || undefined}>
										<th scope="row">{name}</th>
										{values.map((value, index) => (
											<td
												key={sides[index]}
												data-recommended={
													duplicate.recommended === sides[index] || undefined
												}
											>
												{value}
											</td>
										))}
									</tr>
								);
							})}
						</tbody>
						<tfoot>
							<tr>
								<td />
								{sides.map((side) => (
									<td
										key={side}
										data-recommended={
											duplicate.recommended === side || undefined
										}
									>
										<button
											type="button"
											className={styles.button}
											data-recommended={
												duplicate.recommended === side || undefined
											}
											disabled={busy || why[side] !== null}
											onClick={() => void keep(side)}
										>
											{label(side)}
										</button>
										<span className={styles.consequence}>
											{t(
												side === "new"
													? "duplicate.keepNewMeans"
													: "duplicate.keepLibraryMeans",
											)}
										</span>
									</td>
								))}
							</tr>
						</tfoot>
					</table>

					{tracks && (
						<p className={styles.tracks}>
							{t("duplicate.tracksPaired", { n: tracks.paired })}
							{" · "}
							{tracks.length_differs === 0
								? t("duplicate.tracksSameLength")
								: t("duplicate.tracksLengthDiffer", {
										n: tracks.length_differs,
										max: Math.round(tracks.max_length_diff),
									})}
							{tracks.only_new > 0 &&
								` · ${t("duplicate.onlyNew", { n: tracks.only_new })}`}
							{tracks.only_library > 0 &&
								` · ${t("duplicate.onlyLibrary", { n: tracks.only_library })}`}
						</p>
					)}
				</>
			)}
			<Outcome view={current} />
			{refusal && <Alert>{refusal}</Alert>}
			{changed && <Alert>{t("review.changed")}</Alert>}
		</section>
	);
}
